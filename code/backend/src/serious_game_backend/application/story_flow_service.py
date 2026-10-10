from __future__ import annotations

from dataclasses import replace

from serious_game_backend.domain.errors import ActionUnavailableError, ContentValidationError
from serious_game_backend.domain.events import PendingDecision, VisibleDecisionOption
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.domain.story import DecisionOptionDefinition, StoryDayDefinition
from serious_game_backend.application.player_text_policy import player_visible_sentence
from serious_game_backend.application.ending_service import EndingService
from serious_game_backend.application.story_prose import DAY62_OPENING, project_saved_prose, restore_prose
from serious_game_backend.application.story_prose_round_two import restore_round_two, secretary_fallback
from serious_game_backend.application.evidence_guidance import custody_reason, option_next_steps


PERMIT_ALREADY_ISSUED_TEXT = (
    "你与周大山核对了此前签发的祠堂用地批文，编号、红章和有效手续均有留档。"
    "这项手续已经办成，无需重复申请或支付办理成本。接下来核查落实情况，"
    "各户合同仍以本人确认和正式签署为准。"
)
REPEATED_MONEY_OPTION_TEXTS = {
    1: "见他没有还价，你把补偿数又往上提了一次。",
    2: "你把补偿数提到第三次，要求他当场给个答复。",
}
REPEATED_MONEY_CONSEQUENCES = {
    1: "你再次提高补偿数，周奎元仍没有还价。他摇了摇头，提醒你上一次已经说过：钱的账与祖坟的事不能并作一笔。香案前安静下来，你们仍未谈妥迁坟和祭祀的安排。",
    2: "补偿数提到了第三次，周奎元把话停在这里。他没有接受，也没有还价，祖坟和祭祀的顾虑仍未得到回答。这一轮谈钱到此结束，钱不能替代那几件事。",
}

# The original arrival-night paragraph crosses midnight. Keep the immutable
# package and saved-game hash intact, but present its dawn passage on day two.
ARRIVAL_DAWN_START = "天蒙蒙亮时你起身"


def should_skip_permit_reissue(decision_id: str, flags: set[str]) -> bool:
    return (decision_id == "dp5_09" and "祠堂地块批文已签发" in flags
            and "用地手续有瑕疵" not in flags)


