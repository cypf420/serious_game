"""Provision a production account without exposing an account-creation HTTP endpoint."""

from __future__ import annotations

import argparse
from getpass import getpass
import secrets

from serious_game_backend.bootstrap import build_container
from serious_game_backend.config import Settings
from serious_game_backend.domain.identity import ROLE_PERMISSIONS


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a serious-game account")
    parser.add_argument("username")
    parser.add_argument(
        "--role", action="append", required=True, choices=sorted(ROLE_PERMISSIONS)
    )
    parser.add_argument("--account-id", default=None)
    args = parser.parse_args()
    password = getpass("Password (at least 8 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("passwords do not match")
    settings = Settings.from_env()
    if settings.environment != "production" or settings.repository != "mysql":
        raise SystemExit("account provisioning requires production MySQL configuration")
    runtime = build_container(settings)
    account = runtime.auth.create_account(
        account_id=args.account_id or f"acct_{secrets.token_hex(16)}",
        username=args.username, password=password, roles=frozenset(args.role),
    )
    print(f"created account {account.account_id} roles={','.join(sorted(account.roles))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
