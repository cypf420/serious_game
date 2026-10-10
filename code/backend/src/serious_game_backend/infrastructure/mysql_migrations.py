from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path

from serious_game_backend.infrastructure.migrations import MigrationError


class MySQLMigrationRunner:
    """MySQL 8 ordered migration runner with immutable checksums."""

    def __init__(self, store, migration_dir: Path) -> None:
        self._store = store
        self._migration_dir = migration_dir

    def migrate(self) -> None:
        files = sorted(self._migration_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        if not files:
            raise MigrationError(f"no MySQL migrations found in {self._migration_dir}")
        with self._store.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    create table if not exists schema_migrations (
                      version int unsigned primary key,
                      filename varchar(255) not null unique,
                      checksum char(71) not null,
                      applied_at datetime(6) not null
                    ) engine=InnoDB default charset=utf8mb4 collate=utf8mb4_unicode_ci
                    """
                )
                cursor.execute("select version, filename, checksum from schema_migrations")
                applied = {
                    int(row["version"]): (str(row["filename"]), str(row["checksum"]))
                    for row in cursor.fetchall()
                }
            connection.commit()
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
            statements = [item.strip() for item in sql.split(";") if item.strip()]
            try:
                with self._store.connect() as connection:
                    with connection.cursor() as cursor:
                        for statement in statements:
                            cursor.execute(statement)
                        cursor.execute(
                            """
                            insert into schema_migrations(version, filename, checksum, applied_at)
                            values (%s, %s, %s, %s)
                            """,
                            (
                                version, path.name, checksum,
                                datetime.now(timezone.utc).replace(tzinfo=None),
                            ),
                        )
                    connection.commit()
            except Exception as exc:
                raise MigrationError(f"MySQL migration failed: {path.name}") from exc
