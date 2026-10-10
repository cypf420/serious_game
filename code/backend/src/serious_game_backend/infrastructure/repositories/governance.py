from __future__ import annotations

from dataclasses import asdict
import json

from serious_game_backend.domain.governance import (
    DataSubjectRequest,
    ExportJob,
    PrivilegedAccessAudit,
    RetentionResult,
)
from serious_game_backend.infrastructure.repositories.codec import dumps
from serious_game_backend.infrastructure.repositories.sqlite import SqliteRuntimeStore
from serious_game_backend.infrastructure.repositories.mysql import MySQLRuntimeStore, _dt, _iso, _payload


def _export(value: str | dict) -> ExportJob:
    data = json.loads(value) if isinstance(value, str) else value
    data["field_whitelist"] = tuple(data["field_whitelist"])
    return ExportJob(**data)


class SqliteGovernanceRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def create_export(self, job: ExportJob) -> None:
        with self._store.connect() as c:
            c.execute("insert into runtime_export_jobs values (?,?,?,?,?,?)", (
                job.export_job_id, job.requested_by, job.approved_by, job.status,
                job.created_at, dumps(asdict(job)),
            ))

    def get_export(self, export_job_id: str) -> ExportJob | None:
        with self._store.connect() as c:
            row = c.execute("select payload_json from runtime_export_jobs where export_job_id=?", (export_job_id,)).fetchone()
        return _export(row["payload_json"]) if row else None

    def save_export(self, job: ExportJob) -> None:
        with self._store.connect() as c:
            cur = c.execute("update runtime_export_jobs set approved_by=?,status=?,payload_json=? where export_job_id=?", (
                job.approved_by, job.status, dumps(asdict(job)), job.export_job_id,
            ))
            if cur.rowcount != 1:
                raise ValueError("export not found")

    def research_export_rows(self, conditions: dict) -> tuple[dict, ...]:
        clauses, values = [], []
        for key in ("experiment_id", "experiment_group_id", "event_type"):
            if conditions.get(key) is not None:
                clauses.append(f"{key}=?"); values.append(conditions[key])
        sql = "select payload_json from runtime_research_events"
        if clauses: sql += " where " + " and ".join(clauses)
        with self._store.connect() as c:
            rows = c.execute(sql, values).fetchall()
        return tuple(json.loads(row["payload_json"]) for row in rows)

    def create_subject_request(self, request: DataSubjectRequest) -> None:
        with self._store.connect() as c:
            c.execute("insert into runtime_data_subject_requests values (?,?,?,?,?,?)", (
                request.request_id, request.account_id, request.request_type,
                request.status, request.created_at, dumps(asdict(request)),
            ))

    def get_subject_request(self, request_id: str) -> DataSubjectRequest | None:
        with self._store.connect() as c:
            row = c.execute("select payload_json from runtime_data_subject_requests where request_id=?", (request_id,)).fetchone()
        return DataSubjectRequest(**json.loads(row["payload_json"])) if row else None

    def save_subject_request(self, request: DataSubjectRequest) -> None:
        with self._store.connect() as c:
            cur = c.execute("update runtime_data_subject_requests set status=?,payload_json=? where request_id=?", (
                request.status, dumps(asdict(request)), request.request_id,
            ))
            if cur.rowcount != 1: raise ValueError("subject request not found")

    def subject_data(self, account_id: str) -> dict:
        with self._store.connect() as c:
            account = c.execute("select username,created_at from runtime_accounts where account_id=?", (account_id,)).fetchone()
            subject = c.execute("select research_subject_id from runtime_research_subjects where account_id=?", (account_id,)).fetchone()
            sessions = c.execute("select count(*) n from runtime_game_sessions where account_id=?", (account_id,)).fetchone()["n"]
            events = 0 if not subject else c.execute("select count(*) n from runtime_research_events where research_subject_id=?", (subject["research_subject_id"],)).fetchone()["n"]
        return {"account": dict(account) if account else None, "game_session_count": sessions, "research_event_count": events}

    def erase_subject(self, account_id: str) -> dict:
        with self._store.connect() as c:
            subject = c.execute("select research_subject_id from runtime_research_subjects where account_id=?", (account_id,)).fetchone()
            if subject:
                sid = subject["research_subject_id"]
                c.execute("delete from runtime_research_outbox where research_subject_id=?", (sid,))
                c.execute("delete from runtime_research_events where research_subject_id=?", (sid,))
                c.execute("delete from runtime_experiment_assignments where research_subject_id=?", (sid,))
                c.execute("delete from runtime_research_subjects where research_subject_id=?", (sid,))
            session_ids = [row[0] for row in c.execute("select session_id from runtime_game_sessions where account_id=?", (account_id,))]
            for sid in session_ids:
                c.execute("delete from runtime_llm_call_audits where session_id=?", (sid,))
                c.execute("delete from runtime_npc_memories where session_id=?", (sid,))
                c.execute("delete from runtime_operations where session_id=?", (sid,))
            c.execute("delete from runtime_game_sessions where account_id=?", (account_id,))
            c.execute("delete from runtime_session_requests where account_id=?", (account_id,))
            c.execute("delete from runtime_consent_records where account_id=?", (account_id,))
            c.execute("delete from runtime_auth_sessions where account_id=?", (account_id,))
            anonymous = "erased_" + account_id
            c.execute("update runtime_accounts set username=?,disabled=1,payload_json=? where account_id=?", (
                anonymous, dumps({"account_id": account_id, "username": anonymous, "password_hash": "!erased", "roles": [], "disabled": True}), account_id,
            ))
        return {"erased": True, "research_subject_removed": bool(subject), "game_sessions_removed": len(session_ids)}

    def append_privileged_audit(self, audit: PrivilegedAccessAudit) -> None:
        with self._store.connect() as c:
            c.execute("insert into runtime_privileged_access_audits values (?,?,?,?,?,?,?,?)", (
                audit.audit_id, audit.actor_account_id, audit.permission, audit.purpose,
                audit.target_type, audit.target_id_hash, audit.created_at, dumps(asdict(audit)),
            ))

    def apply_retention(self, *, cutoff_at: str, policy_version: str) -> RetentionResult:
        with self._store.connect() as c:
            rows = c.execute("select research_event_id,payload_json from runtime_research_events where created_at < ?", (cutoff_at,)).fetchall()
            raw_removed = 0
            for row in rows:
                payload = json.loads(row["payload_json"])
                if payload.get("raw_text_ciphertext"):
                    payload["raw_text_ciphertext"] = None; raw_removed += 1
                    c.execute("update runtime_research_events set payload_json=? where research_event_id=?", (dumps(payload), row["research_event_id"]))
            cur = c.execute("delete from runtime_auth_sessions where expires_at < ?", (cutoff_at,))
        return RetentionResult(policy_version, cutoff_at, raw_removed, cur.rowcount)


