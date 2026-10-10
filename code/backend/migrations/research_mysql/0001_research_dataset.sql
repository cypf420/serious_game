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
  index idx_research_dataset_subject(research_subject_id, created_at),
  index idx_research_dataset_group(experiment_id, experiment_group_id, event_type)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;
