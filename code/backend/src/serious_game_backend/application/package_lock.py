from __future__ import annotations

from serious_game_backend.application.ports import ScriptPackageRepository
from serious_game_backend.domain.errors import SessionContentUnavailableError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage


CONTENT_UNAVAILABLE_REASON = "该进度锁定的剧本内容已不在当前版本中，暂时无法打开。"


# Exact content-only correction of Tan's demand wording; no story effects changed.
_TAN_DEMAND_COPY_COMPATIBILITY = (
    "pkg_gameplay_v3", "3.5.18-feedback15-approved-copy",
    "sha256:c4795211286ca05dafd97e91b0f4ff513f2b78e536dfc5d9f0a0454063d6932a",
    "sha256:17614221c51fcca8a8b5b4716533367cae6f6812d41ea57d845095896edb3a43",
)


# Only the two approved accessible housing capacities changed from the copy update.
_HOUSING_CAPACITY_COMPATIBILITY = {
    ("pkg_gameplay_v3", "3.5.18-feedback15-approved-copy", prior,
     "sha256:0b1e4d97998dcadf5687b8116d41896c63c68e0df82d969e844ab72e69e290a0")
    for prior in (
        "sha256:c4795211286ca05dafd97e91b0f4ff513f2b78e536dfc5d9f0a0454063d6932a",
        "sha256:17614221c51fcca8a8b5b4716533367cae6f6812d41ea57d845095896edb3a43",
    )
}


def locked_package_access(
    packages: ScriptPackageRepository,
    session: GameSession,
) -> tuple[ScriptPackage | None, dict]:
    package = packages.get(session.package_id)
    content_available = bool(
        package
        and package.package_version == session.package_version
        and (package.content_hash == session.package_content_hash
             or (session.package_id, session.package_version,
                 session.package_content_hash, package.content_hash)
             == _TAN_DEMAND_COPY_COMPATIBILITY
             or (session.package_id, session.package_version,
                 session.package_content_hash, package.content_hash)
             in _HOUSING_CAPACITY_COMPATIBILITY)
    )
    if not content_available:
        return package, {
            "mode": "content_unavailable",
            "content_available": False,
            "review_available": False,
            "loadable": False,
            "unavailable_reason": CONTENT_UNAVAILABLE_REASON,
        }
    review_only = package is not None and package.status == "retired"
    return package, {
        "mode": "review_only" if review_only else "playable",
        "content_available": True,
        "review_available": True,
        "loadable": True,
        "unavailable_reason": None,
    }


def require_locked_package(
    packages: ScriptPackageRepository,
    session: GameSession,
) -> ScriptPackage:
    package, access = locked_package_access(packages, session)
    if not access["content_available"]:
        raise SessionContentUnavailableError(
            access["unavailable_reason"],
            details=access,
        )
    assert package is not None
    return package