class StoryFlowService:
    """把结构化 story beat 投影为可恢复的玩家叙事流和待决策实例。"""

    INTERNAL_MARKERS = (
        "开启旗标", "关闭旗标", "显示位", "本节点", "结局轴",
        "状态量", "代码照此算", "行动点重置", "轴 T", "flag_",
    )

    @staticmethod
    def current_pending_decision(session: GameSession, package: ScriptPackage) -> PendingDecision | None:
        """Re-evaluate the pending instance without replaying its narrative or effects."""
        pending = session.pending_decision
        if pending is None:
            return None
        decision = package.decisions.get(pending.decision_id)
        if decision is None:
            return pending
        ledger = {
            key: getattr(session.game_state, key)
            for key in ("budget_remaining", "signed_households", "reported_signed_households")
        }
        options = []
        for option in decision.options:
            available = option.is_available(
                session.flags, session.state_values, ledger,
                known_fact_ids=session.known_fact_ids,
            ) and not (
                decision.decision_id == "dp4_04" and option.option_id == "a"
                and pending.context.get("listened_once")
            )
            options.append(VisibleDecisionOption(
                option.option_id,
                StoryFlowService._visible_option_text(decision, option, session, pending.context),
                available=available,
                unavailable_reason=None if available else StoryFlowService._option_unavailable_reason(option, session.known_fact_ids, session=session),
                unlock_requirements=option.unlock_requirements,
                next_steps=() if available else option_next_steps(option, session, package),
            ))
        return replace(
            pending, options=tuple(options),
            option_ids=tuple(option.option_id for option in options if option.available),
        )

    def initialize(self, session: GameSession, package: ScriptPackage) -> None:
        self._enter_day(session, package, session.game_state.story_day)

    @staticmethod
    def unread_day_continuation(session: GameSession, package: ScriptPackage):
        """Eligible same-day story blocks still awaiting the reader's Next action."""
        beat = package.story_day(session.game_state.story_day)
        if beat is None:
            return ()
        return tuple(
            block for block in beat.night_blocks
            if block.presentation_phase != "morning"
            and block.text.strip()
            and block.is_visible(origin_id=session.origin_id, flags=session.flags)
            and f"block:{block.block_id}" not in session.rendered_content_ids
        )

    def append_night(self, session: GameSession, package: ScriptPackage) -> None:
        beat = package.story_day(session.game_state.story_day)
        if beat is None:
            return
        self._append_blocks(
            session,
            tuple(
                replace(block, text=block.text.partition(ARRIVAL_DAWN_START)[0])
                if block.block_id == "d01_night" and ARRIVAL_DAWN_START in block.text
                else block
                for block in self.unread_day_continuation(session, package)
            ),
            beat_id=beat.beat_id,
            presentation_phase="night",
        )

    def enter_current_day(self, session: GameSession, package: ScriptPackage) -> None:
        self._enter_day(session, package, session.game_state.story_day)

    def resolve_decision(
        self,
        session: GameSession,
        package: ScriptPackage,
        *,
        decision_id: str,
        option_id: str,
        complete: bool = True,
    ) -> DecisionOptionDefinition:
        pending = self.current_pending_decision(session, package)
        if pending is None or pending.decision_id != decision_id:
            raise ActionUnavailableError("当前待处理决策与提交不一致")
        decision = package.decisions.get(decision_id)
        if decision is None:
            raise ContentValidationError(f"剧本包缺少决策：{decision_id}")
        option = decision.option(option_id)
        if option is None or option_id not in pending.option_ids:
            raise ActionUnavailableError("当前决策不包含该选项")
        resolution_index = sum(
            1
            for item in session.logs
            if item.get("type") == "decision"
            and item.get("decision_id") == decision_id
        )
        session.append_narrative(
            story_day=session.game_state.story_day,
            kind="consequence",
            text=self.session_public_text(
                REPEATED_MONEY_CONSEQUENCES.get(int(pending.context.get("talk_money_count", 0)),
                    decision.visible_consequence(option, session.flags, session.known_fact_ids))
                if decision_id == "dp4_04" and option_id == "b"
                else decision.visible_consequence(option, session.flags, session.known_fact_ids), session
            ),
            beat_id=session.story_beat_id,
            decision_id=decision_id,
            presentation_phase="consequence",
            content_instance_id=(
                f"decision:{pending.event_instance_id}:resolution:"
                f"{resolution_index}:{option_id}"
            ),
        )
        self._append_blocks(
            session,
            decision.followup_blocks,
            beat_id=session.story_beat_id,
            decision_id=decision_id,
            presentation_phase="consequence",
        )
        if complete:
            session.pending_decision = None
        return option

    def present_next_decision(
        self, session: GameSession, package: ScriptPackage
    ) -> None:
        if session.pending_decision is not None:
            return
        while session.pending_decision_queue:
            decision_id = session.pending_decision_queue.pop(0)
            if decision_id in {
                item.get("decision_id")
                for item in session.logs
                if item.get("type") == "decision"
            }:
                continue
            decision = package.decisions.get(decision_id)
            if decision is None:
                raise ContentValidationError(f"剧本包缺少决策：{decision_id}")
            if self._skip_completed_permit(session, decision_id):
                continue
            if self._skip_returned_roster(session, decision_id):
                continue
            if not decision.is_available(session.flags):
                session.logs.append({
                    "type": "decision_skipped",
                    "story_day": session.game_state.story_day,
                    "decision_id": decision_id,
                    "visible_to_player": False,
                })
                continue
            self._present_decision_id(session, package, decision_id)
            return

    def append_blocks(self, session: GameSession, blocks) -> None:
        self._append_blocks(
            session,
            blocks,
            beat_id=session.story_beat_id,
        )

    @classmethod
    def _visible_option_text(
        cls, decision, option, session: GameSession, context: dict
    ) -> str:
        text = decision.visible_option_text(option, session.flags, session.known_fact_ids)
        if decision.decision_id == "dp5_03" and decision.action_point_cost == 0:
            # This mandatory story decision is free. Older package text still
            # contains obsolete per-option costs; normalize saved games too.
            text = text.removesuffix("（0 点）").removesuffix("（强制清场 6 点）")
        if decision.decision_id == "dp4_04" and option.option_id == "b":
            text = REPEATED_MONEY_OPTION_TEXTS.get(int(context.get("talk_money_count", 0)), text)
        return cls.session_public_text(text, session)

    @staticmethod
    def feed_since(session: GameSession, after: int) -> dict:
        ending = EndingService.project_result(session)
        ending_text = (
            f"余波：{ending['sub_ending_title']}\n\n{ending['main_text']}\n\n{ending['sub_text']}"
            if ending is not None and all(
                isinstance(ending.get(key), str)
                for key in ("sub_ending_title", "main_text", "sub_text")
            ) else None
        )
        items = []
        decision_days = {item.story_day for item in session.narrative_feed
                         if item.presentation_phase in {"decision", "decision_setup"}}
        restore_package = session.package_id == "pkg_gameplay_v3"
        has_day62_visit = any(item.block_id == "d62_restored_visit_1" for item in session.narrative_feed)
        seen_content_ids: set[str] = set()
        money_consequences = 0
        for item in session.narrative_feed:
            if item.content_instance_id is not None:
                if item.content_instance_id in seen_content_ids:
                    continue
                seen_content_ids.add(item.content_instance_id)
            if (item.decision_id == "dp4_04" and item.kind == "consequence"
                    and (item.content_instance_id or "").endswith(":b")):
                if money_consequences in REPEATED_MONEY_CONSEQUENCES:
                    item = replace(item, text=REPEATED_MONEY_CONSEQUENCES[money_consequences])
                money_consequences += 1
            if item.cursor > after:
                if (item.kind == "day_intro" and item.content_instance_id == f"day:{item.story_day}:intro"
                        and item.story_day in decision_days
                        and "今天没有必须处理的主线事项" in item.text):
                    item = replace(item, text="", read_gate="advance")
                items.append(restore_round_two(project_saved_prose(item, has_day62_visit=has_day62_visit), session)
                             if restore_package else item)
        return {
            "after": after,
            "cursor": session.next_feed_cursor - 1,
            "items": [
                {
                    "cursor": item.cursor,
                    "story_day": item.story_day,
                    "kind": item.kind,
                    "speaker": item.speaker,
                    "text": (
                        ending_text
                        if ending_text is not None and item.kind == "ending"
                        and item.content_instance_id == "ending:final"
                        else item.text
                    ),
                    "content_instance_id": item.content_instance_id,
                    "block_id": item.block_id,
                    "beat_id": item.beat_id,
                    "decision_id": item.decision_id,
                    "scene_id": item.scene_id,
                    "presentation_phase": item.presentation_phase,
                    "day_sequence": item.day_sequence,
                    "read_gate": item.read_gate,
                }
                for item in items
            ],
        }

    def _enter_day(
        self,
        session: GameSession,
        package: ScriptPackage,
        story_day: int,
    ) -> None:
        beat = package.story_day(story_day)
        if beat is None:
            session.story_beat_id = None
            return
        session.story_beat_id = beat.beat_id
        opening_blocks = (DAY62_OPENING if package.package_id == "pkg_gameplay_v3"
                          and story_day == 62 and not beat.opening_blocks else beat.opening_blocks)
        # Resolve conditional arrivals before describing the day to the player.
        scheduled = list(beat.decision_ids)
        if beat.opening_decision_id and beat.opening_decision_id not in scheduled:
            scheduled.insert(0, beat.opening_decision_id)
        for decision in package.decisions.values():
            if decision.is_due_early(story_day, session.flags):
                scheduled.insert(0, decision.decision_id)
        is_free_day = not opening_blocks and not (
            scheduled or session.pending_decision_queue or session.pending_decision
        )
        session.append_narrative(
            story_day=story_day,
            kind="day_intro",
            text=(
                f"第{story_day}日，今天没有必须处理的主线事项，可以自由安排行动。"
                if is_free_day else self.session_public_text(
                    f"第{story_day}日", session
                )
            ),
            content_instance_id=f"day:{story_day}:intro",
            beat_id=beat.beat_id,
            presentation_phase="day_intro",
            read_gate="free_action" if is_free_day else "advance",
        )
        previous_beat = package.story_day(story_day - 1)
        if story_day == 2 and previous_beat is not None:
            for block in previous_beat.night_blocks:
                if block.block_id == "d01_night" and ARRIVAL_DAWN_START in block.text:
                    _, marker, dawn = block.text.partition(ARRIVAL_DAWN_START)
                    self._append_blocks(session, (replace(
                        block, block_id="d02_arrival_dawn", kind="narration",
                        text=marker + dawn, presentation_phase="scene",
                    ),), beat_id=beat.beat_id)
        self._append_blocks(
            session,
            secretary_fallback(session),
            beat_id=beat.beat_id,
            presentation_phase="scene",
        )
        self._append_blocks(
            session,
            opening_blocks,
            beat_id=beat.beat_id,
            presentation_phase="scene",
        )
        for decision_id in scheduled:
            if decision_id not in session.pending_decision_queue:
                session.pending_decision_queue.append(decision_id)
        self.present_next_decision(session, package)

    @staticmethod
    def _append_blocks(
        session: GameSession,
        blocks,
        *,
        beat_id: str | None = None,
        decision_id: str | None = None,
        presentation_phase: str = "scene",
    ) -> None:
        for block in blocks:
            if not block.is_visible(origin_id=session.origin_id, flags=session.flags):
                continue
            if session.package_id == "pkg_gameplay_v3":
                block = restore_round_two(restore_prose(block), session)
            session.append_narrative(
                story_day=session.game_state.story_day,
                kind=block.kind,
                text=StoryFlowService.session_public_text(block.text, session),
                speaker=block.speaker,
                content_instance_id=f"block:{block.block_id}",
                block_id=block.block_id,
                beat_id=beat_id,
                decision_id=decision_id,
                scene_id=block.scene_id,
                presentation_phase=(
                    block.presentation_phase or presentation_phase
                ),
            )

    @staticmethod
    def _skip_completed_permit(session: GameSession, decision_id: str) -> bool:
        if not should_skip_permit_reissue(decision_id, session.flags):
            return False
        if not any(item.get("type") == "permit_already_issued" for item in session.logs):
            session.logs.append({
                "type": "permit_already_issued", "decision_id": decision_id,
                "story_day": session.game_state.story_day, "visible_to_player": False,
            })
            session.append_narrative(
                story_day=session.game_state.story_day, kind="narration",
                text=PERMIT_ALREADY_ISSUED_TEXT, beat_id=session.story_beat_id,
                content_instance_id="permit:already-issued", presentation_phase="scene",
            )
        return True

    @staticmethod
    def _skip_returned_roster(session: GameSession, decision_id: str) -> bool:
        """The legacy report-choice E already executes the original-return scene.

        In the final script E belongs to the next custody question. Preserve
        legacy route IDs, but never offer retaining/destroying the returned bag.
        The zero-cost return has no metric/flag effects; only custody is recorded.
        """
        if decision_id != 'dp4_roster_disposition':
            return False
        if not any(item.get('type') == 'decision'
                   and item.get('decision_id') == 'dp4_01'
                   and item.get('option_id') == 'e' for item in session.logs):
            return False
        if not any(item.get('type') == 'roster_return_already_handled' for item in session.logs):
            session.state_values['lead_roster_disposition'] = '未获取'
            session.logs.append({
                'type': 'roster_return_already_handled',
                'story_day': session.game_state.story_day,
                'decision_id': decision_id,
                'visible_to_player': False,
            })
        return True

    @staticmethod
    def _present_decision_id(
        session: GameSession,
        package: ScriptPackage,
        decision_id: str,
    ) -> None:
        if StoryFlowService._skip_completed_permit(session, decision_id):
            return
        if StoryFlowService._skip_returned_roster(session, decision_id):
            return
        decision = package.decisions.get(decision_id)
        if decision is None:
            raise ContentValidationError(f"剧本包缺少决策：{decision_id}")
        if (
            decision_id == "dp2_03"
            and session.game_state.story_day == 19
            and not any(item.get("type") == "dp2_03_early_anxiety" for item in session.logs)
        ):
            npc = session.npc_states.get("npc_liu_san")
            if npc is not None and npc.anxiety_score is not None:
                session.npc_states["npc_liu_san"] = replace(
                    npc, anxiety_score=min(100, npc.anxiety_score + 10)
                )
            session.logs.append({
                "type": "dp2_03_early_anxiety",
                "story_day": 19,
                "visible_to_player": False,
            })
        ledger_values = {
            "budget_remaining": session.game_state.budget_remaining,
            "signed_households": session.game_state.signed_households,
            "reported_signed_households": session.game_state.reported_signed_households,
        }
        context = (
            session.pending_decision.context
            if session.pending_decision is not None
            and session.pending_decision.decision_id == decision_id
            else {}
        )
        availability = {
            item.option_id: item.is_available(
                session.flags,
                session.state_values,
                ledger_values,
                known_fact_ids=session.known_fact_ids,
            ) and not (
                decision_id == "dp4_04"
                and item.option_id == "a"
                and context.get("listened_once")
            )
            for item in decision.options
        }
        available_ids = tuple(
            item.option_id for item in decision.options if availability[item.option_id]
        )
        if not available_ids:
            raise ContentValidationError(f"当前决策没有可达选项：{decision_id}")
        self_context = dict(context)
        presentation_index = sum(
            1 for item in session.logs
            if item.get("type") == "decision_presented"
            and item.get("decision_id") == decision_id
        )
        event_instance_id = (
            f"evt_{session.session_id}_{decision.decision_id}_p{presentation_index}"
        )
        StoryFlowService._append_blocks(
            session,
            decision.presentation_blocks,
            beat_id=session.story_beat_id,
            decision_id=decision_id,
            presentation_phase="decision_setup",
        )
        presentation_entry_id = f"decision:{event_instance_id}"
        session.append_narrative(
            story_day=session.game_state.story_day,
            kind="decision",
            text=StoryFlowService.session_public_text(
                decision.visible_prompt(session.flags, session.known_fact_ids), session
            ),
            content_instance_id=presentation_entry_id,
            beat_id=session.story_beat_id,
            decision_id=decision_id,
            scene_id=decision.visible_scene_id(session.flags, session.known_fact_ids),
            presentation_phase="decision",
            read_gate="decision",
        )
        session.pending_decision = PendingDecision(
            event_instance_id=event_instance_id,
            decision_id=decision.decision_id,
            option_ids=available_ids,
            presented_state_version=session.state_version,
            visible_title=StoryFlowService.session_public_text(
                decision.visible_title(session.flags, session.known_fact_ids), session
            ),
            visible_text=StoryFlowService.session_public_text(
                decision.visible_prompt(session.flags, session.known_fact_ids), session
            ),
            scene_id=decision.visible_scene_id(session.flags, session.known_fact_ids),
            options=tuple(
                VisibleDecisionOption(
                    item.option_id,
                    StoryFlowService._visible_option_text(
                        decision, item, session, self_context
                    ),
                    available=availability[item.option_id],
                    unavailable_reason=(
                        None
                        if availability[item.option_id]
                        else StoryFlowService._option_unavailable_reason(
                            item, session.known_fact_ids, session=session
                        )
                    ),
                    unlock_requirements=item.unlock_requirements,
                    next_steps=() if availability[item.option_id] else option_next_steps(item, session, package),
                )
                for item in decision.options
            ),
            input_kind=decision.input_kind,
            input_schema=decision.input_schema or None,
            context=self_context,
            presentation_entry_id=presentation_entry_id,
        )
        session.logs.append({
            "type": "decision_presented",
            "story_day": session.game_state.story_day,
            "decision_id": decision.decision_id,
            "visible_to_player": True,
        })

    @staticmethod
    def _option_unavailable_reason(option, known_fact_ids: set[str], *, session=None) -> str:
        if session is not None:
            specific = custody_reason(option, session)
            if specific:
                return specific
        fact_locked = (
            not option.required_fact_ids.issubset(known_fact_ids)
            or (
                bool(option.required_any_fact_ids)
                and not bool(option.required_any_fact_ids & known_fact_ids)
            )
        )
        if fact_locked and option.unlock_requirements:
            names = "、".join(
                f"《{item['archive_name']}》"
                for item in option.unlock_requirements
            )
            return f"需先查阅{names}或通过正式接触取得相关事实"
        return option.unavailable_reason

    @classmethod
    def _without_internal_markers(cls, text: str) -> str:
        if not any(marker in text for marker in cls.INTERNAL_MARKERS):
            return text
        parts = []
        quote_pairs = {"“": "”", "‘": "’", "「": "」", "『": "』"}
        closing = []
        start = 0
        # Preserve complete quoted utterances and their original punctuation.
        # Splitting at every 。 used to detach closing quotes from the dialogue.
        for index, char in enumerate(text):
            if char in quote_pairs:
                closing.append(quote_pairs[char])
            elif closing and char == closing[-1]:
                closing.pop()
            boundary = not closing and (
                char in "。！？\n"
                or (char in "”’」』" and text[start:index + 1].rstrip("”’」』").endswith(("。", "！", "？", "…")))
            )
            if boundary or index == len(text) - 1:
                sentence = text[start:index + 1]
                if sentence.strip() and not any(marker in sentence for marker in cls.INTERNAL_MARKERS):
                    parts.append(sentence)
                elif not sentence.strip() and parts:
                    # Retain a paragraph separator without accumulating empty
                    # lines left behind by discarded internal sentences.
                    if not parts[-1].endswith("\n"):
                        parts.append(sentence)
                start = index + 1
        return "".join(parts).strip() or "相关处置已经记录，后续影响将在剧情中体现。"

    @classmethod
    def public_text(cls, text: str) -> str:
        """Validate and normalize text under the gameplay-v3 player policy."""
        return player_visible_sentence(cls._without_internal_markers(text))

    @classmethod
    def session_public_text(cls, text: str, session: GameSession) -> str:
        clean = cls._without_internal_markers(text)
        if session.package_id == "pkg_gameplay_v3":
            return player_visible_sentence(clean)
        return clean
