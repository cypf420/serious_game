from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urlparse

import pymysql
from pymysql.cursors import DictCursor

from serious_game_backend.infrastructure.mysql_migrations import MySQLMigrationRunner


BACKEND_ROOT = Path(__file__).resolve().parents[3]


class MySQLResearchStore:
    """Physically separate pseudonymous research dataset; contains no account table."""

    def __init__(self, mysql_url: str, *, run_migrations: bool = True) -> None:
        parsed = urlparse(mysql_url.replace("mysql+pymysql://", "mysql://", 1))
        if parsed.scheme != "mysql" or not parsed.hostname or not parsed.path.strip("/"):
            raise ValueError("RESEARCH_MYSQL_URL must name a dedicated MySQL database")
        self._config = {
            "host": parsed.hostname, "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""), "password": unquote(parsed.password or ""),
            "database": parsed.path.strip("/"), "charset": "utf8mb4",
            "cursorclass": DictCursor, "autocommit": False,
            "connect_timeout": 10, "read_timeout": 30, "write_timeout": 30,
        }
        if run_migrations:
            MySQLMigrationRunner(
                self, BACKEND_ROOT / "migrations" / "research_mysql"
            ).migrate()

    @contextmanager
    def connect(self) -> Iterator[pymysql.Connection]:
        connection = pymysql.connect(**self._config)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
