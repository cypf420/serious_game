create table if not exists runtime_research_outbox (
  research_event_id text primary key,
  research_subject_id text not null,
  status text not null default 'pending',
  attempt_count integer not null default 0,
  created_at text not null,
  payload_json text not null
);
create index if not exists idx_runtime_research_outbox_status
  on runtime_research_outbox(status, created_at);

insert or ignore into runtime_schema_versions(version) values (4);
