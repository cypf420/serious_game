create table if not exists runtime_accounts (
  account_id text primary key,
  username text not null unique,
  disabled integer not null default 0,
  created_at text not null,
  updated_at text not null,
  payload_json text not null
);

create table if not exists runtime_auth_sessions (
  token_hash text primary key,
  account_id text not null,
  expires_at text not null,
  revoked_at text null,
  payload_json text not null,
  foreign key(account_id) references runtime_accounts(account_id)
);
create index if not exists idx_runtime_auth_account
  on runtime_auth_sessions(account_id, expires_at);

create table if not exists runtime_consent_documents (
  consent_version text primary key,
  document_hash text not null unique,
  payload_json text not null
);

create table if not exists runtime_consent_records (
  consent_record_id text primary key,
  account_id text not null,
  consent_version text not null,
  signed_at text not null,
  withdrawn_at text null,
  payload_json text not null,
  foreign key(account_id) references runtime_accounts(account_id),
  foreign key(consent_version) references runtime_consent_documents(consent_version)
);
create index if not exists idx_runtime_consent_account
  on runtime_consent_records(account_id, signed_at);

create table if not exists runtime_research_subjects (
  research_subject_id text primary key,
  account_id text not null unique,
  retired_at text null,
  payload_json text not null,
  foreign key(account_id) references runtime_accounts(account_id)
);

create table if not exists runtime_experiment_assignments (
  assignment_id text primary key,
  research_subject_id text not null,
  experiment_id text not null,
  experiment_group_id text not null,
  environment text not null,
  payload_json text not null,
  unique(research_subject_id, experiment_id),
  foreign key(research_subject_id) references runtime_research_subjects(research_subject_id)
);

create table if not exists runtime_research_events (
  research_event_id text primary key,
  research_subject_id text not null,
  experiment_id text null,
  experiment_group_id text null,
  event_type text not null,
  story_day integer not null,
  created_at text not null,
  payload_json text not null,
  foreign key(research_subject_id) references runtime_research_subjects(research_subject_id)
);
create index if not exists idx_runtime_research_event_subject
  on runtime_research_events(research_subject_id, created_at);

create table if not exists runtime_privileged_access_audits (
  audit_id text primary key,
  actor_account_id text not null,
  permission text not null,
  purpose text not null,
  target_type text not null,
  target_id_hash text not null,
  created_at text not null,
  payload_json text not null
);

insert or ignore into runtime_schema_versions(version) values (3);
