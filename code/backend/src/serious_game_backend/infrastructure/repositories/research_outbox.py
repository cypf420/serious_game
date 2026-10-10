from __future__ import annotations

import json

from serious_game_backend.domain.research import ResearchEvent
from serious_game_backend.infrastructure.repositories.codec import dumps
from serious_game_backend.infrastructure.repositories.sqlite import SqliteRuntimeStore
from serious_game_backend.infrastructure.repositories.mysql import MySQLRuntimeStore, _dt, _payload


class NullResearchOutboxRepository:
    def drain(self, limit: int = 100) -> int:
        return 0


class SqliteResearchOutboxRepository:
    def __init__(self, store: SqliteRuntimeStore) -> None:
        self._store = store

    def drain(self, limit: int = 100) -> int:
        with self._store.connect() as c:
            rows = c.execute("select * from runtime_research_outbox where status='pending' order by created_at limit ?", (limit,)).fetchall()
            for row in rows:
                event = ResearchEvent(**json.loads(row["payload_json"]))
                c.execute("""insert or ignore into runtime_research_events(research_event_id,research_subject_id,experiment_id,experiment_group_id,event_type,story_day,created_at,payload_json) values(?,?,?,?,?,?,?,?)""", (
                    event.research_event_id,event.research_subject_id,event.experiment_id,event.experiment_group_id,event.event_type,event.story_day,event.created_at,dumps(event.__dict__) if hasattr(event,"__dict__") else row["payload_json"],
                ))
                c.execute("update runtime_research_outbox set status='dispatched',attempt_count=attempt_count+1 where research_event_id=?", (event.research_event_id,))
        return len(rows)


class MySQLResearchOutboxRepository:
    def __init__(self, store: MySQLRuntimeStore, research_store=None) -> None:
        self._store = store
        self._research_store = research_store or store

    def drain(self, limit: int = 100) -> int:
        with self._store.connect() as c, c.cursor() as q:
            q.execute("select * from research_outbox where status='pending' order by created_at limit %s for update skip locked", (limit,))
            rows=q.fetchall()
        for row in rows:
            event=ResearchEvent(**_payload(row["payload_json"]))
            with self._research_store.connect() as c, c.cursor() as q:
                q.execute("""insert ignore into research_events(research_event_id,research_subject_id,experiment_id,experiment_group_id,session_public_id,event_type,story_day,structured_payload_json,raw_text_ciphertext,consent_record_id,created_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (event.research_event_id,event.research_subject_id,event.experiment_id,event.experiment_group_id,event.session_public_id,event.event_type,event.story_day,dumps(event.structured_payload),event.raw_text_ciphertext,event.consent_record_id,_dt(event.created_at)))
            with self._store.connect() as c, c.cursor() as q:
                q.execute("update research_outbox set status='dispatched',attempt_count=attempt_count+1,updated_at=utc_timestamp(6) where research_event_id=%s and status='pending'", (event.research_event_id,))
        return len(rows)
