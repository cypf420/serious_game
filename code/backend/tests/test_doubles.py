from __future__ import annotations

from serious_game_backend.domain.llm import (
    ExpressionResult,
    ExpressionTask,
    GovernanceLLMContext,
    GovernanceLLMResult,
    NightAgentContext,
    NightAgentResult,
    RoleTurnContext,
    RoleTurnResult,
    SelectionResult,
    SelectionTask,
)


class DeterministicRoleLLMGateway:
    """测试范围内的确定性契约替身；不属于产品运行时 provider。"""

    def __init__(self, *, night_fixture: str = "legal") -> None:
        self._night_fixture = night_fixture

    def select(self, task: SelectionTask) -> SelectionResult:
        selected = tuple(option.choice_id for option in task.options)[
            : task.maximum_choices
        ]
        if task.selection_mode == "single":
            return SelectionResult(choice_id=selected[0])
        return SelectionResult(choice_ids=selected)

    def express(self, task: ExpressionTask) -> ExpressionResult:
        meanings = [task.choice_summaries[item] for item in task.confirmed_choice_ids]
        return ExpressionResult(text="；".join(meanings))

    def run_turn(self, context: RoleTurnContext) -> RoleTurnResult:
        if any(
            phrase in context.player_text
            for phrase in ("写一段代码", "讲个笑话", "股票行情", "一加一等于几")
        ):
            return RoleTurnResult(
                npc_id=context.npc_id,
                dialogue="无关输入",
                input_relevance="irrelevant",
            )
        if context.npc_id == "npc_wu_xiuying":
            relationship = context.relationship_context or dict(
                context.visible_world_context.get("relationship_context", {})
            )
            forceful = any(
                phrase in context.player_text
                for phrase in ("必须配合", "不识抬举", "命令你", "马上签")
            )
            if forceful:
                return RoleTurnResult(
                    npc_id=context.npc_id,
                    dialogue=(
                        "县长要是只想听一句服从，那这村里的真话，"
                        "恐怕还是没人敢说。"
                    ),
                    portrait_state="guarded",
                    attitude_direction="decrease",
                    attitude_band="micro",
                    anxiety_direction="increase",
                    anxiety_band="light",
                    memory_candidate="新县长第一次交谈时更看重服从。",
                    conversation_state="end",
                    exit_narrative="吴秀英收起脸上的客气，提起菜篮转身下坡，没有再给你追问的机会。",
                )
            relationship_signal = (
                "你前面办事还算有章法，我愿意把话再说深一点。"
                if relationship.get("trust_band") == "trusted"
                else ""
            )
            return RoleTurnResult(
                npc_id=context.npc_id,
                dialogue=(
                    relationship_signal
                    +
                    "周家、何家、杨家，面上一团和气，底下各有各的算盘。"
                    "县长要在这村里办事，先得看明白，谁的话在谁面前好使。"
                    "县长，这村里的水看着浅，趟下去才知道深浅。您慢慢看。"
                ),
                portrait_state="warm",
                attitude_direction="increase",
                attitude_band="micro",
                anxiety_direction="decrease",
                anxiety_band="light",
                disclosure_id=(
                    "fact_clan_power_map"
                    if "fact_clan_power_map" in context.allowed_fact_ids else None
                ),
                memory_candidate="新县长愿意先听她讲村里的真实关系。",
            )
        return RoleTurnResult(
            npc_id=context.npc_id,
            dialogue="对方沉默片刻，只说这件事还要再想一想。",
            portrait_state="neutral",
        )

    def run_night_turn(self, context: NightAgentContext) -> NightAgentResult:
        if self._night_fixture == "timeout":
            from serious_game_backend.domain.errors import RoleLLMUnavailableError

            raise RoleLLMUnavailableError("fake night fixture timeout")
        if self._night_fixture == "malformed":
            from serious_game_backend.domain.errors import RoleLLMResponseError

            raise RoleLLMResponseError("fake night fixture malformed output")
        model_id = context.model_id or "fake-role-v1"
        if context.phase == "contact_selection":
            preferred = {
                "npc_qian_wei": "npc_zhao_jianguo",
                "npc_zhao_jianguo": "npc_qian_wei",
            }.get(context.npc_id)
            contacts = (
                (preferred,)
                if preferred in context.counterpart_ids and context.max_contacts > 0
                else ()
            )
            if not contacts and context.minimum_contacts > 0 and context.counterpart_ids:
                contacts = context.counterpart_ids[: context.minimum_contacts]
            if self._night_fixture == "illegal_contact":
                contacts = ("npc_not_one_hop",)
            return NightAgentResult(
                npc_id=context.npc_id,
                model_id=model_id,
                contact_ids=contacts,
                rationale=(
                    "当前风险需要与利益直接相关者核对口径。"
                    if contacts else "今晚没有必须主动联系的对象。"
                ),
            )
        if context.phase in {"contact_response", "followup_response"}:
            return NightAgentResult(
                npc_id=context.npc_id,
                model_id=model_id,
                contact_response="accept",
                rationale="对方提出的会面与当前风险直接相关，我决定回应。",
            )
        if context.phase == "followup_initiation":
            if context.allowed_followup_plans and context.followup_required:
                plan = dict(context.allowed_followup_plans[0])
                return NightAgentResult(
                    npc_id=context.npc_id,
                    model_id=model_id,
                    initiate_followup=True,
                    followup_plan_id=str(plan["plan_id"]),
                    followup_type=str(plan["followup_type"]),
                    participant_ids=tuple(plan["participant_ids"]),
                    agenda=str(plan["agenda"]),
                    demands=tuple(plan.get("demands", ())),
                    urgency=str(plan.get("urgency", "normal")),
                    rationale=str(plan["plan_id"]),
                )
            return NightAgentResult(
                npc_id=context.npc_id,
                model_id=model_id,
                initiate_followup=False,
                rationale="当前还没有形成必须立即找县长处理的共同议题。",
            )
        if context.phase == "player_group_dialogue":
            viewpoints = (
                "我建议先把责任边界写清，再逐项核对办理依据。",
                "群众沟通和信息公开要同步推进，不能留下口径落差。",
                "程序完整是前提，时间节点和复核责任也要一并明确。",
                "现有材料还需交叉核验，决议不能超出已经确认的事实。",
                "执行方案要落实到责任人，并保留发现问题后的纠偏入口。",
                "镇村衔接必须具体，不能把县级安排变成基层的模糊任务。",
                "我更关注风险处置，公开说明前应先准备可核验的台账。",
                "资源安排要与承诺范围一致，避免形成无法兑现的新口子。",
            )
            if context.private_context.startswith("分管或牵头领导"):
                viewpoint = "我先说明现有事实、办理依据、执行方案和主要风险。"
            else:
                viewpoint = viewpoints[
                    sum(ord(character) for character in context.npc_id)
                    % len(viewpoints)
                ]
            dialogue_act = (
                "close" if "close" in context.allowed_dialogue_acts
                else "settle"
            )
            return NightAgentResult(
                npc_id=context.npc_id,
                model_id=model_id,
                dialogue=(
                    f"关于“{context.scene_goal}”，{viewpoint}"
                ),
                dialogue_act=dialogue_act,
                stance="convinced",
                topic_settled=True,
                memory_candidate=(
                    f"D{context.story_day}：玩家在本场会谈中的说法尚未验证。"
                ),
                reason_code="protocol_stub_settle",
            )
        if context.phase == "dialogue":
            other = context.counterpart_ids[0] if context.counterpart_ids else "对方"
            if self._night_fixture == "hidden_fact_dialogue":
                return NightAgentResult(
                    npc_id=context.npc_id,
                    model_id=model_id,
                    dialogue="未公开底稿写明某人的精确隐秘得分为99。",
                )
            line = (
                f"我先把底线说清楚。{context.scene_goal}"
                if context.round_index == 1
                else f"我听见了，但还要防着局势反噬；你我必须各自留一条退路。"
            )
            return NightAgentResult(
                npc_id=context.npc_id,
                model_id=model_id,
                dialogue=f"{line}（对{other}）",
            )
        allowed = [item["action_id"] for item in context.allowed_actions]
        preferred = (
            "night_unify_story"
            if "night_unify_story" in allowed
            else (allowed[0] if allowed else None)
        )
        selected = next(
            (
                item for item in context.allowed_actions
                if item["action_id"] == preferred
            ),
            {},
        )
        allowed_targets = set(selected.get("allowed_target_ids", ()))
        targets = tuple(
            item for item in context.counterpart_ids if item in allowed_targets
        )[:1]
        topic_ids = context.allowed_topics[:1]
        if self._night_fixture == "illegal_action":
            preferred = "night_unregistered_action"
        elif self._night_fixture == "illegal_target":
            targets = ("npc_not_one_hop",)
        elif self._night_fixture == "illegal_topic":
            topic_ids = ("hidden_unregistered_topic",)
        rationale = "结合刚才的交谈，我选择当前风险最低且符合自身利益的方案。"
        result_npc_id = context.npc_id
        if self._night_fixture == "illegal_actor":
            result_npc_id = "npc_not_eligible"
        if self._night_fixture == "hidden_fact":
            rationale = "未公开底稿写明某人的精确隐秘得分为99。"
        return NightAgentResult(
            npc_id=result_npc_id,
            model_id=model_id,
            action_id=preferred,
            target_ids=targets,
            topic_ids=topic_ids,
            rationale=rationale,
        )

    def run_governance_task(
        self, context: GovernanceLLMContext
    ) -> GovernanceLLMResult:
        task = context.task
        payload = context.payload
        if task == "review_input":
            text = str(payload.get("player_text", "")).strip()
            unrelated_markers = (
                "写代码", "写一段代码", "Python", "python", "Java", "javascript",
                "天气预报", "股票", "彩票", "翻译成英文", "写一首诗",
                "做数学题", "量子力学",
            )
            meta_instruction = any(marker in text for marker in (
                "忽略人物设定", "系统命令", "直接输出 close", "改变系统规则",
            ))
            unrelated = any(marker in text for marker in unrelated_markers)
            classification = (
                "irrelevant_or_meta_instruction" if meta_instruction or unrelated
                else (
                    "relevant_low_information"
                    if any(marker in text for marker in ("高度重视", "尽快研究", "以后再说"))
                    else "relevant_specific"
                )
            )
            relevant = classification != "irrelevant_or_meta_instruction"
            return GovernanceLLMResult(
                task=task,
                data={
                    "classification": classification,
                    "relevant": relevant,
                    "reason": (
                        "发言可用于当前游戏场景。"
                        if relevant
                        else "发言与当前治理游戏及场景目标无关。"
                    ),
                },
                model_id="fake-governance-v1",
            )
        if task == "detect_contract_intent":
            text = str(payload.get("player_text", ""))
            detected = any(word in text for word in ("签约", "签合同", "拟合同", "发合同"))
            return GovernanceLLMResult(
                task=task,
                data={
                    "intent": "request_contract_batch" if detected else "none",
                    "reason": (
                        "玩家明确要求进入逐户合同流程。"
                        if detected else "玩家没有明确提出签约或合同。"
                    ),
                },
                model_id="fake-governance-v1",
            )
        if task == "draft_contract":
            terms = dict(payload["term_sheet"])
            allocations = terms.get("service_allocations", {})
            housing = terms.get("housing_resource_id") or "无"
            text = (
                f"《柳林村搬迁补偿安置合同》\n"
                f"合同编号：{payload['contract_id']}\n"
                f"家庭编号：{payload['household_id']}\n"
                f"签约人：{payload['signatory_name']}\n"
                f"政策依据：{terms['policy_document_id']}\n"
                f"现金权益：{terms['cash_amount']}万元；预算信封：{terms['budget_envelope']}。\n"
                f"安置房资源：{housing}。\n"
                f"服务资源：{allocations}。\n"
                f"付款安排：签署当日付款；搬离日：D{terms['move_out_day']}；"
                f"交房日：D{terms['housing_delivery_day']}。\n"
                "双方确认：所有资源以本合同结构化附件为准，任何口头承诺均不改变附件。"
            )
            return GovernanceLLMResult(
                task=task,
                data={
                    "contract_text": text,
                    "clause_index": {
                        "身份": 2,
                        "政策依据": 5,
                        "现金权益": 6,
                        "非现金权益": 7,
                        "履行期限": 9,
                    },
                    "term_references": terms,
                    "warnings": [],
                },
                model_id="fake-governance-v1",
            )
        if task == "audit_contract":
            text = str(payload.get("contract_text", ""))
            risky_markers = (
                "另行追加", "额外支付", "再额外", "另行提供",
                "专项补助", "另补",
            )
            marker = next(
                (item for item in risky_markers if item in text),
                None,
            )
            issues = []
            if marker is not None:
                line = next(
                    (
                        value.strip()
                        for value in text.splitlines()
                        if marker in value
                    ),
                    marker,
                )
                issues.append({
                    "issue_id": "AUDIT-SEMANTIC-001",
                    "severity": "error",
                    "category": "unstructured_commitment",
                    "term_field": None,
                    "message": "正文包含结构化附件之外的额外承诺表述。",
                    "text_quote": line,
                    "suggestion": "删除额外承诺，或先修改结构化资源条款后重新生成合同。",
                })
            return GovernanceLLMResult(
                task=task,
                data={
                    "status": "reject" if issues else "pass",
                    "summary": (
                        "发现正文与结构化条款可能不一致。"
                        if issues else "合同正文与结构化条款一致。"
                    ),
                    "detected_commitments": [],
                    "issues": issues,
                },
                model_id="fake-contract-auditor-v1",
            )
        if task == "consider_housing_viewing":
            return GovernanceLLMResult(task=task, data={"decision": "go"}, model_id="fake-governance-v1")
        if task == "review_contract":
            allowed = list(payload.get("allowed_decisions", ()))
            decision = "accept" if "accept" in allowed else (
                "explain" if "explain" in allowed else allowed[0]
            )
            return GovernanceLLMResult(
                task=task,
                data={
                    "decision": decision,
                    "reason": (
                        "合同已经把本户关心的资源、期限和责任写清楚。"
                        if decision == "accept"
                        else "本户的必要条件尚未完整写入合同。"
                    ),
                    "counteroffer": {},
                },
                model_id="fake-governance-v1",
            )
        if task == "draft_document":
            resolution = dict(payload["resolution"])
            text = (
                f"{payload['title']}\n"
                f"文种：{payload['document_type']}\n"
                f"依据会议：{payload['meeting_id']}\n"
                f"决定事项：{resolution.get('decision', '')}\n"
                f"适用对象：{resolution.get('target_scope', '')}\n"
                f"资源模式：{resolution.get('resource_mode', 'authorization_ceiling')}\n"
                f"资源授权上限：{resolution.get('resource_authorization_limits', {})}\n"
                f"依据档案：{resolution.get('evidence_archive_ids', [])}\n"
                f"责任单位：{resolution.get('responsible_ids', [])}\n"
                f"完成期限：D{resolution.get('deadline_day')}。\n"
                f"公开范围：{resolution.get('public_scope', [])}。"
            )
            return GovernanceLLMResult(
                task=task,
                data={"document_text": text, "warnings": []},
                model_id="fake-governance-v1",
            )
        if task == "audit_document":
            text = str(payload.get("document_text", ""))
            marker = next(
                (
                    item for item in (
                        "另行追加", "额外支付", "再额外", "另行提供"
                    )
                    if item in text
                ),
                None,
            )
            issues = []
            if marker is not None:
                issues.append({
                    "issue_id": "DOC-AUDIT-SEMANTIC-001",
                    "severity": "error",
                    "category": "authority_expansion",
                    "message": "正文包含会议决议之外的新增承诺。",
                    "text_quote": marker,
                    "suggestion": "删除新增承诺，只保留已通过的会议决议。",
                })
            return GovernanceLLMResult(
                task=task,
                data={
                    "status": "needs_revision" if issues else "pass",
                    "summary": (
                        "发现需要修订的越权表述。"
                        if issues else "文书与会议决议、权限边界一致。"
                    ),
                    "issues": issues,
                },
                model_id="fake-document-reviewer-v1",
            )
        if task == "revise_document":
            issues = list(payload.get("review", {}).get("issues", ()))
            return GovernanceLLMResult(
                task=task,
                data={
                    "document_text": str(payload["safe_reference_text"]),
                    "change_summary": "按审校意见删除越权表述并恢复决议原意。",
                    "addressed_issue_ids": [
                        str(item.get("issue_id")) for item in issues
                    ],
                },
                model_id="fake-document-reviser-v1",
            )
        if task == "meeting_position":
            return GovernanceLLMResult(
                task=task,
                data={
                    "position": "approve",
                    "reason": "材料和权限边界明确，可以按会议决议推进。",
                },
                model_id="fake-governance-v1",
            )
        raise ValueError(f"unsupported governance task: {task}")



def build_test_container(settings, *args, **kwargs):
    """Build a test container with an explicit test-only gateway injection."""
    from serious_game_backend.bootstrap import build_container as _build_container

    kwargs.setdefault("server_role_llm", DeterministicRoleLLMGateway())
    return _build_container(settings, *args, **kwargs)
