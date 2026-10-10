-- MySQL 8.0+ 权威运行时基线。
-- DDL 与 code/backend/src 的仓储端口对应；执行前由正式迁移工具登记版本。

create table if not exists accounts (
  account_id varchar(64) primary key,
  username varchar(128) not null,
  password_hash varchar(255) not null,
  password_hash_scheme varchar(32) not null,
  role varchar(32) not null,
  disabled boolean not null default false,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  metadata_json json not null,
  unique key uq_accounts_username(username)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists auth_sessions (
  token_hash varchar(128) primary key,
  account_id varchar(64) not null,
  csrf_token_hash varchar(128) not null,
  created_at datetime(6) not null,
  last_seen_at datetime(6) not null,
  expires_at datetime(6) not null,
  revoked_at datetime(6) null,
  constraint fk_auth_sessions_account foreign key(account_id) references accounts(account_id),
  index idx_auth_sessions_account(account_id, expires_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists script_packages (
  package_id varchar(128) not null,
  package_version varchar(64) not null,
  content_hash char(71) not null,
  status varchar(16) not null,
  immutable_uri varchar(1024) not null,
  manifest_json json not null,
  created_at datetime(6) not null,
  published_at datetime(6) null,
  retired_at datetime(6) null,
  primary key(package_id, content_hash),
  unique key uq_script_packages_hash(content_hash)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists game_session_requests (
  account_id varchar(64) not null,
  client_request_id varchar(128) not null,
  request_hash char(71) not null,
  session_id varchar(64) null,
  status varchar(32) not null,
  response_json json null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  primary key(account_id, client_request_id),
  constraint fk_game_session_requests_account foreign key(account_id) references accounts(account_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists game_sessions (
  session_id varchar(64) primary key,
  account_id varchar(64) not null,
  package_id varchar(128) not null,
  package_version varchar(64) not null,
  package_content_hash char(71) not null,
  status varchar(32) not null,
  state_version bigint unsigned not null default 1,
  processing_action_id varchar(64) null,
  pending_decision_id varchar(128) null,
  random_seed varchar(128) not null,
  consent_record_id varchar(64) null,
  environment varchar(16) not null,
  experiment_group_id varchar(64) null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  current_snapshot_json json not null,
  metadata_json json not null,
  constraint fk_game_sessions_account foreign key(account_id) references accounts(account_id),
  constraint fk_game_sessions_package foreign key(package_id, package_content_hash)
    references script_packages(package_id, content_hash),
  index idx_game_sessions_account_updated(account_id, updated_at),
  index idx_game_sessions_package(package_id, package_content_hash)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists game_snapshots (
  snapshot_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  reason varchar(64) not null,
  story_day int not null,
  action_index int not null,
  state_version bigint unsigned not null,
  snapshot_json json not null,
  json_file_path varchar(512) null,
  created_at datetime(6) not null,
  constraint fk_game_snapshots_session foreign key(session_id) references game_sessions(session_id),
  constraint fk_game_snapshots_account foreign key(account_id) references accounts(account_id),
  unique key uq_game_snapshots_session_version(session_id, state_version),
  index idx_game_snapshots_session_created(session_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists game_actions (
  operation_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  client_action_id varchar(128) not null,
  request_hash char(71) not null,
  input_mode varchar(32) not null,
  opportunity_id varchar(128) null,
  action_id varchar(128) null,
  decision_id varchar(128) null,
  option_id varchar(128) null,
  base_state_version bigint unsigned not null,
  committed_state_version bigint unsigned null,
  status varchar(32) not null,
  processing_worker_token varchar(128) null,
  lease_expires_at datetime(6) null,
  attempt_count int unsigned not null default 1,
  request_json json not null,
  response_json json null,
  error_json json null,
  created_at datetime(6) not null,
  updated_at datetime(6) not null,
  constraint fk_game_actions_session foreign key(session_id) references game_sessions(session_id),
  constraint fk_game_actions_account foreign key(account_id) references accounts(account_id),
  unique key uq_game_actions_idempotency(account_id, client_action_id),
  index idx_game_actions_session_status(session_id, status, updated_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists decision_instances (
  event_instance_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  decision_id varchar(128) not null,
  state varchar(32) not null,
  option_ids_json json not null,
  presentation_json json not null,
  precondition_snapshot_json json not null,
  presented_state_version bigint unsigned not null,
  resolved_option_id varchar(128) null,
  resolution_source varchar(32) null,
  created_at datetime(6) not null,
  resolved_at datetime(6) null,
  constraint fk_decision_instances_session foreign key(session_id) references game_sessions(session_id),
  constraint fk_decision_instances_account foreign key(account_id) references accounts(account_id),
  unique key uq_decision_instances_session_decision(session_id, decision_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists action_logs (
  log_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  operation_id varchar(64) not null,
  story_day int not null,
  action_json json not null,
  effects_json json not null,
  created_at datetime(6) not null,
  constraint fk_action_logs_session foreign key(session_id) references game_sessions(session_id),
  constraint fk_action_logs_operation foreign key(operation_id) references game_actions(operation_id),
  index idx_action_logs_session_day(session_id, story_day, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists dialogue_logs (
  dialogue_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  operation_id varchar(64) not null,
  npc_id varchar(128) not null,
  player_text_ciphertext longtext null,
  visible_reply_text longtext not null,
  portrait_state varchar(32) not null,
  consent_record_id varchar(64) null,
  created_at datetime(6) not null,
  constraint fk_dialogue_logs_session foreign key(session_id) references game_sessions(session_id),
  constraint fk_dialogue_logs_operation foreign key(operation_id) references game_actions(operation_id),
  index idx_dialogue_logs_session_npc(session_id, npc_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists event_logs (
  event_log_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  event_id varchar(128) not null,
  event_instance_id varchar(64) null,
  story_day int not null,
  event_json json not null,
  created_at datetime(6) not null,
  constraint fk_event_logs_session foreign key(session_id) references game_sessions(session_id),
  index idx_event_logs_session_day(session_id, story_day, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists night_logs (
  night_log_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  story_day int not null,
  hidden_result_json json not null,
  morning_summary_text varchar(1000) null,
  created_at datetime(6) not null,
  constraint fk_night_logs_session foreign key(session_id) references game_sessions(session_id),
  unique key uq_night_logs_session_day(session_id, story_day)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists llm_call_audits (
  model_audit_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  operation_id varchar(64) null,
  call_kind varchar(32) not null,
  model_provider varchar(64) not null,
  model_id varchar(128) not null,
  prompt_version varchar(64) not null,
  request_hash char(71) not null,
  temperature decimal(6,4) not null,
  input_tokens int unsigned null,
  output_tokens int unsigned null,
  latency_ms int unsigned null,
  retry_count int unsigned not null default 0,
  raw_output_ciphertext longtext null,
  validated_result_json json null,
  validation_status varchar(32) not null,
  created_at datetime(6) not null,
  constraint fk_llm_call_audits_session foreign key(session_id) references game_sessions(session_id),
  index idx_llm_call_audits_session_created(session_id, created_at)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;

create table if not exists npc_memories (
  memory_id varchar(64) primary key,
  session_id varchar(64) not null,
  account_id varchar(64) not null,
  npc_id varchar(128) not null,
  source_operation_id varchar(64) null,
  memory_type varchar(32) not null,
  content_json json not null,
  visibility varchar(32) not null,
  valid_from_day int not null,
  expires_after_day int null,
  invalidated_at datetime(6) null,
  created_at datetime(6) not null,
  constraint fk_npc_memories_session foreign key(session_id) references game_sessions(session_id),
  index idx_npc_memories_lookup(session_id, npc_id, valid_from_day)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;
