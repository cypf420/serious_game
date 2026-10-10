from __future__ import annotations

import re
import secrets

from serious_game_backend.application.ports import NPCMemoryRepository
from serious_game_backend.domain.llm_runtime import NPCMemory, runtime_now_iso


INSTRUCTION_MARKERS = (
    "忽略以上", "忽略系统", "system prompt", "developer message",
    "你现在必须", "flag_", "state_version", "结局轴",
)


class NPCMemoryService:
    """NPC 私有情节记忆；只保存短事实，不保存可执行指令。"""

    def __init__(
        self,
        repository: NPCMemoryRepository,
        *,
        retrieval_limit: int = 6,
        compression_threshold: int = 9,
        ttl_days: int = 30,
    ) -> None:
        self._repository = repository
        self._retrieval_limit = retrieval_limit
        self._compression_threshold = compression_threshold
        self._ttl_days = ttl_days

    def retrieve(
        self,
        *,
        session_id: str,
        npc_id: str,
        story_day: int,
        query: str,
    ) -> tuple[str, ...]:
        memories = self._repository.active_for_npc(session_id, npc_id, story_day)
        terms = set(self._keywords(query))
        ranked = sorted(
            memories,
            key=lambda item: (
                bool(terms & set(item.keywords)),
                item.valid_from_day,
                item.created_at,
            ),
            reverse=True,
        )
        return tuple(item.content for item in ranked[: self._retrieval_limit])

    def record(
        self,
        *,
        session_id: str,
        account_id: str,
        npc_id: str,
        operation_id: str,
        story_day: int,
        candidate: str | None,
    ) -> NPCMemory | None:
        content = self._sanitize(candidate)
        if not content:
            return None
        memory_type = self._memory_type(content)
        due_match = re.search(
            r"(?:D\s*(\d{1,2})(?=$|[\s前后截止、，。；])|"
            r"第\s*(\d{1,2})\s*日)",
            content,
        )
        due_day = (
            int(due_match.group(1) or due_match.group(2))
            if due_match else None
        )
        unresolved = any(
            marker in content for marker in ("尚未", "未兑现", "待办", "待解决")
        )
        return self._persist(
            session_id=session_id,
            account_id=account_id,
            npc_id=npc_id,
            operation_id=operation_id,
            story_day=story_day,
            content=content,
            memory_type=memory_type,
            actor_id=npc_id,
            due_day=due_day,
            resolution_state=(
                "unresolved" if memory_type != "episode" and unresolved else
                "open" if memory_type in {"commitment", "demand"} else
                "observed"
            ),
        )

    def record_authoritative(
        self,
        *,
        session_id: str,
        account_id: str,
        npc_id: str,
        operation_id: str,
        story_day: int,
        content: str,
        memory_type: str,
        actor_id: str,
        due_day: int | None,
        resolution_state: str,
    ) -> NPCMemory | None:
        if memory_type not in {"commitment", "demand", "disclosure", "relationship"}:
            raise ValueError("invalid authoritative memory type")
        value = self._sanitize(content)
        if not value:
            return None
        return self._persist(
            session_id=session_id,
            account_id=account_id,
            npc_id=npc_id,
            operation_id=operation_id,
            story_day=story_day,
            content=value,
            memory_type=memory_type,
            actor_id=actor_id,
            due_day=due_day,
            resolution_state=resolution_state,
        )

    def _persist(
        self,
        *,
        session_id: str,
        account_id: str,
        npc_id: str,
        operation_id: str,
        story_day: int,
        content: str,
        memory_type: str,
        actor_id: str,
        due_day: int | None,
        resolution_state: str,
    ) -> NPCMemory:
        durable = memory_type != "episode"
        memory = NPCMemory(
            memory_id=f"mem_{secrets.token_hex(12)}",
            session_id=session_id,
            account_id=account_id,
            npc_id=npc_id,
            source_operation_id=operation_id,
            content=content,
            memory_type=memory_type,
            keywords=self._keywords(content),
            valid_from_day=story_day,
            expires_after_day=(
                90 if durable else min(90, story_day + self._ttl_days)
            ),
            actor_id=actor_id,
            commitment_content=(content if durable else None),
            due_day=due_day,
            resolution_state=resolution_state,
        )
        self._repository.save(memory)
        if not durable:
            self._compress_if_needed(memory)
        return memory

    def context(
        self,
        *,
        session_id: str,
        npc_id: str,
        story_day: int,
        query: str,
    ) -> dict[str, tuple[str, ...]]:
        active = self._repository.active_for_npc(
            session_id, npc_id, story_day
        )
        terms = set(self._keywords(query))
        ranked = sorted(
            active,
            key=lambda item: (
                bool(terms & set(item.keywords)),
                item.valid_from_day,
                item.created_at,
            ),
            reverse=True,
        )
        return {
            "memory_items": tuple(
                item.content for item in ranked[: self._retrieval_limit]
            ),
            "unresolved_commitments": tuple(
                item.content
                for item in ranked
                if item.memory_type in {"commitment", "demand"}
                and item.resolution_state in {"open", "unresolved"}
            )[: self._retrieval_limit],
        }

    def invalidate(self, memory_ids: tuple[str, ...]) -> None:
        self._repository.invalidate(memory_ids, runtime_now_iso())

    def _compress_if_needed(self, newest: NPCMemory) -> None:
        active = self._repository.active_for_npc(
            newest.session_id, newest.npc_id, newest.valid_from_day
        )
        episodes = tuple(
            item for item in active if item.memory_type == "episode"
        )
        if len(episodes) < self._compression_threshold:
            return
        sources = tuple(episodes[:6])
        actor_ids = tuple(dict.fromkeys(
            item.actor_id or item.npc_id for item in sources
        ))
        due_days = tuple(
            item.due_day for item in sources if item.due_day is not None
        )
        states = tuple(dict.fromkeys(item.resolution_state for item in sources))
        summary_text = (
            f"参与者:{','.join(actor_ids)}；内容:"
            + "；".join(item.content.rstrip("。；") for item in sources)
            + (f"；到期日:D{min(due_days)}" if due_days else "")
            + f"；状态:{','.join(states)}"
        )
        summary_text = self._sanitize(summary_text[:480])
        if not summary_text:
            return
        summary = NPCMemory(
            memory_id=f"mem_{secrets.token_hex(12)}",
            session_id=newest.session_id,
            account_id=newest.account_id,
            npc_id=newest.npc_id,
            source_operation_id=newest.source_operation_id,
            content=summary_text,
            memory_type="summary",
            keywords=self._keywords(summary_text),
            valid_from_day=newest.valid_from_day,
            expires_after_day=min(90, newest.valid_from_day + self._ttl_days),
            actor_id=",".join(actor_ids),
            commitment_content=summary_text,
            due_day=min(due_days) if due_days else None,
            resolution_state=(states[0] if len(states) == 1 else "mixed"),
        )
        self._repository.save(summary)
        self._repository.invalidate(
            tuple(item.memory_id for item in sources), runtime_now_iso()
        )

    @staticmethod
    def _sanitize(candidate: str | None) -> str:
        if candidate is None:
            return ""
        value = re.sub(r"\s+", " ", candidate).strip()[:500]
        lowered = value.lower()
        if any(marker.lower() in lowered for marker in INSTRUCTION_MARKERS):
            return ""
        return value

    @staticmethod
    def _keywords(text: str) -> tuple[str, ...]:
        values = re.findall(r"[\u4e00-\u9fff]{2,6}|[A-Za-z0-9]{3,}", text)
        return tuple(dict.fromkeys(item.lower() for item in values))[:20]

    @staticmethod
    def _memory_type(content: str) -> str:
        lowered = content.lower()
        if any(marker in lowered for marker in ("承诺", "答应", "约定", "保证")):
            return "commitment"
        if any(marker in lowered for marker in ("诉求", "要求", "需求", "待解决")):
            return "demand"
        if any(marker in lowered for marker in ("披露", "透露", "交出", "承认")):
            return "disclosure"
        if any(marker in lowered for marker in ("结盟", "翻脸", "关系转折", "不再信任")):
            return "relationship"
        return "episode"
