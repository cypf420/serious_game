from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def identity_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


PLAYER = "player"
RESEARCHER = "researcher"
CONTENT_EDITOR = "content_editor"
OPERATOR = "operator"
ADMIN = "admin"

PERMISSION_PLAY = "game:play"
PERMISSION_RESEARCH_READ = "research:read"
PERMISSION_RESEARCH_EXPORT = "research:export"
PERMISSION_RESEARCH_APPROVE = "research:approve"
PERMISSION_CONTENT_EDIT = "content:edit"
PERMISSION_OPERATE = "system:operate"
PERMISSION_ADMIN = "system:admin"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    PLAYER: frozenset({PERMISSION_PLAY}),
    RESEARCHER: frozenset({PERMISSION_RESEARCH_READ, PERMISSION_RESEARCH_EXPORT}),
    CONTENT_EDITOR: frozenset({PERMISSION_CONTENT_EDIT}),
    OPERATOR: frozenset({PERMISSION_OPERATE}),
    ADMIN: frozenset({
        PERMISSION_PLAY,
        PERMISSION_RESEARCH_READ,
        PERMISSION_RESEARCH_EXPORT,
        PERMISSION_RESEARCH_APPROVE,
        PERMISSION_CONTENT_EDIT,
        PERMISSION_OPERATE,
        PERMISSION_ADMIN,
    }),
}


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    username: str
    password_hash: str
    roles: frozenset[str] = field(default_factory=lambda: frozenset({PLAYER}))
    disabled: bool = False
    created_at: str = field(default_factory=identity_now_iso)
    updated_at: str = field(default_factory=identity_now_iso)

    @property
    def permissions(self) -> frozenset[str]:
        values: set[str] = set()
        for role in self.roles:
            values.update(ROLE_PERMISSIONS.get(role, ()))
        return frozenset(values)


@dataclass(frozen=True, slots=True)
class AuthSession:
    token_hash: str
    account_id: str
    csrf_token_hash: str
    created_at: str
    last_seen_at: str
    expires_at: str
    revoked_at: str | None = None

    def is_active(self, now: str) -> bool:
        return self.revoked_at is None and self.expires_at > now


@dataclass(frozen=True, slots=True)
class Principal:
    account_id: str
    roles: frozenset[str]
    permissions: frozenset[str]
    auth_session_hash: str

    def can(self, permission: str) -> bool:
        return permission in self.permissions
