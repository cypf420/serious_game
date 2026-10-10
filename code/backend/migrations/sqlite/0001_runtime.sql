create table if not exists runtime_schema_versions (
  version integer primary key,
  applied_at text not null default current_timestamp
);

create table if not exists runtime_game_sessions (
  session_id text primary key,
  account_id text not null,
  status text not null,
  state_version integer not null,
  processing_action_id text null,
  updated_at text not null,
  payload_json text not null
);
create index if not exists idx_runtime_sessions_account
  on runtime_game_sessions(account_id, status, updated_at);

create table if not exists runtime_operations (
  operation_id text primary key,
  account_id text not null,
  session_id text not null,
  client_action_id text not null,
  status text not null,
  payload_json text not null,
  unique(account_id, session_id, client_action_id)
);

create table if not exists runtime_session_requests (
  account_id text not null,
  client_request_id text not null,
  status text not null,
  payload_json text not null,
  primary key(account_id, client_request_id)
);

create table if not exists runtime_llm_call_audits (
  audit_id text primary key,
  session_id text not null,
  operation_id text not null,
  request_hash text not null,
  status text not null,
  payload_json text not null
);
create index if not exists idx_runtime_llm_session
  on runtime_llm_call_audits(session_id, status);
create index if not exists idx_runtime_llm_operation
  on runtime_llm_call_audits(operation_id, request_hash, status);

create table if not exists runtime_npc_memories (
  memory_id text primary key,
  session_id text not null,
  npc_id text not null,
  valid_from_day integer not null,
  expires_after_day integer null,
  invalidated_at text null,
  created_at text not null,
  payload_json text not null
);
create index if not exists idx_runtime_memory_lookup
  on runtime_npc_memories(session_id, npc_id, valid_from_day);

insert or ignore into runtime_schema_versions(version) values (1);
insert or ignore into runtime_schema_versions(version) values (2);