class MySQLGovernanceRepository:
    def __init__(self, store: MySQLRuntimeStore, research_store=None) -> None:
        self._store = store
        self._research_store = research_store or store

    def create_export(self, job: ExportJob) -> None:
        with self._store.connect() as c, c.cursor() as q:
            q.execute("""insert into export_jobs(export_job_id,requested_by,approved_by,purpose,status,field_whitelist_json,query_conditions_json,consent_filter_json,minimum_cell_size,dataset_version,file_hash,created_at,updated_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (
                job.export_job_id,job.requested_by,job.approved_by,job.purpose,job.status,dumps(list(job.field_whitelist)),dumps(job.query_conditions),dumps({"research_consent_required":True}),job.minimum_cell_size,job.dataset_version,job.file_hash,_dt(job.created_at),_dt(job.updated_at)))

    def get_export(self, export_job_id: str) -> ExportJob | None:
        with self._store.connect() as c, c.cursor() as q:
            q.execute("select * from export_jobs where export_job_id=%s", (export_job_id,)); row=q.fetchone()
        if not row: return None
        return ExportJob(export_job_id=row["export_job_id"],requested_by=row["requested_by"],approved_by=row["approved_by"],purpose=row["purpose"],status=row["status"],field_whitelist=tuple(_payload(row["field_whitelist_json"])),query_conditions=_payload(row["query_conditions_json"]),minimum_cell_size=row["minimum_cell_size"],dataset_version=row["dataset_version"],file_hash=row["file_hash"],created_at=_iso(row["created_at"]),updated_at=_iso(row["updated_at"]))

    def save_export(self, job: ExportJob) -> None:
        with self._store.connect() as c, c.cursor() as q:
            q.execute("update export_jobs set approved_by=%s,status=%s,dataset_version=%s,file_hash=%s,updated_at=%s where export_job_id=%s", (job.approved_by,job.status,job.dataset_version,job.file_hash,_dt(job.updated_at),job.export_job_id))
            if q.rowcount != 1: raise ValueError("export not found")

    def research_export_rows(self, conditions: dict) -> tuple[dict, ...]:
        clauses=[]; values=[]
        for key in ("experiment_id","experiment_group_id","event_type"):
            if conditions.get(key) is not None: clauses.append(f"{key}=%s"); values.append(conditions[key])
        sql="select research_subject_id,experiment_id,experiment_group_id,event_type,story_day,created_at,structured_payload_json from research_events" + ((" where "+" and ".join(clauses)) if clauses else "")
        with self._research_store.connect() as c, c.cursor() as q: q.execute(sql,values); rows=q.fetchall()
        return tuple({
            "research_subject_id": row["research_subject_id"],
            "experiment_id": row["experiment_id"],
            "experiment_group_id": row["experiment_group_id"],
            "event_type": row["event_type"], "story_day": row["story_day"],
            "created_at": _iso(row["created_at"]),
            "structured_payload": _payload(row["structured_payload_json"]),
        } for row in rows)

    def create_subject_request(self, request: DataSubjectRequest) -> None:
        request_payload = self._store.protect_json(
            {"reason": request.reason}, purpose=f"subject_request_input:{request.request_id}"
        )
        with self._store.connect() as c, c.cursor() as q:
            q.execute("insert into data_subject_requests(request_id,account_id,request_type,status,request_json,result_json,created_at,updated_at,completed_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s)", (request.request_id,request.account_id,request.request_type,request.status,request_payload,None,_dt(request.created_at),_dt(request.updated_at),None))

    def get_subject_request(self, request_id: str) -> DataSubjectRequest | None:
        with self._store.connect() as c, c.cursor() as q: q.execute("select * from data_subject_requests where request_id=%s",(request_id,)); row=q.fetchone()
        if not row:return None
        result = (self._store.unprotect_json(
            row["result_json"], purpose=f"subject_request:{request_id}"
        ) if row["result_json"] else None)
        request_payload = self._store.unprotect_json(
            row["request_json"], purpose=f"subject_request_input:{request_id}"
        )
        return DataSubjectRequest(request_id=row["request_id"],account_id=row["account_id"],request_type=row["request_type"],status=row["status"],reason=request_payload.get("reason"),result=result,created_at=_iso(row["created_at"]),updated_at=_iso(row["updated_at"]),completed_at=_iso(row["completed_at"]))

    def save_subject_request(self, request: DataSubjectRequest) -> None:
        protected = (self._store.protect_json(
            request.result, purpose=f"subject_request:{request.request_id}"
        ) if request.result is not None else None)
        with self._store.connect() as c, c.cursor() as q: q.execute("update data_subject_requests set status=%s,result_json=%s,updated_at=%s,completed_at=%s where request_id=%s",(request.status,protected,_dt(request.updated_at),_dt(request.completed_at),request.request_id))

    def subject_data(self, account_id: str) -> dict:
        with self._store.connect() as c, c.cursor() as q:
            q.execute("select username,created_at from accounts where account_id=%s",(account_id,)); account=q.fetchone()
            q.execute("select count(*) n from game_sessions where account_id=%s",(account_id,)); sessions=q.fetchone()["n"]
            q.execute("select research_subject_id from research_subjects where account_id=%s",(account_id,)); subject=q.fetchone()
        if subject:
            with self._research_store.connect() as c, c.cursor() as q:
                q.execute("select count(*) n from research_events where research_subject_id=%s",(subject["research_subject_id"],)); events=q.fetchone()["n"]
        else:
            events=0
        return {"account":{"username":account["username"],"created_at":_iso(account["created_at"])} if account else None,"game_session_count":sessions,"research_event_count":events}

    def erase_subject(self, account_id: str) -> dict:
        with self._store.connect() as c, c.cursor() as q:
            q.execute("select research_subject_id from research_subjects where account_id=%s",(account_id,)); row=q.fetchone()
        if row:
            with self._research_store.connect() as c, c.cursor() as q:
                q.execute("delete from research_events where research_subject_id=%s",(row["research_subject_id"],))
        with self._store.connect() as c, c.cursor() as q:
            if row:
                sid=row["research_subject_id"]
                q.execute("delete from research_outbox where research_subject_id=%s",(sid,)); q.execute("delete from experiment_assignments where research_subject_id=%s",(sid,)); q.execute("delete from research_subjects where research_subject_id=%s",(sid,))
            q.execute("update auth_sessions set revoked_at=utc_timestamp(6) where account_id=%s and revoked_at is null",(account_id,))
            q.execute("update consent_records set withdrawn_at=coalesce(withdrawn_at,utc_timestamp(6)),withdrawal_reason='data subject erasure' where account_id=%s",(account_id,))
            for table in (
                "dialogue_logs", "action_logs", "event_logs", "night_logs",
                "llm_call_audits", "npc_memories", "decision_instances",
            ):
                q.execute(f"delete from {table} where account_id=%s", (account_id,))
            q.execute("delete from game_snapshots where account_id=%s", (account_id,))
            q.execute("delete from game_actions where account_id=%s", (account_id,))
            q.execute("delete from game_sessions where account_id=%s", (account_id,))
            q.execute("delete from game_session_requests where account_id=%s", (account_id,))
            q.execute("update accounts set username=%s,password_hash='!erased',disabled=true,updated_at=utc_timestamp(6) where account_id=%s",("erased_"+account_id,account_id))
        return {"erased":True,"research_subject_removed":bool(row),"game_data_removed":True,"account_disabled":True}

    def append_privileged_audit(self, audit: PrivilegedAccessAudit) -> None:
        with self._store.connect() as c, c.cursor() as q: q.execute("insert into privileged_access_audits(audit_id,actor_account_id,permission_id,purpose,target_type,target_id_hash,outcome,request_id,created_at,audit_json) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(audit.audit_id,audit.actor_account_id,audit.permission,audit.purpose,audit.target_type,audit.target_id_hash,audit.outcome,audit.request_id,_dt(audit.created_at),dumps(asdict(audit))))

    def apply_retention(self, *, cutoff_at: str, policy_version: str) -> RetentionResult:
        with self._research_store.connect() as c, c.cursor() as q:
            q.execute("update research_events set raw_text_ciphertext=null where created_at < %s and raw_text_ciphertext is not null",(_dt(cutoff_at),)); raw=q.rowcount
        with self._store.connect() as c, c.cursor() as q:
            q.execute("delete from auth_sessions where expires_at < %s",(_dt(cutoff_at),)); auth=q.rowcount
            q.execute("insert into retention_jobs(retention_job_id,policy_version,cutoff_at,status,result_json,created_at,completed_at) values(%s,%s,%s,'completed',%s,utc_timestamp(6),utc_timestamp(6))",("ret_"+__import__('secrets').token_hex(16),policy_version,_dt(cutoff_at),dumps({"raw_research_text_removed":raw,"auth_sessions_removed":auth})))
        return RetentionResult(policy_version,cutoff_at,raw,auth)
