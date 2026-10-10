from __future__ import annotations

import hashlib
import hmac
import secrets

from serious_game_backend.application.ports import ExperimentAssignmentRepository
from serious_game_backend.domain.research import ExperimentAssignment, ResearchSubject


class ExperimentAssignmentService:
    def __init__(
        self,
        repository: ExperimentAssignmentRepository,
        *,
        enabled: bool,
        experiment_id: str,
        groups: tuple[str, ...],
        assignment_salt: str,
    ) -> None:
        self._repository = repository
        self._enabled = enabled
        self._experiment_id = experiment_id
        self._groups = groups
        self._salt = assignment_salt.encode("utf-8")

    def assign(
        self,
        subject: ResearchSubject,
        *,
        environment: str,
        package_content_hash: str,
        model_id: str,
        prompt_version: str,
    ) -> ExperimentAssignment | None:
        if not self._enabled:
            return None
        current = self._repository.get_for_subject(
            subject.research_subject_id, self._experiment_id
        )
        if current is not None:
            return current
        digest = hmac.new(
            self._salt,
            f"{subject.research_subject_id}:{self._experiment_id}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        group = self._groups[int.from_bytes(digest[:8], "big") % len(self._groups)]
        value = ExperimentAssignment(
            assignment_id=f"assign_{secrets.token_hex(16)}",
            research_subject_id=subject.research_subject_id,
            experiment_id=self._experiment_id,
            experiment_group_id=group,
            environment=environment,
            package_content_hash=package_content_hash,
            model_id=model_id,
            prompt_version=prompt_version,
        )
        try:
            self._repository.create(value)
        except ValueError:
            current = self._repository.get_for_subject(
                subject.research_subject_id, self._experiment_id
            )
            if current is None:
                raise
            return current
        return value
