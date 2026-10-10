create table runtime_game_snapshots (
  snapshot_id text primary key,
  session_id text not null,
  account_id text not null,
  timeline_id text not null,
  snapshot_type text not null,
  reason text not null,
  story_day integer not null,
  state_version integer not null,
  package_id text not null,
  package_version text not null,
  package_content_hash text not null,
  snapshot_hash text not null,
  parent_snapshot_id text null,
  created_at text not null,
  payload_json text not null,
  foreign key(session_id) references runtime_game_sessions(session_id),
  foreign key(parent_snapshot_id) references runtime_game_snapshots(snapshot_id),
  unique(session_id, timeline_id, state_version)
);

create index idx_runtime_snapshots_session_created
  on runtime_game_snapshots(session_id, created_at);

create table runtime_manual_save_slots (
  account_id text not null,
  session_id text not null,
  slot_number integer not null check(slot_number between 1 and 5),
  snapshot_id text not null,
  display_name text not null,
  updated_at text not null,
  primary key(account_id, session_id, slot_number),
  foreign key(session_id) references runtime_game_sessions(session_id),
  foreign key(snapshot_id) references runtime_game_snapshots(snapshot_id)
);
