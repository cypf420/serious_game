create table if not exists schema_migrations (
  version int unsigned primary key,
  filename varchar(255) not null unique,
  checksum char(71) not null,
  applied_at datetime(6) not null
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists roles (
  role_id varchar(32) primary key,
  description varchar(255) not null
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists permissions (
  permission_id varchar(64) primary key,
  description varchar(255) not null
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists account_roles (
  account_id varchar(64) not null,
  role_id varchar(32) not null,
  granted_at datetime(6) not null,
  granted_by varchar(64) null,
  primary key(account_id, role_id),
  constraint fk_account_roles_account foreign key(account_id) references accounts(account_id),
  constraint fk_account_roles_role foreign key(role_id) references roles(role_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists role_permissions (
  role_id varchar(32) not null,
  permission_id varchar(64) not null,
  primary key(role_id, permission_id),
  constraint fk_role_permissions_role foreign key(role_id) references roles(role_id),
  constraint fk_role_permissions_permission foreign key(permission_id) references permissions(permission_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists consent_documents (
  consent_version varchar(128) primary key,
  document_hash char(71) not null unique,
  model_provider varchar(128) not null,
  processing_region varchar(128) not null,
  retention_days_raw_text int unsigned not null,
  published_at datetime(6) not null,
  retired_at datetime(6) null,
  document_json json not null
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists consent_records (
  consent_record_id varchar(64) primary key,
  account_id varchar(64) not null,
  consent_version varchar(128) not null,
  document_hash char(71) not null,
  scopes_json json not null,
  signed_at datetime(6) not null,
  withdrawn_at datetime(6) null,
  withdrawal_reason varchar(500) null,
  record_json json not null,
  constraint fk_consent_account foreign key(account_id) references accounts(account_id),
  constraint fk_consent_document foreign key(consent_version) references consent_documents(consent_version),
  index idx_consent_account_signed(account_id, signed_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists research_subjects (
  research_subject_id varchar(64) primary key,
  account_id varchar(64) not null unique,
  created_at datetime(6) not null,
  retired_at datetime(6) null,
  identity_json json not null,
  constraint fk_research_subject_account foreign key(account_id) references accounts(account_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists experiments (
  experiment_id varchar(64) primary key,
  name varchar(255) not null,
  status varchar(32) not null,
  assignment_salt_hash char(71) not null,
  config_json json not null,
  created_at datetime(6) not null,
  published_at datetime(6) null,
  retired_at datetime(6) null
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists experiment_groups (
  experiment_group_id varchar(64) primary key,
  experiment_id varchar(64) not null,
  weight int unsigned not null,
  config_json json not null,
  constraint fk_experiment_group_experiment foreign key(experiment_id) references experiments(experiment_id),
  unique key uq_experiment_group(experiment_id, experiment_group_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists experiment_assignments (
  assignment_id varchar(64) primary key,
  research_subject_id varchar(64) not null,
  experiment_id varchar(64) not null,
  experiment_group_id varchar(64) not null,
  environment varchar(16) not null,
  package_content_hash char(71) not null,
  model_id varchar(128) not null,
  prompt_version varchar(64) not null,
  assigned_at datetime(6) not null,
  assignment_json json not null,
  constraint fk_assignment_subject foreign key(research_subject_id) references research_subjects(research_subject_id),
  constraint fk_assignment_experiment foreign key(experiment_id) references experiments(experiment_id),
  constraint fk_assignment_group foreign key(experiment_group_id) references experiment_groups(experiment_group_id),
  unique key uq_subject_experiment(research_subject_id, experiment_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists research_events (
  research_event_id varchar(64) primary key,
  research_subject_id varchar(64) not null,
  experiment_id varchar(64) null,
  experiment_group_id varchar(64) null,
  session_public_id varchar(128) not null,
  event_type varchar(64) not null,
  story_day int not null,
  structured_payload_json json not null,
  raw_text_ciphertext longtext null,
  consent_record_id varchar(64) null,
  created_at datetime(6) not null,
  constraint fk_research_event_subject foreign key(research_subject_id) references research_subjects(research_subject_id),
  constraint fk_research_event_consent foreign key(consent_record_id) references consent_records(consent_record_id),
  index idx_research_event_subject(research_subject_id, created_at),
  index idx_research_event_experiment(experiment_id, experiment_group_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists research_outbox (
  research_event_id varchar(64) primary key,
  research_subject_id varchar(64) not null,
  status varchar(32) not null default 'pending',
  attempt_count int unsigned not null default 0,
  lease_token varchar(128) null,
  lease_expires_at datetime(6) null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  payload_json json not null,
  index idx_research_outbox_status(status, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists export_jobs (
  export_job_id varchar(64) primary key,
  requested_by varchar(64) not null,
  approved_by varchar(64) null,
  purpose varchar(1000) not null,
  status varchar(32) not null,
  field_whitelist_json json not null,
  query_conditions_json json not null,
  consent_filter_json json not null,
  minimum_cell_size int unsigned not null,
  dataset_version varchar(128) null,
  file_hash char(71) null,
  expires_at datetime(6) null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  constraint fk_export_requester foreign key(requested_by) references accounts(account_id),
  constraint fk_export_approver foreign key(approved_by) references accounts(account_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists data_subject_requests (
  request_id varchar(64) primary key,
  account_id varchar(64) not null,
  request_type varchar(32) not null,
  status varchar(32) not null,
  request_json json not null,
  result_json json null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  completed_at datetime(6) null,
  constraint fk_data_subject_account foreign key(account_id) references accounts(account_id),
  index idx_data_subject_status(status, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists retention_jobs (
  retention_job_id varchar(64) primary key,
  policy_version varchar(128) not null,
  cutoff_at datetime(6) not null,
  status varchar(32) not null,
  result_json json null,
  created_at datetime(6) not null,
  completed_at datetime(6) null
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists privileged_access_audits (
  audit_id varchar(64) primary key,
  actor_account_id varchar(64) not null,
  permission_id varchar(64) not null,
  purpose varchar(1000) not null,
  target_type varchar(64) not null,
  target_id_hash char(71) not null,
  outcome varchar(32) not null,
  request_id varchar(128) null,
  created_at datetime(6) not null,
  audit_json json not null,
  constraint fk_privileged_actor foreign key(actor_account_id) references accounts(account_id),
  index idx_privileged_actor(actor_account_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;
