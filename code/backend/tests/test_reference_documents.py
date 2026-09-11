from types import SimpleNamespace as NS
import pytest
from serious_game_backend.application.reference_documents import catalog, resolve_references, hearing_facts, public_catalog
from serious_game_backend.domain.gameplay_governance import ArchiveRecord, MeetingRecord, GovernanceActionRecord, AdministrativeDocument
from serious_game_backend.domain.errors import ActionUnavailableError


def fixture():
    a = ArchiveRecord("a", "证据", "材料", "SECRET_RAW", "investigation", "x", 1, "read", read_at_days=[1], related_npc_ids=("tan",))
    session = NS(archive_records={"a": a}, meetings={}, governance_actions={}, administrative_documents={}, flags=set())
    package = NS(npc_profiles=[NS(npc_id="tan", name="谭")], households=[NS(representative_npc="tan")])
    project = lambda *args, **kwargs: {"player_sections": [{"heading": "材料", "body": "公开正文"}]}
    return session, package, project


def test_archive_requires_read_and_projects_only_public_sections():
    s,p,f = fixture()
    assert catalog(s,p,f)[0]["body"] == "材料\n公开正文"
    assert "SECRET_RAW" not in str(catalog(s,p,f))
    s.archive_records["a"].read_at_days = []
    assert catalog(s,p,f) == []
    with pytest.raises(ActionUnavailableError): resolve_references(s,p,["archive:a"],["tan"],f)


def test_reference_checks_actual_audience_and_all_recipients():
    s,p,f = fixture()
    assert resolve_references(s,p,["archive:a"],["tan"],f)[0]["title"] == "材料"
    for ids, audience in [(["archive:a"],["other"]),(["archive:a"],["tan","other"]),(["archive:a"]*2,["tan"]),(["forged"],["tan"])]:
        with pytest.raises(ActionUnavailableError): resolve_references(s,p,ids,audience,f)
    assert not any(k.startswith("_") for k in public_catalog(catalog(s,p,f))[0])


def test_meeting_body_does_not_expose_internal_metadata_and_tracks_actual_stage():
    s,p,f = fixture()
    a = GovernanceActionRecord("act","leadership_meeting",1,("tan",),(),variant_id="public_hearing",topic="旧案程序")
    m = MeetingRecord("m","act",1,"旧案程序",("tan",),"executive_decision","tan")
    m.transcript = [{"speaker_type":"npc","npc_name":"谭","text":"需要法审","model_id":"SECRET_MODEL","meeting_role":"SECRET_ROLE"}]
    s.governance_actions["act"] = a; s.meetings["m"] = m
    body = next(d["body"] for d in catalog(s,p,f) if d["id"] == "meeting:m")
    assert "需要法审" in body and "SECRET" not in body
    assert hearing_facts(s,"tan")["records"][0]["status"] == "started"
    m.status = "resolved"; a.status = "completed"
    assert hearing_facts(s,"tan")["records"][0]["status"] == "completed"
    assert hearing_facts(s,"other")["records"] == []
    a.status = "cancelled"
    assert hearing_facts(s,"tan")["records"][0]["status"] == "aborted"
    assert s.flags == set()


def test_published_scope_is_not_automatically_public_and_latest_version_is_read():
    s,p,f = fixture()
    d = AdministrativeDocument("d","hearing_notice","通知","published",1,"通知原文",1,"v",public_scope=("县级相关部门",))
    s.administrative_documents["d"] = d
    with pytest.raises(ActionUnavailableError): resolve_references(s,p,["document:d"],["tan"],f)
    d.public_scope = ("全村36户",); d.version = 2; d.content = "更新正文"
    r=resolve_references(s,p,["document:d"],["tan"],f)[0]
    assert (r["version"],r["body"]) == (2,"更新正文")
    assert s.flags == set()


def test_governance_reference_api_passes_real_material_and_rejects_forgery():
    from tests.test_gameplay_governance import GameplayGovernanceTests
    harness = GameplayGovernanceTests()
    harness.setUp()
    harness._resolve_opening()
    started = harness._post("/governance/actions", {
        "state_version": harness.state["state_version"], "action_kind": "household_visit",
        "target_ids": ["npc_zhou_dashan"], "topic": "核实搬迁诉求"}, expected=201)
    session = harness.runtime.sessions.get_owned(harness.session_id, "acct_gameplay_governance")
    session.archive_records["reference-test"] = ArchiveRecord("reference-test", "材料", "现场材料", "已核实住房需求", "interaction", "test", 1, "test", read_at_days=[1], related_npc_ids=("npc_zhou_dashan",))
    harness.runtime.sessions.save(session, expected_version=session.state_version)
    path=f"/api/game/session/{harness.session_id}/governance"
    response=harness.client.get(path+"/reference-documents",headers=harness.headers)
    assert response.status_code == 200
    assert any(d["id"] == "archive:reference-test" for d in response.json()["documents"])
    gateway=harness.runtime.gameplay_governance._npc_turns._gateway
    captured=[]
    class Capture:
        def __getattr__(self,name): return getattr(gateway,name)
        def run_turn(self,context):
            captured.append(context)
            return gateway.run_turn(context)
    harness.runtime.gameplay_governance._npc_turns._gateway=Capture()
    version=session.state_version
    endpoint=path+f"/actions/{started['action']['action_instance_id']}/turn"
    response=harness.client.post(endpoint,headers=harness.headers,json={"state_version":version,"player_text":"请根据材料说明住房诉求。","reference_ids":["forged"]})
    assert response.status_code == 409
    assert not captured
    response=harness.client.post(endpoint,headers=harness.headers,json={"state_version":version,"player_text":"请根据材料说明住房诉求。","reference_ids":["archive:reference-test"]})
    assert response.status_code == 200, response.text
    assert captured[0].player_reference_materials["referenced_documents"][0]["title"] == "现场材料"
