"""Signature accounting regressions using real application/API paths and a test-only dialogue double."""
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from fastapi.testclient import TestClient
from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from serious_game_backend.application.contract_accounting import migrate_contract_accounting, ACCOUNTING_VERSION
from serious_game_backend.domain.errors import ActionUnavailableError
from serious_game_backend.domain.llm import GovernanceLLMResult
from serious_game_backend.domain.gameplay_governance import HouseholdContract, ResourceReservation

class ContractAccountingTests(unittest.TestCase):
    def setUp(self):
        settings=Settings(environment='test',repository='memory',role_llm_provider='none',default_package_id='pkg_gameplay_v3',content_root=Path(__file__).resolve().parents[1]/'content/packages')
        self.runtime=build_container(settings); self.client=TestClient(create_app(settings,self.runtime))
        self.headers={'X-Account-ID':'accounting-tests'}
        r=self.client.post('/api/game/session',headers=self.headers,json={'client_request_id':'accounting-session'})
        self.assertEqual(201,r.status_code,r.text)
        self.sid=r.json()['session_id']; self.base=f'/api/game/session/{self.sid}'
        s=self.session(); s.pending_decision=None; s.pending_decision_queue.clear()
        s.game_state=replace(s.game_state,story_day=10,action_points=8)
        s.known_npc_ids.add('npc_zhou_dashan'); s.encountered_npc_ids.add('npc_zhou_dashan')
        self.save(s)
    def session(self): return self.runtime.sessions.get_owned(self.sid,'accounting-tests')
    def save(self,s): self.runtime.sessions.save(s,expected_version=s.state_version)
    def post(self,path,payload=None,status=200):
        r=self.client.post(self.base+path,headers=self.headers,json={'state_version':self.session().state_version,**(payload or {})})
        self.assertEqual(status,r.status_code,r.text); return r.json()
    def draft(self,*,missing_grave=False,npc="npc_zhou_dashan",household_id=None):
        descriptor=next(x for x in self.client.get(self.base+'/opportunities',headers=self.headers).json()['person_actions'] if x['npc_id']==npc and x['action_id']=='household_visit')
        started=self.post('/governance/actions',{'action_kind':'household_visit','variant_id':descriptor['variant_id'],'location_id':descriptor['legal_location_ids'][0],'target_ids':[npc],'topic':'逐户协商'},201)
        self.action_id=started['action']['action_instance_id']
        proposed=self.post(f'/governance/actions/{self.action_id}/prepare-contracts')
        batch=proposed['batch']['batch_id']
        confirmed=self.post(f'/governance/contract-batches/{batch}/confirm',{'confirmed':True})
        c=next(x for x in confirmed['contracts'] if x['household_id']==(household_id or ('ZDS-01' if missing_grave else 'ZDS-03')))
        self.cid=c['contract_id']
        payload={'state_version':self.session().state_version,'policy_document_id':'doc_compensation_policy_v1','cash_amount':90,'budget_envelope':'property_land','housing_resource_id':'housing_d1_120','service_allocations':{'lead_recheck_slot':1},'payment_day':20,'move_out_day':60,'housing_delivery_day':60,'transition_months':0,'public_window_reward':False,'approval_document_ids':[]}
        # Exact standard cash from the authoritative household table, not fabricated fact flags.
        package=self.runtime.packages.get('pkg_gameplay_v3')
        household=next(h for h in package.households if h.household_id==c['household_id'])
        payload['cash_amount']=self.runtime.gameplay_governance._standard_cash(package,household,months=0,reward=False)
        self.cash=payload['cash_amount']
        r=self.client.put(self.base+f'/governance/contracts/{self.cid}/terms',headers=self.headers,json=payload)
        self.assertEqual(200,r.status_code,r.text)
        return r.json()
    def review(self,status=200): return self.post(f'/governance/contracts/{self.cid}/review',status=status)
    def test_signature_debits_cash_housing_and_count_together(self):
        self.draft(); before=self.session(); result=self.review(); after=self.session()
        self.assertEqual('signed',result['contract']['status'])
        self.assertEqual(before.game_state.budget_remaining-self.cash,after.game_state.budget_remaining)
        self.assertEqual(before.game_state.budget_paid+self.cash,after.game_state.budget_paid)
        self.assertEqual(before.game_state.signed_households+1,after.game_state.signed_households)
        allocated=[x for x in after.resource_reservations if x.owner_id==self.cid]
        self.assertEqual({'budget:property_land':self.cash,'housing_d1_120':1,'lead_recheck_slot':1},{x.resource_id:x.quantity for x in allocated})
        self.assertEqual({'allocated'},{x.status for x in allocated})
        self.assertEqual(10,after.household_contracts[self.cid].term_sheet['payment_day'])
    def test_nonacceptance_does_not_deduct_or_reveal_hidden_checklist(self):
        self.draft(missing_grave=True); before=self.session(); response=self.review(); after=self.session()
        self.assertNotEqual('signed',response['contract']['status'])
        self.assertEqual(before.game_state.budget_remaining,after.game_state.budget_remaining)
        self.assertEqual(before.game_state.signed_households,after.game_state.signed_households)
        self.assertFalse(any(x.owner_id==self.cid for x in after.resource_reservations))
        self.assertNotIn('missing_hard_conditions',str(response))
    def test_repeat_review_sign_and_day_end_do_not_charge_twice(self):
        self.draft(); self.review(); before=self.session()
        self.review(); self.post(f'/governance/contracts/{self.cid}/sign',{'confirmed':True})
        after=self.session()
        package=self.runtime.packages.get('pkg_gameplay_v3')
        after.game_state=replace(after.game_state,story_day=25)
        self.assertEqual([],self.runtime.gameplay_governance.settle_due_contracts(after,package))
        self.assertEqual(before.game_state.budget_remaining,after.game_state.budget_remaining)
        self.assertEqual(before.game_state.signed_households,after.game_state.signed_households)
        self.assertEqual(before.resource_ledger_entries,after.resource_ledger_entries)
    def test_cash_shortage_rolls_back_entire_review(self):
        self.draft(); s=self.session(); s.game_state=replace(s.game_state,budget_remaining=0); self.save(s)
        before=self.session(); self.review(409); self.assertEqual(before,self.session())
    def test_stock_shortage_rolls_back_entire_review(self):
        self.draft(); s=self.session()
        s.resource_reservations.append(ResourceReservation('exhaust','contract','another','housing_d1_120',7,'allocated',10))
        self.save(s); before=self.session(); self.review(409); self.assertEqual(before,self.session())
    def test_explicit_npc_rejection_does_not_spend(self):
        self.draft(); before=self.session()
        # Unbounded model refusals no longer veto an eligible scheme.
        with patch.object(self.runtime.gameplay_governance._gateway,'run_governance_task',return_value=GovernanceLLMResult(task='review_contract', data={'decision':'reject','reason':'房子和补偿都安排到了，我同意。'},model_id='test-ai')) as call:
            response=self.review()
        self.assertEqual(call.call_count, 1)
        self.assertEqual(call.call_args.args[0].payload['confirmed_decision'], 'accept')
        after=self.session()
        self.assertEqual('signed',response['contract']['status'])
        self.assertEqual(before.game_state.budget_remaining-self.cash,after.game_state.budget_remaining)
        self.assertEqual(before.game_state.signed_households+1,after.game_state.signed_households)
    def test_stale_review_retry_does_not_spend_again(self):
        self.draft(); version=self.session().state_version; self.review(); before=self.session()
        self.post(f'/governance/contracts/{self.cid}/review',{'state_version':version},409)
        self.assertEqual(before,self.session())
    def test_api_viewing_invitation_executes_scoped_scene_and_unlocks_signing(self):
        # Day-50 fixture tests the full API action turn, not a full story route.
        s=self.session(); s.game_state=replace(s.game_state,story_day=50)
        s.known_npc_ids.add('npc_lao_juetou'); s.encountered_npc_ids.add('npc_lao_juetou')
        self.save(s)
        self.draft(npc='npc_lao_juetou',household_id='LAO-01')
        before=self.session()
        from serious_game_backend.application.contract_facts import resolve_contract_facts
        p=self.runtime.packages.get('pkg_gameplay_v3')
        self.assertFalse(resolve_contract_facts(before,p,before.household_contracts[self.cid])['real_unit_viewed'])
        self.post(f'/governance/actions/{self.action_id}/turn',{'player_text':'我们现在去看合同里这套可入住的安置房，好吗？'})
        after=self.session()
        self.assertTrue(resolve_contract_facts(after,p,after.household_contracts[self.cid])['real_unit_viewed'])
        self.assertEqual(before.game_state.budget_remaining,after.game_state.budget_remaining)
        self.assertEqual(before.resource_reservations,after.resource_reservations)
        self.assertTrue(any(e.scene_id=='C06_S10' for e in after.narrative_feed))
        result=self.review()
        self.assertEqual('signed',result['contract']['status'])
    def test_public_governance_hides_private_demands_and_retired_http_commands_are_noops(self):
        s=self.session()
        for demand in self.runtime.packages.get('pkg_gameplay_v3').npc_demands:
            s.npc_demand_states[demand.demand_id]={'npc_id':demand.npc_id,'status':'acknowledged','history':[]}
        self.save(s)
        response=self.client.get(self.base+'/governance',headers=self.headers)
        self.assertEqual(200,response.status_code,response.text)
        self.assertEqual([],response.json().get('npc_demands',[]))
        self.assertNotIn('allowed_transitions',response.text)
        before=self.session()
        for transition in ('acknowledged','committed','satisfied','lawfully_refused','breached','expired'):
            self.post('/governance/npc-demands/demand_wu_xiuying/dispose',{'transition':transition},422 if transition == 'expired' else 409)
            self.assertEqual(before,self.session())
    def test_cross_day_signature_uses_signature_day_payment_without_stale_text(self):
        drafted=self.draft()
        text=drafted['contract']['contract_text']
        self.assertIn('签署当日付款',text)
        self.assertNotIn('付款日：D10',text)
        s=self.session(); s.game_state=replace(s.game_state,story_day=11)
        self.save(s)
        result=self.review()
        self.assertEqual('signed',result['contract']['status'])
        self.assertEqual(text,result['contract']['contract_text'])
        after=self.session()
        payments=[e for e in after.resource_ledger_entries if e.get('source_id')==self.cid and e.get('change_kind')=='payment']
        self.assertEqual([11],[e['story_day'] for e in payments])
    def test_expired_public_schedule_is_rejected_atomically(self):
        for field in ('housing_delivery_day','move_out_day'):
            with self.subTest(field=field):
                self.setUp()
                draft=self.draft()
                # Keep text/hash consistent through the public terms endpoint.
                terms=dict(draft['contract']['term_sheet'])
                terms.pop('policy_minimum_cash',None)
                terms.pop('payment_timing',None)
                # Keep the draft valid without an uncovered housing gap; this
                # regression concerns expiry after saving, not transition rules.
                terms[field]=10
                if field == 'move_out_day':
                    terms['housing_delivery_day']=10
                r=self.client.put(self.base+f'/governance/contracts/{self.cid}/terms',
                    headers=self.headers,json={'state_version':self.session().state_version,**terms})
                self.assertEqual(200,r.status_code,r.text)
                s=self.session(); s.game_state=replace(s.game_state,story_day=11); self.save(s)
                before=self.session()
                result=self.review(409)
                self.assertIn('日期已经过去',str(result))
                self.assertEqual(before,self.session())
    def test_offline_sqlite_migration_dry_run_backup_snapshot_and_repeat(self):
        import json
        import sqlite3
        from contextlib import closing
        import subprocess
        import sys
        from tempfile import TemporaryDirectory
        from serious_game_backend.infrastructure.repositories.sqlite import SqliteRuntimeStore, SqliteGameSessionRepository
        from serious_game_backend.infrastructure.repositories.codec import encode_session
        from serious_game_backend.domain.gameplay_governance import ContractVersion
        s=self.session(); s.state_values.pop('contract_accounting',None)
        c=self.legacy(s,'legacy-unpaid',20)
        c.signed_hash='historical-signed-hash'
        c.versions=[ContractVersion(version=1,text='原签署正文保持不变。',term_hash='old-term-hash',
                                    text_hash='old-text-hash',created_by='historical')]
        c.current_version=1
        before=json.loads(json.dumps(encode_session(s)))
        with TemporaryDirectory(prefix='contract-accounting-test-') as directory:
            db=Path(directory)/'progress.db'
            sessions=SqliteGameSessionRepository(SqliteRuntimeStore(db)); sessions.create(s)
            tool=Path(__file__).resolve().parents[1]/'tools/migrate_contract_accounting.py'
            command=[sys.executable,str(tool),'--database',str(db),'--session-id',s.session_id]
            def run(*args):
                result=subprocess.run(command+list(args),capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(0,result.returncode,result.stderr)
                return result
            run()
            self.assertEqual(before,json.loads(json.dumps(encode_session(sessions.get_owned(s.session_id,s.account_id)))))
            self.assertEqual([],list(Path(directory).glob('*.bak')))
            run('--apply')
            backups=list(Path(directory).glob('progress.db.before-contract-*.bak'))
            self.assertEqual(1,len(backups))
            with closing(sqlite3.connect(backups[0])) as connection:
                saved=json.loads(connection.execute('select payload_json from runtime_game_sessions where session_id=?',(s.session_id,)).fetchone()[0])
            self.assertEqual(before,saved)
            after=sessions.get_owned(s.session_id,s.account_id)
            self.assertEqual(s.game_state.budget_remaining-20,after.game_state.budget_remaining)
            self.assertEqual(s.state_version+1,after.state_version)
            self.assertEqual(c.signed_hash,after.household_contracts[c.contract_id].signed_hash)
            self.assertEqual(c.versions,after.household_contracts[c.contract_id].versions)
            with closing(sqlite3.connect(db)) as connection:
                versions=[r[0] for r in connection.execute('select state_version from runtime_game_snapshots order by state_version')]
            self.assertEqual([s.state_version,after.state_version],versions)
            snapshot=encode_session(after)
            run('--apply')
            self.assertEqual(backups,list(Path(directory).glob('progress.db.before-contract-*.bak')))
            self.assertEqual(snapshot,encode_session(sessions.get_owned(s.session_id,s.account_id)))
            with closing(sqlite3.connect(db)) as connection:
                self.assertEqual(2,connection.execute('select count(*) from runtime_game_snapshots').fetchone()[0])
    def legacy(self,s,cid,cash,*,paid=False,status='signed'):
        c=HouseholdContract(cid,'legacy','ZDS-03','周家人',None,1,status=status,term_sheet={'cash_amount':cash,'budget_envelope':'property_land','housing_resource_id':'housing_d1_120','service_allocations':{}},fulfillment={'cash_paid':paid},reserved_until_day=15)
        s.household_contracts[cid]=c
        for rid,q in [('budget:property_land',cash),('housing_d1_120',1)]:
            s.resource_reservations.append(ResourceReservation(cid+rid,'contract',cid,rid,q,'delivered' if paid else 'committed',1))
        return c
    def test_migration_paid_unpaid_draft_old_npc_holds_and_idempotence(self):
        s=self.session(); s.state_values.pop('contract_accounting',None)
        self.legacy(s,'paid',10,paid=True); self.legacy(s,'unpaid',20); self.legacy(s,'draft',30,status='accepted')
        s.resource_reservations.append(ResourceReservation('npc-hold','npc_demand','demand','audit_slot',1,'committed',1))
        s.resource_reservations.append(ResourceReservation('npc-delivered','npc_demand','old','hearing_slot',1,'delivered',1))
        before=s.game_state
        self.assertTrue(migrate_contract_accounting(s))
        self.assertEqual(before.budget_remaining-20,s.game_state.budget_remaining)
        self.assertEqual(before.budget_paid+20,s.game_state.budget_paid)
        self.assertEqual('draft',s.household_contracts['draft'].status)
        self.assertEqual({'allocated'},{r.status for r in s.resource_reservations if r.owner_id in {'paid','unpaid'}})
        self.assertEqual({'released'},{r.status for r in s.resource_reservations if r.owner_id in {'draft','demand'}})
        self.assertEqual('delivered',next(r for r in s.resource_reservations if r.reservation_id=='npc-delivered').status)
        self.assertEqual(ACCOUNTING_VERSION,s.state_values['contract_accounting'])
        snapshot=deepcopy(s); self.assertFalse(migrate_contract_accounting(s)); self.assertEqual(snapshot,s)
    def test_migration_bad_ledger_leaves_all_state_unchanged(self):
        s=self.session(); s.state_values.pop('contract_accounting',None); self.legacy(s,'broken',20)
        s.resource_reservations.pop(); before=deepcopy(s)
        with self.assertRaises(ActionUnavailableError): migrate_contract_accounting(s)
        self.assertEqual(before,s)
    def test_migration_insufficient_cash_leaves_all_state_unchanged(self):
        s=self.session(); s.state_values.pop('contract_accounting',None); self.legacy(s,'unpaid',20)
        s.game_state=replace(s.game_state,budget_remaining=10); before=deepcopy(s)
        with self.assertRaises(ActionUnavailableError): migrate_contract_accounting(s)
        self.assertEqual(before,s)
