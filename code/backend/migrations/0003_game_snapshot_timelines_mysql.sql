alter table game_snapshots
  add column timeline_id varchar(64) null after account_id,
  add column snapshot_type varchar(32) not null default 'auto' after timeline_id,
  add column package_id varchar(128) null after state_version,
  add column package_version varchar(64) null after package_id,
  add column package_content_hash char(71) null after package_version,
  add column snapshot_hash char(71) null after snapshot_json,
  add column parent_snapshot_id varchar(64) null after snapshot_hash;

update game_snapshots s
join game_sessions g on g.session_id = s.session_id
set s.timeline_id = concat('timeline_', s.session_id),
    s.package_id = g.package_id,
    s.package_version = g.package_version,
    s.package_content_hash = g.package_content_hash,
    s.snapshot_hash = concat('sha256:', sha2(cast(s.snapshot_json as char), 256))
where s.timeline_id is null;

alter table game_snapshots
  modify timeline_id varchar(64) not null,
  modify package_id varchar(128) not null,
  modify package_version varchar(64) not null,
  modify package_content_hash char(71) not null,
  modify snapshot_hash char(71) not null,
  add constraint fk_game_snapshots_parent
    foreign key(parent_snapshot_id) references game_snapshots(snapshot_id),
  add unique key uq_game_snapshots_timeline_version(
    session_id, timeline_id, state_version
  );

create table manual_save_slots (
  account_id varchar(64) not null,
  session_id varchar(64) not null,
  slot_number int not null,
  snapshot_id varchar(64) not null,
  display_name varchar(128) not null,
  updated_at datetime(6) not null,
  primary key(account_id, session_id, slot_number),
  constraint chk_manual_save_slot check(slot_number between 1 and 5),
  constraint fk_manual_save_account foreign key(account_id) references accounts(account_id),
  constraint fk_manual_save_session foreign key(session_id) references game_sessions(session_id),
  constraint fk_manual_save_snapshot foreign key(snapshot_id) references game_snapshots(snapshot_id)
) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci;
