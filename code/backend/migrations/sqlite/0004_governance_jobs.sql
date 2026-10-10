create table if not exists runtime_export_jobs (
  export_job_id text primary key,
  requested_by text not null,
  approved_by text null,
  status text not null,
  created_at text not null,
  payload_json text not null
);

create table if not exists runtime_data_subject_requests (
  request_id text primary key,
  account_id text not null,
  request_type text not null,
  status text not null,
  created_at text not null,
  payload_json text not null
);

insert or ignore into runtime_schema_versions(version) values (5);
