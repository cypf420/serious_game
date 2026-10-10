from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3


class MigrationError(RuntimeError):
    pass


class SqliteMigrationRunner:
    def __init__(self, database_path: Path, migration_dir: Path) -> None:
        self._database_path = database_path
        self._migration_dir = migration_dir

    def migrate(self) -> None:
        files = sorted(self._migration_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        if not files:
            raise MigrationError(f"no SQLite migrations found in {self._migration_dir}")
        connection = sqlite3.connect(self._database_path, timeout=10, isolation_level=None)
        try:
            connection.execute("pragma foreign_keys = on")
            connection.execute("pragma busy_timeout = 10000")
            connection.execute("pragma journal_mode = wal")
            connection.execute(
                """
                create table if not exists runtime_migrations (
                  version integer primary key,
                  filename text not null unique,
                  checksum text not null,
                  applied_at text not null default current_timestamp
                )
                """
            )
            applied = {
                int(row[0]): (str(row[1]), str(row[2]))
                for row in connection.execute(
                    "select version, filename, checksum from runtime_migrations"
                ).fetchall()
            }
            for path in files:
                version = int(path.name.split("_", 1)[0])
                sql = path.read_text(encoding="utf-8")
                checksum = "sha256:" + hashlib.sha256(sql.encode("utf-8")).hexdigest()
                current = applied.get(version)
                if current is not None:
                    if current != (path.name, checksum):
                        raise MigrationError(
                            f"migration checksum mismatch for version {version}: {path.name}"
                        )
                    continue
                filename_sql = path.name.replace("'", "''")
                checksum_sql = checksum.replace("'", "''")
                script = (
                    "begin immediate;\n"
                    + sql
                    + "\ninsert into runtime_migrations(version, filename, checksum) "
                    + f"values ({version}, '{filename_sql}', '{checksum_sql}');\ncommit;"
                )
                try:
                    connection.executescript(script)
                except Exception as exc:
                    if connection.in_transaction:
                        connection.rollback()
                    raise MigrationError(f"SQLite migration failed: {path.name}") from exc
            self._validate(connection)
        finally:
            connection.close()

    @staticmethod
    def _validate(connection: sqlite3.Connection) -> None:
        required = {
            "runtime_game_sessions": {"session_id", "account_id", "state_version", "payload_json"},
            "runtime_operations": {"operation_id", "client_action_id", "payload_json"},
            "runtime_accounts": {"account_id", "username", "payload_json"},
            "runtime_auth_sessions": {"token_hash", "account_id", "payload_json"},
            "runtime_consent_records": {"consent_record_id", "account_id", "payload_json"},
            "runtime_research_subjects": {"research_subject_id", "account_id", "payload_json"},
            "runtime_game_snapshots": {
                "snapshot_id", "session_id", "timeline_id", "state_version",
                "snapshot_hash", "payload_json",
            },
            "runtime_manual_save_slots": {
                "account_id", "session_id", "slot_number", "snapshot_id",
            },
        }
        for table, columns in required.items():
            actual = {
                str(row[1]) for row in connection.execute(f"pragma table_info({table})").fetchall()
            }
            missing = columns - actual
            if missing:
                raise MigrationError(f"SQLite schema incomplete: {table} missing {sorted(missing)}")
