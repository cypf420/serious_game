from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from serious_game_backend.application.ports import AccountRepository, AuthSessionRepository
from serious_game_backend.domain.errors import (
    AccountConflictError,
    AuthenticationRequiredError,
    CSRFValidationError,
    InvalidCredentialsError,
    PermissionDeniedError,
)
from serious_game_backend.domain.identity import Account, AuthSession, Principal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class PasswordHasher:
    """标准库 scrypt；哈希字符串自带参数和随机盐。"""

    n = 2**14
    r = 8
    p = 1

    def hash(self, password: str) -> str:
        if len(password) < 8:
            raise ValueError("password must contain at least 8 characters")
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=self.n, r=self.r, p=self.p
        )
        return "$".join((
            "scrypt", str(self.n), str(self.r), str(self.p), salt.hex(), digest.hex()
        ))

    def verify(self, password: str, encoded: str) -> bool:
        try:
            scheme, n, r, p, salt_hex, digest_hex = encoded.split("$", 5)
            if scheme != "scrypt":
                return False
            candidate = hashlib.scrypt(
                password.encode("utf-8"),
                salt=bytes.fromhex(salt_hex),
                n=int(n),
                r=int(r),
                p=int(p),
            )
            return hmac.compare_digest(candidate.hex(), digest_hex)
        except (TypeError, ValueError):
            return False


class AuthService:
    def __init__(
        self,
        accounts: AccountRepository,
        sessions: AuthSessionRepository,
        *,
        session_ttl_seconds: int = 8 * 60 * 60,
        hasher: PasswordHasher | None = None,
    ) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._ttl = session_ttl_seconds
        self._hasher = hasher or PasswordHasher()

    def create_account(
        self, *, account_id: str, username: str, password: str, roles: frozenset[str]
    ) -> Account:
        normalized = username.strip().casefold()
        if self._accounts.get_by_username(normalized) is not None:
            raise AccountConflictError("用户名已被使用")
        account = Account(
            account_id=account_id,
            username=normalized,
            password_hash=self._hasher.hash(password),
            roles=roles,
        )
        try:
            self._accounts.create(account)
        except ValueError as exc:
            raise AccountConflictError("用户名或账号标识已被使用") from exc
        return account

    def login(self, username: str, password: str) -> tuple[str, str, Principal, str]:
        account = self._accounts.get_by_username(username.strip().casefold())
        if (
            account is None
            or account.disabled
            or not self._hasher.verify(password, account.password_hash)
        ):
            raise InvalidCredentialsError("用户名或密码错误")
        raw_token = secrets.token_urlsafe(48)
        raw_csrf = secrets.token_urlsafe(32)
        now = _now()
        expires = now + timedelta(seconds=self._ttl)
        session = AuthSession(
            token_hash=_sha256(raw_token),
            account_id=account.account_id,
            csrf_token_hash=_sha256(raw_csrf),
            created_at=_iso(now),
            last_seen_at=_iso(now),
            expires_at=_iso(expires),
        )
        self._sessions.create(session)
        return raw_token, raw_csrf, self._principal(account, session), session.expires_at

    def authenticate(self, raw_token: str | None) -> Principal:
        if not raw_token:
            raise AuthenticationRequiredError("缺少登录会话")
        token_hash = _sha256(raw_token)
        session = self._sessions.get(token_hash)
        now = _iso(_now())
        if session is None or not session.is_active(now):
            raise AuthenticationRequiredError("登录会话无效或已过期")
        account = self._accounts.get_by_id(session.account_id)
        if account is None or account.disabled:
            raise AuthenticationRequiredError("账号不可用")
        self._sessions.save(replace(session, last_seen_at=now))
        return self._principal(account, session)

    def verify_csrf(self, principal: Principal, raw_csrf: str | None) -> None:
        if not raw_csrf:
            raise CSRFValidationError("缺少 CSRF Token")
        session = self._sessions.get(principal.auth_session_hash)
        if session is None or not hmac.compare_digest(
            session.csrf_token_hash, _sha256(raw_csrf)
        ):
            raise CSRFValidationError("CSRF Token 无效")

    def logout(self, raw_token: str | None) -> None:
        if not raw_token:
            return
        session = self._sessions.get(_sha256(raw_token))
        if session is not None and session.revoked_at is None:
            self._sessions.save(replace(session, revoked_at=_iso(_now())))

    @staticmethod
    def require(principal: Principal, permission: str) -> None:
        if not principal.can(permission):
            raise PermissionDeniedError("当前账号没有执行该操作的权限")

    @staticmethod
    def _principal(account: Account, session: AuthSession) -> Principal:
        return Principal(
            account_id=account.account_id,
            roles=account.roles,
            permissions=account.permissions,
            auth_session_hash=session.token_hash,
        )
