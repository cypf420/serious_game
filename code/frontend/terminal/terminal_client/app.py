from __future__ import annotations

import shlex
import time
from getpass import getpass
from typing import Callable

from .api_client import ApiClient, ApiError
from .renderer import (
    render_actions,
    render_decision,
    render_feed,
    render_opportunities,
    render_state,
)


HELP_TEXT = """可用命令：
  register <username>         注册本地测试账号（交互输入密码）
  login <username>            登录已有账号（交互输入密码）
  whoami                     查看当前登录账号
  logout                     退出账号
  new                         开始新游戏
  continue                    继续当前账号最近一局
  load <session_id>           载入已有游戏
  scene                       刷新并显示新剧情、状态和待决策
  next                        继续阅读当日后续剧情
  status                      显示当前玩家可见状态
  choose <A|option_id>        提交当前强制决策
  order <A B C D [E]>         提交当前排序题的完整顺序
  allocate <A B C D额度>      提交分配题四项整数额度
  actions                     查看自主行动目录
  opportunities               查看当前 NPC 互动机会
  do <action_id>              按服务端提示配置、报价并执行资源行动
  governance                  查看权限、档案、红头文件、合同与资源占用
  cancel-governance <id>      中止卡住的入户、访谈或班子会议
  contract <contract_id>      拟定、送审并确认一份逐户合同
  document <document_id>      会签、签发并公示一份会议产出文件
  talk <opportunity_id> <话>  在服务端开放的机会中与 NPC 交谈
  leave                       结束当前进行中的 NPC 会谈
  knowledge                   查看已掌握的事实、线索与证据
  map                         查看当前地图入口和可用状态
  review                      查看本局只读复盘
  group <回应内容>            回应NPC发起的强制群组会谈
  validate                    查看完整剧本包校验报告
  end                         结束当天并执行夜间推进
  overtime <1|2|3>            行动点用尽后申请本章加班额度
  help                        显示帮助
  quit                        退出客户端（不会删除存档）"""


class TerminalApp:
    DOCUMENT_TYPE_LABELS = {
        "implementation_notice": "工作实施通知",
        "medical_guarantee": "医疗保障文件",
        "grave_or_shrine_approval": "迁坟或祠堂事项批复",
        "compensation_adjustment": "补偿方案调整文件",
        "hearing_notice": "听证通知",
        "investigation_notice": "调查通知",
    }
    OWNERSHIP_STATUS_LABELS = {
        "clear": "权属清晰",
        "overbuild_partly_recognized": "部分超建已认定，剩余待处理",
        "ledger_sensitive": "台账差异敏感",
        "old_contract_sensitive": "历史合同待核验",
        "old_road_case_pending": "历史道路旧案未结",
        "old_materials_sensitive": "历史材料待核验",
        "business_verified": "经营性房屋已核验",
        "procedure_sensitive": "程序补正敏感",
        "migrant_authorization_needed": "外出人员授权待补",
        "prior_extra_payment_risk": "既往额外付款风险",
    }
    CONTRACT_FIELD_LABELS = {
        "contract_id": "合同编号",
        "household_id": "家庭编号",
        "signatory_name": "签约人",
        "policy_document_id": "政策依据",
        "cash_amount": "现金补偿额",
        "budget_envelope": "预算科目",
        "housing_resource_id": "安置房",
        "service_allocations": "配套服务",
        "payment_day": "付款日",
        "move_out_day": "搬离日",
        "housing_delivery_day": "交房日",
        "transition_months": "过渡月数",
        "public_window_reward": "公开时间窗奖励",
        "approval_document_ids": "引用的批准文件",
        "authorization_confirmed": "本人授权核验",
        "real_unit_viewed": "实房查看",
        "ledger_disclosed": "测算账公开",
        "old_case_resolved": "历史旧案处理",
        "prior_payment_verified": "既往付款核验",
    }
    AUDIT_CATEGORY_LABELS = {
        "resource_authority": "资源授权",
        "unstructured_commitment": "附件外承诺",
        "missing_required_term": "必要条款缺失",
        "missing_authority_clause": "资源权威条款缺失",
        "policy_conflict": "政策冲突",
        "identity_mismatch": "签约主体不一致",
        "date_conflict": "履行日期冲突",
    }
    BUDGET_ENVELOPE_LABELS = {
        "property_land": "房屋与土地补偿",
        "housing_delivery": "安置房建设与交付",
        "moving_transition_reward": "搬迁、过渡与奖励",
        "attachments_business_graves": "附属物、经营与迁坟",
        "medical_hardship_employment_school": "医疗、困难救助、就业与就学",
        "investigation_legal_publicity": "调查、法务与公开",
        "risk_reserve": "风险预备金",
    }
    ERROR_DETAIL_LABELS = {
        "minimum": "政策最低补偿额",
        "submitted": "本次填写金额",
        "required": "所需数量",
        "available": "当前可用数量",
        "document_ids": "批准文件",
        "resource_ids": "资源",
        "resources": "资源不足明细",
        "expected": "合同应占用资源",
        "reserved": "当前有效预占",
        "audit_status": "专业审校状态",
        "audit": "专业审校问题",
    }

    def __init__(
        self,
        api: ApiClient,
        *,
        input_fn: Callable[[str], str] = input,
        output_fn: Callable[[str], None] = print,
        sleep_fn: Callable[[float], None] = time.sleep,
        password_fn: Callable[[str], str] = getpass,
        menu_mode: bool = False,
    ) -> None:
        self.api = api
        self.input = input_fn
        self.output = output_fn
        self.sleep = sleep_fn
        self.password = password_fn
        self.menu_mode = menu_mode
        self.session_id: str | None = None
        self.state_version: int | None = None
        self.feed_cursor = 0
        self.rendered_content_ids: set[str] = set()
        self.state: dict = {}
        self.option_labels: dict[str, str] = {}
        self.commands: dict = {}
        self.authentication_required = False
        self.authenticated = False
        self.pending_operation_id: str | None = None
        self.show_night_dialogues = False
        self.night_dialogue_preference_set = False
        self.rendered_night_groups: set[str] = set()

    def run(self) -> int:
        self.output("《浊流之上》文字测试客户端")
        try:
            readiness_call = getattr(self.api, "readiness", None)
            readiness = readiness_call() if readiness_call else {}
        except ApiError:
            readiness = {}
        self.authentication_required = bool(readiness.get("authentication_required"))
        self.authenticated = not self.authentication_required
        if self.authentication_required:
            try:
                self.api.me()
                self.authenticated = True
            except ApiError:
                self.authenticated = False
            if self.authenticated:
                self._post_auth_guide()
            else:
                self.output(
                    "尚未登录，请在账号入口选择登录或注册。" if self.menu_mode else
                    "尚未登录。下一步：输入 register <用户名> 注册，或 login <用户名> 登录。"
                )
        else:
            self.output(
                "请在游戏入口选择继续存档或开始新游戏。" if self.menu_mode else
                "输入 new 开始游戏。"
            )
        if self.menu_mode:
            return self._run_menu()
        while True:
            try:
                raw = self.input(self._command_prompt()).strip()
            except (EOFError, KeyboardInterrupt):
                self.output("")
                return 0
            if not raw:
                continue
            try:
                if not self.handle(raw):
                    return 0
            except ApiError as exc:
                self.output(f"[后端错误 {exc.code}] {exc.message}")
                if exc.code in {"AUTHENTICATION_REQUIRED", "INVALID_CREDENTIALS"}:
                    self.authenticated = False
                    self.output("下一步：输入 login <用户名> 重试；没有账号则输入 register <用户名>。")
                elif exc.code == "SESSION_CONTENT_UNAVAILABLE":
                    self._handle_unavailable_session()
                elif self.session_id:
                    self._safe_refresh()
            except ValueError as exc:
                self.output(f"[输入错误] {exc}")

    def handle(self, raw: str) -> bool:
        try:
            parts = shlex.split(raw)
        except ValueError as exc:
            raise ValueError(f"无法解析命令：{exc}") from exc
        if not parts:
            return True
        command = parts[0].lower()
        args = parts[1:]

        if self.pending_operation_id and command not in {"quit", "exit", "help", "?"}:
            self._resume_pending_operation()
            self.output("上一轮会谈结果已经恢复，请确认回复后再决定下一步。")
            return True

        if command in {"quit", "exit"}:
            return False
        if command in {"help", "?"}:
            self.output(HELP_TEXT)
        elif command == "register":
            if len(args) != 1:
                raise ValueError("用法：register <username>")
            password = self._read_new_password()
            result = self.api.register(args[0], password)
            self.authenticated = True
            self.output(f"注册并登录成功：{result['account_id']}")
            self._post_auth_guide()
        elif command == "login":
            if len(args) != 1:
                raise ValueError("用法：login <username>")
            result = self.api.login(args[0], self.password("密码："))
            self.authenticated = True
            self.output(f"登录成功：{result['account_id']}")
            self._post_auth_guide()
        elif command == "whoami":
            result = self.api.me()
            self.authenticated = True
            self.output(
                f"当前账号：{result['account_id']}｜角色："
                f"{','.join(result.get('roles', []))}"
            )
        elif command == "logout":
            self.api.logout()
            self.authenticated = False
            self.session_id = None
            self.pending_operation_id = None
            self.state_version = None
            self.show_night_dialogues = False
            self.night_dialogue_preference_set = False
            self.rendered_night_groups.clear()
            self.output("已退出登录。")
            self.output("下一步：输入 login <用户名>，或 register <用户名> 注册新账号。")
        elif command == "new":
            if args:
                raise ValueError("用法：new")
            self._new()
        elif command == "continue":
            self._continue_latest()
        elif command == "load":
            if len(args) != 1:
                raise ValueError("用法：load <session_id>")
            self._load(args[0])
        elif command == "scene":
            self._refresh()
        elif command == "status":
            self._require_session()
            self._write_lines(render_state(self.state))
            self._guide_current(self.commands)
        elif command == "choose":
            if len(args) != 1:
                raise ValueError("用法：choose <A|option_id>")
            self._choose(args[0])
        elif command == "order":
            if len(args) not in {3, 4, 5}:
                raise ValueError("用法：order A B C D [E]")
            self._order(args)
        elif command == "allocate":
            if len(args) != 4:
                raise ValueError("用法：allocate <签约补偿> <民生安抚> <环评复检> <应急维稳>")
            self._allocate(args)
        elif command == "actions":
            self._actions()
        elif command == "opportunities":
            self._opportunities()
        elif command == "do":
            if len(args) != 1:
                raise ValueError("用法：do <action_id>")
            self._do(args[0])
        elif command == "governance":
            if args:
                raise ValueError("用法：governance")
            self._show_governance()
        elif command == "cancel-governance":
            if len(args) != 1:
                raise ValueError(
                    "用法：cancel-governance <action_instance_id>"
                )
            self._cancel_governance(args[0])
        elif command == "contract":
            if len(args) != 1:
                raise ValueError("用法：contract <contract_id>")
            self._process_contract(args[0])
        elif command == "document":
            if len(args) != 1:
                raise ValueError("用法：document <document_id>")
            self._process_document(args[0])
        elif command == "talk":
            if len(args) < 2:
                raise ValueError("用法：talk <opportunity_id> <你要说的话>")
            self._command_talk(args[0], " ".join(args[1:]))
        elif command == "leave":
            active = self.state.get("active_conversation") or {}
            if not active.get("conversation_id"):
                raise ValueError("当前没有进行中的会谈")
            self._end_conversation(str(active["conversation_id"]))
        elif command == "knowledge":
            self._knowledge()
        elif command == "map":
            self._map()
        elif command == "review":
            self._review()
        elif command == "group":
            if not args:
                raise ValueError("用法：group <你对群组会谈的回应>")
            self._reply_group_conversation(" ".join(args))
        elif command == "validate":
            self._validate_package()
        elif command == "end":
            self._end_day()
        elif command == "next":
            self._continue_story()
        elif command == "overtime":
            if len(args) != 1 or args[0] not in {"1", "2", "3"}:
                raise ValueError("用法：overtime <1|2|3>")
            self._request_overtime(int(args[0]))
        else:
            raise ValueError(f"未知命令：{parts[0]}；输入 help 查看命令")
        return True

    def _new(self) -> None:
        state = self.api.new_session()
        self.session_id = str(state["session_id"])
        self.pending_operation_id = None
        self.state_version = int(state["state_version"])
        self.feed_cursor = 0
        self.rendered_content_ids.clear()
        self.rendered_night_groups.clear()
        self.state = state
        self.option_labels = {}
        self.commands = {}
        self.output(f"已创建游戏：{self.session_id}")
        self._refresh()
        self._show_new_night_dialogues()

    def _continue_latest(self) -> None:
        state = self.api.get_latest_active()
        self._load(str(state["session_id"]))

    def _load(self, session_id: str) -> None:
        same_session = self.session_id == session_id
        self.session_id = session_id
        self.pending_operation_id = None
        self.state_version = None
        if not same_session:
            self.feed_cursor = 0
            self.rendered_content_ids.clear()
            self.rendered_night_groups.clear()
        self.state = {}
        self.option_labels = {}
        self.commands = {}
        self._refresh()
        self._show_new_night_dialogues()

    def _refresh(self) -> None:
        session_id = self._require_session()
        document = self.api.get_view(session_id, after=self.feed_cursor)
        self.state = document["state"]
        self.state_version = int(self.state["state_version"])
        feed = document.get("feed", {})
        fresh_items = []
        for item in feed.get("items", []):
            content_id = item.get("content_instance_id")
            if content_id and content_id in self.rendered_content_ids:
                continue
            if content_id:
                self.rendered_content_ids.add(str(content_id))
            fresh_items.append(item)
        self._write_lines(render_feed(fresh_items))
        self.feed_cursor = max(self.feed_cursor, int(feed.get("cursor", self.feed_cursor)))
        self._write_lines(render_state(self.state))
        decision_lines, self.option_labels = render_decision(
            self.state.get("pending_decision"), show_options=not self.menu_mode
        )
        self._write_lines(decision_lines)
        commands = document.get("commands", {})
        self.commands = commands
        if not commands.get("can_choose") and not any(
            commands.get(key) for key in ("can_act", "can_talk", "can_end_day", "can_continue_story")
        ):
            self.output("当前剧情节点暂无可提交命令。")
        self._guide_current(commands)

    def _choose(self, value: str) -> None:
        session_id = self._require_session()
        pending = self.state.get("pending_decision")
        if not pending:
            raise ValueError("当前没有待处理决策")
        option_id = self.option_labels.get(value.upper(), value)
        allowed = {
            str(item["option_id"])
            for item in pending.get("options", [])
            if item.get("available", True)
        }
        if option_id not in allowed:
            raise ValueError("选项不存在；请使用当前显示的字母或 option_id")
        client_action_id = self.api.new_key("decision")
        result = self.api.submit_decision(
            session_id,
            state_version=self._require_version(),
            decision_id=str(pending["decision_id"]),
            option_id=option_id,
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self.output("决策已提交。")
        self._refresh()

    def _order(self, values: list[str]) -> None:
        session_id = self._require_session()
        pending = self.state.get("pending_decision")
        if not pending or pending.get("input_kind") != "sorting":
            raise ValueError("当前待决策不是排序题")
        ordered = [item.lower() for item in values]
        required = [str(item).lower() for item in pending.get("input_schema", {}).get("items", [])]
        if sorted(ordered) != sorted(required):
            raise ValueError("排序项必须完整且不能重复")
        client_action_id = self.api.new_key("decision")
        result = self.api.submit_decision(
            session_id,
            state_version=self._require_version(),
            decision_id=str(pending["decision_id"]),
            ordered_option_ids=ordered,
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self.output("排序决策已提交。")
        self._refresh()

    def _allocate(self, values: list[str]) -> None:
        session_id = self._require_session()
        pending = self.state.get("pending_decision")
        if not pending or pending.get("input_kind") != "allocation":
            raise ValueError("当前待决策不是分配题")
        try:
            amounts = [int(item) for item in values]
        except ValueError as exc:
            raise ValueError("四项额度必须是整数") from exc
        schema = pending.get("input_schema", {})
        fields = list(schema.get("fields", []))
        if len(fields) != 4 or sum(amounts) != int(schema.get("total", 0)):
            raise ValueError(f"四项额度之和必须为 {schema.get('total')} {schema.get('unit', '')}")
        client_action_id = self.api.new_key("decision")
        result = self.api.submit_decision(
            session_id,
            state_version=self._require_version(),
            decision_id=str(pending["decision_id"]),
            parameters={"allocations": dict(zip(fields, amounts, strict=True))},
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self.output("分配决策已提交。")
        self._refresh()

    def _actions(self) -> None:
        document = self.api.get_actions(self._require_session())
        self.state_version = int(document["state_version"])
        self._write_lines(render_actions(document))
        if any(item.get("available") for item in document.get("actions", [])):
            self.output("下一步：输入 do <action_id>，再按提示选择对象和参数；输入 scene 返回剧情。")
        else:
            self.output("当前没有可执行的自主行动。下一步：输入 scene 查看剧情，或 end 尝试日终。")

    def _opportunities(self) -> None:
        document = self.api.get_opportunities(self._require_session())
        self.state_version = int(document["state_version"])
        self._write_lines(render_opportunities(document))
        if document.get("opportunities"):
            self.output("下一步：输入 talk <opportunity_id> <你要说的话>；输入 scene 返回剧情。")
        else:
            self.output("当前没有可交谈对象。下一步：输入 scene 查看剧情，或 actions 查看行动。")

    def _do(self, action_id: str) -> None:
        session_id = self._require_session()
        document = self.api.get_actions(session_id)
        actions = {str(item["action_id"]): item for item in document.get("actions", [])}
        item = actions.get(action_id)
        if item is None:
            raise ValueError("行动 ID 不存在；先输入 actions 查看目录")
        if not item.get("available"):
            raise ValueError(str(item.get("unavailable_reason") or "当前行动不可用"))
        if item.get("execution_mode") == "governance":
            self._run_governance_action(item)
            return
        if item.get("execution_mode") == "conversation":
            raise ValueError("该行动必须从“交谈”入口选择具体人物")
        self._run_resource_action(item)

    def _show_governance(self) -> dict:
        overview = self.api.get_governance(self._require_session())
        self.state_version = int(overview["state_version"])
        cash = overview.get("resources", {}).get("cash_ledger", {})
        self.output(
            "财政：账面余额 "
            f"{cash.get('remaining', 0)}｜可再支配 "
            f"{cash.get('available_unencumbered', cash.get('remaining', 0))}"
            f"｜已签未付 {cash.get('outstanding', 0)}"
        )
        holds = overview.get("resources", {}).get("active_reservations", [])
        if holds:
            self.output("当前资源占用：")
            for hold in holds:
                self.output(
                    f"  {hold['resource_id']} × {hold['quantity']}｜"
                    f"{hold['display_status']}｜来源 {hold['owner_type']}:{hold['owner_id']}"
                )
        documents = overview.get("documents", [])
        if documents:
            self.output("档案下的行政文件：")
            for document in documents:
                self.output(
                    f"  {document['document_id']}｜{document['title']}｜{document['status']}"
                )
                for resource_id, status in document.get(
                    "authorization_status", {}
                ).items():
                    self.output(
                        f"    授权 {resource_id}："
                        f"{status['drawn']}/{status['authorized']}，"
                        f"剩余 {status['remaining']}"
                    )
        contracts = overview.get("contracts", [])
        if contracts:
            self.output("逐户合同：")
            for contract in contracts:
                self.output(
                    f"  {contract['contract_id']}｜{contract['household_id']}｜"
                    f"{contract['signatory_name']}｜{contract['status']}｜"
                    f"审校 {contract.get('audit_status', 'not_started')}｜"
                    f"{contract['resource_hold_status']}"
                )
        active_actions = [
            item for item in overview.get("governance_actions", [])
            if item.get("status") == "active"
        ]
        if active_actions:
            self.output("进行中的治理行动：")
            for action in active_actions:
                self.output(
                    f"  {action['action_instance_id']}｜"
                    f"{action['action_kind']}｜{action.get('topic', '')}"
                )
            self.output(
                "如当前流程无法继续，可输入 "
                "cancel-governance <action_instance_id> 中止。"
            )
        return overview

    def _cancel_governance(self, action_instance_id: str) -> None:
        result = self.api.cancel_governance_action(
            self._require_session(),
            action_instance_id,
            state_version=self._require_version(),
        )
        self.state_version = int(result["state_version"])
        self.output(
            f"治理行动 {action_instance_id} 已中止；"
            "已消耗的行动点不退回。"
        )

    def _run_governance_action(self, item: dict) -> None:
        overview = self.api.get_governance(self._require_session())
        self.state_version = int(overview["state_version"])
        action_kind = str(item["action_id"])
        if action_kind == "inspect_archives":
            archives = list(overview.get("archives", []))
            if not archives:
                raise ValueError("当前没有已经取得、可供查阅的档案")
            selected = self._select(
                "选择要查阅的档案",
                [
                    f"{entry['title']}｜证据等级 {entry['evidence_level']}"
                    for entry in archives
                ],
                back_label="取消查阅",
            )
            if selected is None:
                return
            result = self.api.start_governance_action(
                self._require_session(),
                state_version=self._require_version(),
                action_kind=action_kind,
                target_ids=[],
                archive_ids=[str(archives[selected]["archive_id"])],
            )
            self.state_version = int(result["state_version"])
            for archive in result.get("archives", []):
                sections = [
                    section for section in archive.get("player_sections", [])
                    if isinstance(section, dict) and section.get("body")
                ]
                body = "\n\n".join(
                    f"{section.get('heading', '档案记录')}\n{section['body']}"
                    for section in sections
                ) or "这份档案暂无可读正文。"
                self.output(f"【{archive['title']}】\n{body}")
            return

        if action_kind == "leadership_meeting":
            self._run_governance_meeting(overview)
            return

        target_kind = str(item.get("target_kind", ""))
        choices = list(
            overview.get("target_catalogs", {}).get(target_kind, [])
        )
        selected = self._select(
            "选择互动对象",
            [str(entry["label"]) for entry in choices],
            back_label="取消行动",
        )
        if selected is None:
            return
        topic = self.input("本次行动的具体议题：").strip()
        if not topic:
            raise ValueError("议题不能为空")
        started = self.api.start_governance_action(
            self._require_session(),
            state_version=self._require_version(),
            action_kind=action_kind,
            target_ids=[str(choices[selected]["target_id"])],
            topic=topic,
        )
        self.state_version = int(started["state_version"])
        action_id = str(started["action"]["action_instance_id"])
        while True:
            player_text = self.input("你的发言：").strip()
            if player_text:
                break
            self.output("发言不能为空，请重新输入。")
        while True:
            turn = self.api.governance_action_turn(
                self._require_session(),
                action_id,
                state_version=self._require_version(),
                player_text=player_text,
            )
            self.state_version = int(turn["state_version"])
            if not turn.get("input_rejected"):
                break
            self.output(str(turn["message"]))
            player_text = self.input("请重新输入与游戏相关的发言：").strip()
            if not player_text:
                self.output(
                    f"行动仍在进行。可输入 cancel-governance {action_id} 中止。"
                )
                return
        for reply in turn.get("replies", []):
            self.output(f"{reply['npc_name']}：{reply['text']}")
        if turn.get("acquired_archive_ids"):
            self.output(
                "取得档案：" + "、".join(turn["acquired_archive_ids"])
            )
        proposal = turn.get("contract_batch_proposal")
        if proposal:
            self.output(
                "系统识别到逐户签约请求；将分别生成 "
                f"{len(proposal['household_ids'])} 份独立合同。"
            )
            confirmed = self._select(
                "确认发起合同批次？",
                ["按该代表人及其所代表各户逐户建合同"],
                back_label="取消批次",
            ) is not None
            batch = self.api.confirm_contract_batch(
                self._require_session(),
                str(proposal["batch_id"]),
                state_version=self._require_version(),
                confirmed=confirmed,
            )
            self.state_version = int(batch["state_version"])
            for contract in batch.get("contracts", []):
                self.output(
                    f"已建合同 {contract['contract_id']}｜"
                    f"{contract['household_id']}｜签约人 {contract['signatory_name']}"
                )
            if batch.get("contracts"):
                self.output(
                    "下一步：逐份输入 contract <contract_id> 拟定、送审和签署。"
                )
        finished = self.api.finish_governance_action(
            self._require_session(),
            action_id,
            state_version=self._require_version(),
        )
        self.state_version = int(finished["state_version"])

    def _run_governance_meeting(self, overview: dict) -> None:
        document_types = list(overview.get("document_types", []))
        document_choice = self._select(
            "本次会议是否形成行政文件",
            ["只形成会议纪要"] + [
                self.DOCUMENT_TYPE_LABELS.get(
                    str(item["document_type"]), "其他行政文件"
                ) for item in document_types
            ],
            back_label="取消会议",
        )
        if document_choice is None:
            return
        document_rule = (
            None if document_choice == 0 else document_types[document_choice - 1]
        )
        proposed_type = (
            None if document_rule is None
            else str(document_rule["document_type"])
        )
        people = list(
            overview.get("target_catalogs", {}).get(
                "meeting_participants", []
            )
        )
        by_id = {str(item["target_id"]): item for item in people}
        initial_participant_ids = list(
            document_rule.get("required_countersign_ids", [])
            if document_rule else []
        )
        participant_ids = self._select_meeting_participants(
            people, initial_participant_ids
        )
        if participant_ids is None:
            return
        self.output(
            "参会人：" + "、".join(
                str(by_id[npc_id]["label"]) for npc_id in participant_ids
            )
        )
        topic = self.input("会议具体议题：").strip()
        if not topic:
            raise ValueError("会议议题不能为空")
        archives = list(overview.get("archives", []))
        archive_ids: list[str] = []
        if proposed_type and archives:
            selected = self._select(
                "选择会议依据档案",
                [
                    f"{item['title']}｜{item['evidence_level']}"
                    for item in archives
                ],
                back_label="不引用档案",
            )
            if selected is not None:
                archive_ids.append(str(archives[selected]["archive_id"]))
        started = self.api.start_governance_action(
            self._require_session(),
            state_version=self._require_version(),
            action_kind="leadership_meeting",
            target_ids=participant_ids,
            topic=topic,
            archive_ids=archive_ids,
            proposed_document_type=proposed_type,
        )
        self.state_version = int(started["state_version"])
        meeting = started["meeting"]
        while True:
            player_text = self.input("面向全体参会人的发言：").strip()
            if not player_text:
                self.output("会议发言不能为空，请重新输入。")
                continue
            turn = self.api.governance_meeting_turn(
                self._require_session(),
                str(meeting["meeting_id"]),
                state_version=self._require_version(),
                player_text=player_text,
            )
            self.state_version = int(turn["state_version"])
            if turn.get("input_rejected"):
                self.output(str(turn["message"]))
                continue
            break
        for reply in turn.get("replies", []):
            self.output(f"{reply['npc_name']}：{reply['text']}")
        decision = self.input("拟形成的决定：").strip()
        target_scope = self.input("适用对象范围：").strip()
        raw_resources = self.input(
            "资源安排（resource_id=数量，多个用逗号；可留空）："
        ).strip()
        resources = self._parse_resource_pairs(raw_resources)
        mode_options = [
            "登记授权上限；具体资源由逐户合同或执行凭证占用"
        ]
        mode_index = self._select(
            "资源写入方式",
            mode_options,
            back_label="取消形成决议",
        )
        if mode_index is None:
            abandoned = self.api.resolve_governance_meeting(
                self._require_session(),
                str(meeting["meeting_id"]),
                state_version=self._require_version(),
                adopt=False,
                resolution={
                    "decision": decision or "本次会议未形成决定",
                    "target_scope": target_scope or "无",
                    "resources": {},
                    "resource_mode": "authorization_ceiling",
                    "responsible_ids": participant_ids,
                    "deadline_day": int(
                        self.state.get("story", {}).get("day", 1)
                    ),
                    "public_scope": ["内部会议纪要"],
                    "document_title": "未形成决议的会议纪要",
                },
            )
            self.state_version = int(abandoned["state_version"])
            self.output("会议已按未采纳议案结束，并保存会议纪要。")
            return
        deadline = int(self.input("完成期限（输入剧情日数字）：").strip())
        public_scope = self.input("允许公示范围：").strip()
        title = self.input("会议纪要或行政文件标题：").strip()
        resolved = self.api.resolve_governance_meeting(
            self._require_session(),
            str(meeting["meeting_id"]),
            state_version=self._require_version(),
            adopt=True,
            resolution={
                "decision": decision,
                "target_scope": target_scope,
                "resources": resources,
                "resource_mode": "authorization_ceiling",
                "responsible_ids": participant_ids,
                "deadline_day": deadline,
                "public_scope": [public_scope],
                "document_title": title,
            },
        )
        self.state_version = int(resolved["state_version"])
        self.output(
            "会议决议已通过。" if resolved["passed"]
            else f"会议未通过：{resolved['failure_reason']}"
        )
        document = resolved.get("document")
        if document:
            self.output(
                f"已生成文件 {document['document_id']}，状态 {document['status']}。"
            )
            self.output(
                f"下一步：输入 document {document['document_id']} 完成会签、签发和公示。"
            )

    @staticmethod
    def _parse_resource_pairs(text: str) -> dict[str, int]:
        if not text:
            return {}
        values: dict[str, int] = {}
        for pair in text.replace("，", ",").split(","):
            key, separator, raw_value = pair.partition("=")
            if not separator or not key.strip():
                raise ValueError("资源格式应为 resource_id=数量")
            amount = int(raw_value.strip())
            if amount <= 0:
                raise ValueError("资源数量必须大于0")
            values[key.strip()] = amount
        return values

    def _render_contract_audit(self, contract: dict) -> None:
        status_labels = {
            "pass": "通过",
            "reject": "不通过",
            "needs_revision": "需要修改",
            "pending": "等待审校",
            "not_started": "尚未开始",
        }
        status = str(contract.get("audit_status", "not_started"))
        audit = dict(contract.get("audit_result") or {})
        self.output(
            f"【合同专业审校：{status_labels.get(status, status)}】"
        )
        if contract.get("audit_model_id"):
            self.output(f"审校模型：{contract['audit_model_id']}")
        if audit.get("summary"):
            self.output(f"结论：{audit['summary']}")
        issues = list(audit.get("issues", []))
        if not issues:
            self.output("未发现需要玩家修正的问题。")
            return
        for index, issue in enumerate(issues, start=1):
            raw_field = issue.get("term_field")
            raw_field_text = str(raw_field)
            field_key = raw_field_text.split(".", 1)[0]
            field = self.CONTRACT_FIELD_LABELS.get(
                field_key, raw_field_text
            ) if raw_field else "正文整体"
            raw_category = str(issue.get("category") or "其他问题")
            category = self.AUDIT_CATEGORY_LABELS.get(
                raw_category, raw_category
            )
            self.output(
                f"  问题{index}｜{category}｜位置字段：{field}"
            )
            self.output(f"    位置：{issue.get('text_quote')}")
            self.output(f"    说明：{issue.get('message')}")
            self.output(f"    建议：{issue.get('suggestion')}")

    def _input_multiline_contract(self) -> str:
        self.output(
            "请输入完整合同正文，可输入多行；单独输入“完成”提交，"
            "单独输入“取消”放弃本次编辑。"
        )
        lines: list[str] = []
        while True:
            line = self.input("正文> ")
            if line.strip() == "完成":
                content = "\n".join(lines).strip()
                if not content:
                    self.output("合同正文不能为空，请继续输入。")
                    continue
                return content
            if line.strip() == "取消":
                return ""
            lines.append(line)

    def _input_multiline_document(self) -> str:
        self.output(
            "请输入修改后的完整文件正文，可输入多行；单独输入“完成”提交，"
            "单独输入“取消”放弃本次编辑。"
        )
        lines: list[str] = []
        while True:
            line = self.input("文件正文> ")
            if line.strip() == "完成":
                content = "\n".join(lines).strip()
                if not content:
                    self.output("文件正文不能为空，请继续输入。")
                    continue
                return content
            if line.strip() == "取消":
                return ""
            lines.append(line)

    def _render_contract_form_error(self, exc: ApiError) -> None:
        self.output(f"【合同条款未通过】{exc.message}")
        if not exc.details:
            return
        self.output("需要检查：")
        for key, value in exc.details.items():
            label = self.CONTRACT_FIELD_LABELS.get(
                str(key),
                self.ERROR_DETAIL_LABELS.get(str(key), str(key)),
            )
            if key in {"missing_term_fields", "missing_term_values"}:
                values = [
                    self.CONTRACT_FIELD_LABELS.get(
                        str(item).split(".", 1)[0],
                        str(item),
                    )
                    for item in value
                ]
                self.output(f"- 缺少字段：{'、'.join(values)}")
            else:
                self.output(f"- {label}：{value}")

    @staticmethod
    def _is_editable_contract_error(exc: ApiError) -> bool:
        return exc.code == "ACTION_UNAVAILABLE"

    @staticmethod
    def _is_retryable_contract_audit_error(exc: ApiError) -> bool:
        return exc.code in {
            "ROLE_LLM_UNAVAILABLE",
            "ROLE_LLM_INVALID_RESPONSE",
        }

    def _prompt_contract_audit_retry(
        self,
        exc: ApiError,
        *,
        retained_content: str,
    ) -> bool:
        self.output(f"【专业合同审校暂不可用】{exc.message}")
        self.output(
            f"{retained_content}仍保留在本次操作中，尚未写入正式草案。"
        )
        return self._select(
            "审校服务恢复操作",
            [f"保持{retained_content}并重新审校"],
            back_label="退出合同处理（本次未通过内容不会保存）",
        ) is not None

    def _prompt_service_allocations(
        self, service_resources: list[dict]
    ) -> dict[str, int]:
        if not service_resources:
            self.output("当前没有可调用的配套服务资源。")
            return {}
        self.output("【可调用的配套服务】")
        for index, item in enumerate(service_resources, start=1):
            self.output(
                f"  {index}. {item.get('name', item['resource_id'])}"
                f"｜可用 {item.get('available', 0)}"
            )
        while True:
            raw = self.input(
                "填写“序号=数量”，多个用逗号；无需服务可留空："
            ).strip()
            if not raw:
                return {}
            try:
                result: dict[str, int] = {}
                for pair in raw.replace("，", ",").split(","):
                    raw_index, separator, raw_amount = pair.partition("=")
                    if not separator:
                        raise ValueError("格式应为“序号=数量”")
                    index = int(raw_index.strip())
                    amount = int(raw_amount.strip())
                    if not 1 <= index <= len(service_resources):
                        raise ValueError("配套服务序号不存在")
                    if amount <= 0:
                        raise ValueError("配套服务数量必须大于0")
                    resource_id = str(
                        service_resources[index - 1]["resource_id"]
                    )
                    result[resource_id] = amount
                return result
            except ValueError as exc:
                self.output(f"配套服务输入错误：{exc}，请重新填写。")

    def _prompt_approval_documents(
        self,
        documents: list[dict],
        *,
        resource_names: dict[str, str] | None = None,
    ) -> list[str]:
        if not documents:
            return []
        self.output("【可引用的已发布批准文件】")
        for index, item in enumerate(documents, start=1):
            limits = item.get("authorization_status", {})
            limit_text = "；".join(
                (
                    f"{(resource_names or {}).get(resource_id, resource_id)}"
                    f"剩余{status.get('remaining', 0)}"
                )
                for resource_id, status in limits.items()
            )
            self.output(
                f"  {index}. {item.get('title', item['document_id'])}"
                + (f"｜{limit_text}" if limit_text else "")
            )
        while True:
            raw = self.input(
                "输入本合同引用的文件序号，多个用逗号；无需引用可留空："
            ).strip()
            if not raw:
                return []
            try:
                indexes = [
                    int(item.strip())
                    for item in raw.replace("，", ",").split(",")
                    if item.strip()
                ]
                if any(
                    not 1 <= index <= len(documents)
                    for index in indexes
                ):
                    raise ValueError("批准文件序号不存在")
                return list(dict.fromkeys(
                    str(documents[index - 1]["document_id"])
                    for index in indexes
                ))
            except ValueError as exc:
                self.output(f"批准文件输入错误：{exc}，请重新填写。")

    def _input_contract_integer(self, label: str) -> int:
        while True:
            raw = self.input(f"{label}：").strip()
            try:
                return int(raw)
            except ValueError:
                self.output(f"{label}必须填写整数，请重新输入。")

    def _edit_contract_term(
        self,
        terms: dict,
        *,
        envelopes: list[str],
        budget_envelopes: dict,
        housing: list[dict],
        service_resources: list[dict],
        approval_documents: list[dict],
        resource_names: dict[str, str],
    ) -> bool:
        document_names = {
            str(item["document_id"]): str(
                item.get("title", item["document_id"])
            )
            for item in approval_documents
        }

        def display_value(key: str) -> object:
            value = terms.get(key)
            if key == "budget_envelope":
                return self.BUDGET_ENVELOPE_LABELS.get(
                    str(value), str(value)
                )
            if key == "housing_resource_id":
                return (
                    resource_names.get(str(value), str(value))
                    if value else "不配置"
                )
            if key == "service_allocations":
                return {
                    resource_names.get(str(resource_id), str(resource_id)): amount
                    for resource_id, amount in dict(value or {}).items()
                }
            if key == "approval_document_ids":
                return [
                    document_names.get(str(item), str(item))
                    for item in value or []
                ]
            if isinstance(value, bool):
                return "是" if value else "否"
            return value

        editable_fields = [
            key for key in self.CONTRACT_FIELD_LABELS
            if key not in {
                "contract_id", "household_id", "signatory_name",
                "policy_document_id", "payment_day", "authorization_confirmed",
                "real_unit_viewed", "ledger_disclosed", "old_case_resolved",
                "prior_payment_verified",
            }
        ]
        selected = self._select(
            "选择需要修改的合同条件",
            [
                (
                    f"{self.CONTRACT_FIELD_LABELS[key]}｜"
                    f"当前：{display_value(key)}"
                )
                for key in editable_fields
            ],
            back_label="退出合同处理（本次未通过内容不会保存）",
        )
        if selected is None:
            return False
        field = editable_fields[selected]
        if field == "budget_envelope":
            choice = self._select(
                "选择预算科目",
                [
                    (
                        f"{self.BUDGET_ENVELOPE_LABELS.get(key, key)}"
                        f"｜可用 {budget_envelopes[key]['available']}"
                    )
                    for key in envelopes
                ],
                back_label="不修改",
            )
            if choice is not None:
                terms[field] = envelopes[choice]
        elif field == "housing_resource_id":
            choice = self._select(
                "选择安置房",
                ["不配置安置房"] + [
                    f"{item['name']}｜可用 {item['available']}"
                    for item in housing
                ],
                back_label="不修改",
            )
            if choice is not None:
                terms[field] = (
                    None if choice == 0
                    else str(housing[choice - 1]["resource_id"])
                )
        elif field == "service_allocations":
            terms[field] = self._prompt_service_allocations(
                service_resources
            )
        elif field == "approval_document_ids":
            terms[field] = self._prompt_approval_documents(
                approval_documents,
                resource_names=resource_names,
            )
        elif field in {
            "public_window_reward", "authorization_confirmed",
            "real_unit_viewed", "ledger_disclosed",
            "old_case_resolved", "prior_payment_verified",
        }:
            choice = self._select(
                self.CONTRACT_FIELD_LABELS[field],
                ["是", "否"],
                back_label="不修改",
            )
            if choice is not None:
                terms[field] = choice == 0
        else:
            terms[field] = self._input_contract_integer(
                f"{self.CONTRACT_FIELD_LABELS[field]}的新值"
            )
        return True

    def _process_contract(self, contract_id: str) -> None:
        overview = self.api.get_governance(self._require_session())
        self.state_version = int(overview["state_version"])
        contract = next(
            (
                item for item in overview.get("contracts", [])
                if str(item["contract_id"]) == contract_id
            ),
            None,
        )
        if contract is None:
            raise ValueError("合同不存在；输入 governance 查看合同清单")
        detail = self.api.get_contract(self._require_session(), contract_id)
        self.state_version = int(detail["state_version"])
        contract = detail["contract"]
        if contract["status"] == "signed":
            self.output(str(contract.get("contract_text", "")))
            self.output(f"该合同已经签署；资源状态：{contract['resource_hold_status']}")
            return
        legacy_ack = False
        if contract.get("legacy_draft"):
            self.output("【旧合同正文，请核对特殊约定】\n" + str(contract.get("contract_text", "")))
            legacy_ack = self._select(
                "核对旧约定后，是否按方案重新生成？旧正文将保留。",
                ["已核对，按方案生成合同"], back_label="返回会谈",
            ) == 0
            if not legacy_ack:
                return
        elif contract.get("term_sheet") and not self._preview_contract(contract):
            return
        documents = [
            item for item in overview.get("documents", [])
            if item.get("status") == "published"
        ]
        policy = next(
            (
                item for item in documents
                if item.get("document_type") == "compensation_policy"
            ),
            None,
        )
        if policy is None:
            raise ValueError("当前没有有效的已发布补偿方案")
        resources = overview.get("resources", {})
        envelopes = list(resources.get("budget_envelopes", {}))
        envelope_index = self._select(
            "选择预算信封",
            [
                (
                    f"{self.BUDGET_ENVELOPE_LABELS.get(key, key)}"
                    f"｜可用 {resources['budget_envelopes'][key]['available']}"
                )
                for key in envelopes
            ],
            back_label="取消拟约",
        )
        if envelope_index is None:
            return
        pools = list(resources.get("resource_pools", []))
        resource_names = {
            str(item["resource_id"]): str(
                item.get("name", item["resource_id"])
            )
            for item in pools
        }
        resource_names.update({
            f"budget:{envelope_id}": self.BUDGET_ENVELOPE_LABELS.get(
                envelope_id, envelope_id
            )
            for envelope_id in envelopes
        })
        housing = [
            item for item in pools
            if item.get("category") == "housing"
            and int(item.get("available", 0)) > 0
        ]
        service_resources = [
            item for item in pools
            if item.get("category") != "housing"
            and item.get("allocatable_scope") != "npc_demand"
            and int(item.get("available", 0)) > 0
        ]
        housing_index = self._select(
            "选择安置房",
            ["不配置安置房"] + [
                f"{item['name']}｜可用 {item['available']}"
                for item in housing
            ],
            back_label="取消拟约",
        )
        if housing_index is None:
            return
        service_allocations = self._prompt_service_allocations(
            service_resources
        )
        cash = self._input_contract_integer("核心现金补偿额（万元）")
        day = int(self.state.get("story", {}).get("day", 1))
        payment_day = day
        self.output("现金补偿于签署当日支付。")
        move_out_day = self._input_contract_integer("搬离日")
        delivery_day = self._input_contract_integer("交房日")
        months = self._input_contract_integer("过渡月数（0至12）")
        booleans = {}
        for key, label in (
            ("public_window_reward", "是否适用公开时间窗奖励"),
        ):
            choice = self._select(
                label, ["是", "否"], back_label="取消拟约"
            )
            if choice is None:
                return
            booleans[key] = choice == 0
        approval_documents = [
            item for item in documents
            if item["document_id"] != policy["document_id"]
        ]
        approval_ids = self._prompt_approval_documents(
            approval_documents,
            resource_names=resource_names,
        )
        terms = {
            "policy_document_id": str(policy["document_id"]),
            "cash_amount": cash,
            "budget_envelope": envelopes[envelope_index],
            "housing_resource_id": (
                None if housing_index == 0
                else str(housing[housing_index - 1]["resource_id"])
            ),
            "service_allocations": service_allocations,
            "payment_day": payment_day,
            "move_out_day": move_out_day,
            "housing_delivery_day": delivery_day,
            "transition_months": months,
            "approval_document_ids": approval_ids,
            **booleans,
        }
        if legacy_ack:
            terms["acknowledge_legacy_text"] = True
        while True:
            try:
                drafted = self.api.set_contract_terms(
                    self._require_session(), contract_id,
                    state_version=self._require_version(), term_sheet=terms,
                )
                self.state_version = int(drafted["state_version"])
                if not self._preview_contract(drafted["contract"]):
                    return
            except ApiError as exc:
                if not self._is_editable_contract_error(exc):
                    raise
                self._render_contract_form_error(exc)
            if not self._edit_contract_term(
                terms, envelopes=envelopes,
                budget_envelopes=resources["budget_envelopes"], housing=housing,
                service_resources=service_resources,
                approval_documents=approval_documents, resource_names=resource_names,
            ):
                return

    def _preview_contract(self, contract: dict) -> bool:
        """Return True only when the player chooses to modify the scheme."""
        self.output("【合同预览】\n" + str(contract.get("contract_text", "")))
        if contract.get("review_reason"):
            self.output(f"【对方的签约答复 · 方案第{contract.get('review_version', '?')}版】\n"
                        + str(contract["review_reason"]))
        can_review = bool(contract.get("can_review"))
        if not can_review:
            self.output(str(contract.get("review_blocked_reason") or "请先继续协商或修改方案。"))
        options = (["提交签约（对方接受后立即生效并扣除资源）"] if can_review else [])
        options += ["修改方案", "返回会谈继续协商"]
        choice = self._select("合同办理", options, back_label="返回会谈")
        if choice is None:
            return False
        if can_review and choice == 0:
            result = self.api.review_contract(
                self._require_session(), str(contract["contract_id"]),
                state_version=self._require_version(),
            )
            self._handle_contract_review_result(result)
            return False
        return choice == (1 if can_review else 0)

    def _handle_contract_review_result(self, reviewed: dict) -> bool:
        self.state_version = int(reviewed["state_version"])
        contract = reviewed["contract"]
        self.output(
            f"签约人决定：{contract['review_decision']}｜"
            f"{contract['review_reason']}"
        )
        self.output(f"资源状态：{contract['resource_hold_status']}")
        if contract["status"] == "signed":
            self.output(
                f"合同签署成功｜资源状态："
                f"{contract['resource_hold_status']}"
            )
            return True
        if contract.get("counteroffer"):
            self.output(f"反报价：{contract['counteroffer']}")
        return False

    def _process_document(self, document_id: str) -> None:
        overview = self.api.get_governance(self._require_session())
        self.state_version = int(overview["state_version"])
        document = next(
            (
                item for item in overview.get("documents", [])
                if str(item["document_id"]) == document_id
            ),
            None,
        )
        if document is None:
            raise ValueError("文件不存在；输入 governance 查看文件清单")
        self.output(
            f"【{document['title']}｜版本{document['version']}】\n"
            f"{document.get('content', '')}"
        )
        if document["status"] in {"draft", "pending_countersign"}:
            while True:
                edit_choice = self._select(
                    "文件正文确认",
                    ["保持当前正文并进入会签", "修改完整文件正文"],
                    back_label="暂不处理该文件",
                )
                if edit_choice is None:
                    return
                if edit_choice == 0:
                    break
                replacement = self._input_multiline_document()
                if not replacement:
                    continue
                try:
                    edited = self.api.edit_document(
                        self._require_session(),
                        document_id,
                        state_version=self._require_version(),
                        content=replacement,
                    )
                except ApiError as exc:
                    if not self._is_editable_contract_error(exc):
                        raise
                    self.output(f"【文件正文未通过】{exc.message}")
                    continue
                self.state_version = int(edited["state_version"])
                document = edited["document"]
                self.output(
                    f"文件正文已保存为版本{document['version']}；"
                    "此前会签已按现实程序清空，需要重新会签。"
                )
                self.output(
                    f"【修改后全文】\n{document.get('content', '')}"
                )
            pending = [
                npc_id
                for npc_id in document.get("required_countersign_ids", [])
                if npc_id not in document.get("countersigned_by", [])
            ]
            for npc_id in pending:
                result = self.api.countersign_document(
                    self._require_session(),
                    document_id,
                    state_version=self._require_version(),
                    npc_id=str(npc_id),
                )
                self.state_version = int(result["state_version"])
                document = result["document"]
                self.output(
                    f"{npc_id}会签："
                    f"{'同意' if result['accepted'] else '不同意'}｜"
                    f"{result['reason']}"
                )
                if not result["accepted"]:
                    return
        if document["status"] == "approved":
            if self._select(
                "确认签发该文件？",
                ["签发并登记政策、责任与资源授权上限"],
                back_label="暂不签发",
            ) is None:
                return
            issued = self.api.issue_document(
                self._require_session(),
                document_id,
                state_version=self._require_version(),
            )
            self.state_version = int(issued["state_version"])
            document = issued["document"]
            self.output("文件已签发并进入档案。")
        if document["status"] in {"issued", "published"}:
            allowed_scope = list(
                document.get("resolution_snapshot", {}).get(
                    "public_scope", document.get("public_scope", [])
                )
            )
            if not allowed_scope:
                self.output("文件没有登记可公示范围，流程在签发处结束。")
                return
            scope_index = self._select(
                "选择本次公示范围",
                [str(scope) for scope in allowed_scope],
                back_label="暂不公示",
            )
            if scope_index is None:
                return
            published = self.api.publish_document(
                self._require_session(),
                document_id,
                state_version=self._require_version(),
                scope=[str(allowed_scope[scope_index])],
            )
            self.state_version = int(published["state_version"])
            self.output(
                f"文件已公示；本次公示行动点成本 "
                f"{published['cost_action_points']}。"
            )

    def _run_resource_action(self, item: dict) -> None:
        target_schema = item.get("target_schema") or {}
        minimum = int(target_schema.get("min_items", 0))
        choices = list(item.get("target_choices", []))
        targets: list[str] = []
        remaining = list(choices)
        for position in range(minimum):
            if not remaining:
                raise ValueError("当前可选对象不足，尚不能执行这个行动")
            selected = self._select(
                f"选择行动对象（{position + 1}/{minimum}）",
                [str(value.get("label", "行动对象")) for value in remaining],
                back_label="取消本次行动",
            )
            if selected is None:
                return
            targets.append(str(remaining.pop(selected)["target_id"]))
        parameter_schema = item.get("parameter_schema") or {}
        properties = dict(parameter_schema.get("properties", {}))
        parameters: dict = {}
        for key in parameter_schema.get("required", []):
            spec = properties.get(key, {})
            enum_values = list(spec.get("enum", []))
            if not enum_values:
                raise ValueError(f"参数 {key} 没有可供选择的登记值")
            selected = self._select(
                f"选择{key}",
                [str(value) for value in enum_values],
                back_label="取消本次行动",
            )
            if selected is None:
                return
            parameters[str(key)] = enum_values[selected]
        session_id = self._require_session()
        quote = self.api.quote_action(
            session_id,
            state_version=self._require_version(),
            action_id=str(item["action_id"]),
            target_ids=targets,
            parameters=parameters,
        )
        self.output(
            f"执行前报价：行动点 {quote['cost_action_points']}｜"
            f"直接财政支出 {quote['direct_budget_cost']} {quote['budget_unit']}"
        )
        if quote.get("resource_ids"):
            self.output("承办资源：" + "、".join(quote["resource_ids"]))
        if quote.get("narrative_preview"):
            self.output("程序说明：" + str(quote["narrative_preview"]))
        if self._select(
            "确认执行该行动？", ["按以上对象、参数与报价执行"], back_label="取消"
        ) is None:
            return
        client_action_id = self.api.new_key("resource")
        result = self.api.execute_resource_action(
            session_id,
            state_version=int(quote["state_version"]),
            action_id=str(item["action_id"]),
            target_ids=targets,
            parameters=parameters,
            quote_id=str(quote["quote_id"]),
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self.output(str(result.get("narrative", "行动已完成。")))
        self._refresh()

    def _request_overtime(self, points: int) -> None:
        client_action_id = self.api.new_key("overtime")
        result = self.api.request_overtime(
            self._require_session(),
            state_version=self._require_version(),
            points=points,
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self.output(str(result.get("narrative", "加班额度已发放。")))
        self._refresh()

    def _talk(
        self, opportunity_id: str, conversation_id: str, player_text: str
    ) -> dict:
        session_id = self._require_session()
        document = self.api.get_opportunities(session_id)
        opportunities = {
            str(item["opportunity_id"]): item
            for item in document.get("opportunities", [])
        }
        opportunity = opportunities.get(opportunity_id)
        if opportunity is None:
            reason = document.get("blocked_reason")
            raise ValueError(str(reason or "当前没有这个互动机会"))
        client_action_id = self.api.new_key("talk")
        self.pending_operation_id = client_action_id
        npc_name = str(opportunity.get("npc_name") or opportunity.get("npc_id") or "角色")
        self.output(f"{npc_name}正在思考，请稍候……")
        try:
            try:
                result = self.api.submit_free_text(
                    session_id,
                    state_version=int(document["state_version"]),
                    opportunity_id=opportunity_id,
                    target_npc_id=str(opportunity["npc_id"]),
                    conversation_id=conversation_id,
                    player_text=player_text,
                    client_action_id=client_action_id,
                )
            except ApiError as exc:
                if exc.code != "CLIENT_TIMEOUT":
                    raise
                self.output(
                    "模型响应时间较长，但本回合已经取得唯一操作编号。"
                    "正在查询原操作结果，请勿重复输入。"
                )
                result = {"status": "processing", "poll_after_ms": 750}
            result = self._await_operation(client_action_id, result)
        except ApiError as exc:
            if exc.code not in {
                "CLIENT_POLL_TIMEOUT", "CLIENT_TIMEOUT", "CLIENT_CONNECTION_ERROR"
            }:
                self.pending_operation_id = None
            raise
        self.pending_operation_id = None
        self.state_version = int(result["state_version"])
        self._refresh()
        return result

    def _command_talk(self, opportunity_id: str, player_text: str) -> None:
        document = self.api.get_opportunities(self._require_session())
        opportunity = next(
            (
                item for item in document.get("opportunities", [])
                if str(item["opportunity_id"]) == opportunity_id
            ),
            None,
        )
        if opportunity is None:
            raise ValueError("当前没有这个互动机会")
        if opportunity.get("conversation_active"):
            conversation_id = str(opportunity["conversation_id"])
        else:
            started = self._start_conversation(opportunity)
            conversation_id = str(started["conversation"]["conversation_id"])
        self._talk(opportunity_id, conversation_id, player_text)

    def _start_conversation(self, opportunity: dict) -> dict:
        client_action_id = self.api.new_key("conversation-start")
        result = self.api.start_conversation(
            self._require_session(),
            state_version=int(self.state_version or 0),
            opportunity_id=str(opportunity["opportunity_id"]),
            target_npc_id=str(opportunity["npc_id"]),
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self._refresh()
        return result

    def _end_conversation(self, conversation_id: str) -> dict:
        client_action_id = self.api.new_key("conversation-end")
        result = self.api.end_conversation(
            self._require_session(),
            state_version=int(self.state_version or 0),
            conversation_id=conversation_id,
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self._refresh()
        return result

    def _knowledge(self) -> None:
        document = self.api.get_knowledge(self._require_session())
        self.state_version = int(document["state_version"])
        values = []
        for key, title in (("facts", "事实"), ("clues", "线索"), ("evidence", "证据")):
            items = document.get(key, [])
            values.append(f"{title}：{len(items)} 项")
            for item in items:
                values.extend((
                    f"  【{item.get('title') or item.get('fact_id') or item}】",
                    f"    内容：{item.get('text') or '暂无正文。'}",
                    f"    来源：{item.get('source_label') or '剧情中已确认'}",
                    f"    可用于：{item.get('use_hint') or '可在后续会谈、调查和决策中引用。'}",
                ))
        self._write_lines(values)
        self.output(
            "查看完毕，返回游戏菜单。" if self.menu_mode else
            "下一步：输入 scene 返回当前剧情；输入 map、actions 或 opportunities 查看其他入口。"
        )

    def _write_related_materials(self, materials: list[dict]) -> None:
        if not materials:
            self.output("当前没有与此人直接关联的已知材料。")
            return
        self.output("本次会谈可参考的材料：")
        for item in materials:
            self._write_lines((
                f"  【{item.get('title') or item.get('material_id') or '材料'}】",
                f"    内容：{item.get('text') or '暂无正文。'}",
                f"    来源：{item.get('source_label') or '县长案头'}",
                f"    可用于：{item.get('use_hint') or '可在会谈中引用。'}",
            ))

    def _menu_desk(self) -> None:
        document = self.api.get_desk(self._require_session())
        self.state_version = int(document["state_version"])
        options = [
            "任务与硬约束", "五份背景卷宗", "补偿政策与财政盘子",
            "当前可调资源", "全部行动工具", "36户公开底表",
            "事实、线索与证据",
        ]
        while True:
            selected = self._select("县长案头", options, back_label="返回游戏菜单")
            if selected is None:
                return
            if selected == 0:
                mission = document["mission"]
                self.output(f"【{mission['title']}】\n{mission['summary']}")
                for item in mission.get("hard_constraints", []):
                    self.output(f"  - {item['label']}：{item['value']}｜{item['detail']}")
            elif selected == 1:
                for item in document.get("dossiers", []):
                    self.output(f"【{item['title']}】\n  {item['summary']}")
                    for point in item.get("known_points", []):
                        self.output(f"  - {point}")
            elif selected == 2:
                policy = document["compensation_policy"]
                budget = policy["current_budget"]
                self.output(f"【{policy['title']}】{policy['status']}")
                self.output(
                    f"当前财政盘：基础授权 {budget['base_authorized']}、"
                    f"有来源调整 {budget['approved_adjustments']}、"
                    f"已承诺 {budget['committed']}、已支出 {budget['paid']}、"
                    f"当前可安排 {budget['remaining']} {budget['unit']}"
                )
                if budget.get("precoord_suspense"):
                    self.output(
                        f"疑点挂账：前期协调费 {budget['precoord_suspense']} {budget['unit']}。"
                    )
                self.output("已确定资金口径：")
                for item in policy.get("funding", []):
                    self.output(f"  - {item['label']}：{item['value']}")
                self.output("公开执行原则：")
                for item in policy.get("principles", []):
                    self.output(f"  - {item}")
                self.output(f"数字边界：{policy['numeric_guardrail']}")
            elif selected == 3:
                for item in document.get("authorities", []):
                    self.output(f"【{item['name']}】{item['description']}\n  边界：{item['limitation']}")
            elif selected == 4:
                categories = {item["name"]: item["description"] for item in document.get("tool_categories", [])}
                current_category = None
                for item in document.get("tools", []):
                    if item["category"] != current_category:
                        current_category = item["category"]
                        self.output(f"\n【{current_category}】{categories.get(current_category, '')}")
                    state = "现在可用" if item.get("available") else f"当前不可用：{item.get('unavailable_reason')}"
                    self.output(
                        f"  - {item['name']}｜消耗 {item['cost_action_points']} 行动点｜{state}\n"
                        f"    作用：{item['description']}\n"
                        f"    条件：{item['availability_note']}"
                    )
            elif selected == 5:
                households = list(document.get("household_registry", []))
                self.output(
                    f"【36户公开底表】共 {len(households)} 户。"
                    "以下是已登记基础量；地类、附属物数量等未给出的明细仍待核验。"
                )
                self.output(
                    "户号中的字母只是代表户群的拼音缩写，横线后的数字是组内序号，"
                    "不表示等级、风险或签约顺序。"
                )
                for item in households:
                    other_land = ""
                    if item.get("other_land_mu"):
                        other_land = f"，其他土地 {item['other_land_mu']:g}亩"
                    self.output(
                        f"  - {item['household_id']}｜签约代表 {item.get('signatory_name', '待核验')}｜"
                        f"户籍 {item['registered_population']} 人｜"
                        f"住宅 {item['legal_residential_area_m2']:g}㎡｜"
                        f"宅基地认定 {item['homestead_recognized_m2']:g}㎡｜"
                        f"承包地 {item['contracted_land_mu']:g}亩{other_land}｜"
                        "权属："
                        + self.OWNERSHIP_STATUS_LABELS.get(
                            str(item["ownership_status"]), "其他待核验状态"
                        )
                    )
            else:
                self._knowledge()

    def _map(self) -> None:
        document = self.api.get_map(self._require_session())
        locations = list(document.get("locations", []))
        if self.menu_mode:
            selected_location = self._select(
                f"地图入口（D{document.get('story_day', '?')}）",
                [
                    f"{item.get('name')}｜{item.get('description')}｜{item.get('visual_state')}"
                    for item in locations
                ],
                back_label="返回游戏菜单",
            )
            if selected_location is None:
                return
            location = locations[selected_location]
            cards = list(location.get("entry_cards", []))
            if not cards:
                self.output("这个地点今天没有可进入的人物、事件或资源行动。")
                return
            selected_card = self._select(
                str(location.get("name", "地点入口")),
                [
                    f"{card.get('title')}｜{card.get('description')}｜"
                    + (
                        f"消耗 {card.get('cost_action_points')} 行动点"
                        if card.get("available") else
                        f"不可用：{card.get('unavailable_reason') or '条件不足'}"
                    )
                    for card in cards
                ],
                back_label="返回地图",
            )
            if selected_card is None:
                return
            card = cards[selected_card]
            if not card.get("available"):
                self.output(str(card.get("unavailable_reason") or "当前入口不可用。"))
                return
            submit = card.get("submit") or {}
            if card.get("entry_type") == "conversation":
                opportunities = self.api.get_opportunities(
                    self._require_session()
                ).get("opportunities", [])
                opportunity = next(
                    (
                        item for item in opportunities
                        if item.get("opportunity_id") == submit.get("opportunity_id")
                    ),
                    None,
                )
                if opportunity is None:
                    self.output("该人物入口刚刚发生变化，请刷新地图后重试。")
                    return
                self._run_conversation(opportunity)
                return
            actions = self.api.get_actions(self._require_session())
            self.state_version = int(actions["state_version"])
            action = next(
                (
                    item for item in actions.get("actions", [])
                    if item.get("action_id") == submit.get("action_id")
                ),
                None,
            )
            if action is None or not action.get("available"):
                self.output("该行动入口刚刚发生变化，请刷新地图后重试。")
                return
            self._run_resource_action(action)
            return
        self.output(f"地图入口（D{document.get('story_day', '?')}）：")
        for item in locations:
            cards = item.get("entry_cards", [])
            self.output(
                f"  {item.get('name')}｜{item.get('visual_state')}｜"
                f"当前入口 {len(cards)} 项"
            )
        self.output(
            "查看完毕，返回游戏菜单。" if self.menu_mode else
            "下一步：输入 opportunities 查看可交谈对象，或 scene 返回当前剧情。"
        )

    def _review(self) -> None:
        document = self.api.get_review(self._require_session())
        self.output(
            f"复盘：决策 {len(document.get('decision_timeline', []))}｜"
            f"行动 {len(document.get('action_timeline', []))}｜"
            f"会谈记录 {len(document.get('conversation_timeline', []))}｜"
            f"夜间 {len(document.get('night_timeline', []))}"
        )
        for item in document.get("decision_timeline", []):
            self.output(
                f"  D{item.get('story_day')} 决策｜{item.get('title')}｜"
                f"选择：{item.get('choice')}"
            )
        for item in document.get("action_timeline", []):
            self.output(
                f"  D{item.get('story_day')} 行动｜{item.get('name')}｜"
                f"行动点 {item.get('cost_action_points', 0)}｜"
                f"财政 {item.get('budget_cost', 0)}"
            )
            if item.get("public_result"):
                self.output(f"    公开结果：{item['public_result']}")
        for item in document.get("known_facts", []):
            self.output(
                f"  材料｜{item.get('title')}｜{item.get('source_label')}\n"
                f"    {item.get('text')}"
            )
        ending = document.get("ending")
        if ending:
            self.output(
                f"结局：{ending.get('main_ending_name')} · "
                f"{ending.get('sub_ending_title')}"
            )
        self.output(
            "查看完毕，返回游戏菜单。" if self.menu_mode else
            "下一步：输入 scene 返回当前剧情；若本局已结束，可输入 new 新开一局。"
        )

    def _validate_package(self) -> None:
        document = self.api.get_package_validation()
        counts = document.get("counts", {})
        self.output(
            f"剧本包校验：{'通过' if document.get('valid') else '失败'}｜"
            f"D{counts.get('story_days')}｜决策 {counts.get('decision_catalog')}｜"
            f"事件 {counts.get('event_catalog')}｜"
            f"运行实例 {counts.get('runtime_decisions')}｜"
            f"结局 {counts.get('main_endings')}/{counts.get('sub_endings')}"
        )
        self.output(
            "查看完毕，返回游戏菜单。" if self.menu_mode else
            "下一步：输入 new 开始新局，或 scene 返回当前游戏。"
        )

    def _continue_story(self) -> None:
        if not self.commands.get("can_continue_story"):
            raise ValueError("当前没有可接续的剧情，请先处理当前互动或刷新现场。")
        client_action_id = self.api.new_key("story")
        result = self.api.continue_story(
            self._require_session(), state_version=self._require_version(),
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self._refresh()

    def _end_day(self) -> None:
        client_action_id = self.api.new_key("end")
        result = self.api.end_day(
            self._require_session(),
            state_version=self._require_version(),
            client_action_id=client_action_id,
        )
        result = self._await_operation(client_action_id, result)
        self.state_version = int(result["state_version"])
        self.output("夜间模拟完成。")
        self._refresh()
        self._show_new_night_dialogues()

    def _show_new_night_dialogues(self, *, force: bool = False) -> None:
        if not self.show_night_dialogues:
            return
        document = self.api.get_night_dialogues(self._require_session())
        shown = False
        for night in document.get("nights", []):
            day = night.get("story_day")
            selection_key = f"D{day}:contacts"
            if force or selection_key not in self.rendered_night_groups:
                selections = night.get("contact_selections", [])
                if selections:
                    shown = True
                    self.output(f"【调试观察｜D{day} 夜间联系人选择】")
                    for item in selections:
                        contacts = item.get("contact_ids", [])
                        self.output(
                            f"  {item.get('npc_id')} [{item.get('model_id')}] → "
                            f"{', '.join(contacts) if contacts else '不主动联系任何人'}"
                        )
                        if item.get("rationale"):
                            self.output(f"    理由：{item['rationale']}")
                self.rendered_night_groups.add(selection_key)
            response_key = f"D{day}:responses"
            if force or response_key not in self.rendered_night_groups:
                responses = night.get("contact_responses", [])
                if responses:
                    shown = True
                    self.output(f"【调试观察｜D{day} 夜间邀请响应】")
                    response_labels = {
                        "accept": "接受",
                        "reject": "拒绝",
                        "defer": "延后",
                    }
                    for item in responses:
                        self.output(
                            f"  {item.get('initiator_npc_id')} → "
                            f"{item.get('invited_npc_id')} "
                            f"[{item.get('model_id')}]："
                            f"{response_labels.get(item.get('response'), '拒绝')}"
                        )
                        if item.get("rationale"):
                            self.output(f"    理由：{item['rationale']}")
                self.rendered_night_groups.add(response_key)
            followup_key = f"D{day}:followups"
            if force or followup_key not in self.rendered_night_groups:
                followups = night.get("followup_decisions", [])
                if followups:
                    shown = True
                    self.output(f"【调试观察｜D{day} 次日会谈发起决定】")
                    for item in followups:
                        label = (
                            "群众上访"
                            if item.get("followup_type") == "petition"
                            else "干部会谈"
                        )
                        self.output(
                            f"  {item.get('initiator_npc_id')} "
                            f"[{item.get('model_id')}]："
                            f"{'发起' if item.get('initiate') else '不发起'}"
                            f"{label}"
                        )
                        if item.get("agenda"):
                            self.output(f"    议题：{item['agenda']}")
                        if item.get("rationale"):
                            self.output(f"    理由：{item['rationale']}")
                self.rendered_night_groups.add(followup_key)
            for exchange in night.get("agent_exchanges", []):
                key = (
                    f"D{day}:{exchange.get('scene_id')}:"
                    f"{exchange.get('group_index', 1)}"
                )
                if not force and key in self.rendered_night_groups:
                    continue
                shown = True
                participants = ", ".join(exchange.get("participant_ids", []))
                self.output(
                    f"【调试观察｜D{day} {exchange.get('scene_id')}｜"
                    f"参与者：{participants}】"
                )
                for turn in exchange.get("transcript", []):
                    self.output(
                        f"  R{turn.get('round')} {turn.get('speaker_name')}"
                        f" [{turn.get('model_id')}]：{turn.get('dialogue')}"
                    )
                for proposal in exchange.get("action_proposals", []):
                    self.output(
                        f"  决策｜{proposal.get('npc_id')} → "
                        f"{proposal.get('action_id')}｜"
                        f"{'通过' if proposal.get('accepted') else '拒绝'}"
                    )
                    if proposal.get("rationale"):
                        self.output(f"    理由：{proposal['rationale']}")
                self.output(
                    "  最终执行："
                    + (
                        ", ".join(exchange.get("executed_action_ids", []))
                        or "无"
                    )
                )
                self.rendered_night_groups.add(key)
        if force and not shown:
            self.output("当前 session 还没有可观看的 NPC 夜间对话。")

    def _run_menu(self) -> int:
        while True:
            try:
                if self.authentication_required and not self.authenticated:
                    if not self._menu_authentication():
                        return 0
                    continue
                if not self.session_id:
                    if not self._menu_session_entry():
                        return 0
                    continue
                if not self.state:
                    self._refresh()
                if not self._menu_game_step():
                    return 0
            except ApiError as exc:
                self.output(f"[后端错误 {exc.code}] {exc.message}")
                if exc.code in {"AUTHENTICATION_REQUIRED", "INVALID_CREDENTIALS"}:
                    self.authenticated = False
                    self.session_id = None
                    self.output("登录状态无效，请在下一页重新登录或注册。")
                elif exc.code == "SESSION_CONTENT_UNAVAILABLE":
                    self._handle_unavailable_session()
                else:
                    self._safe_refresh()
                    if exc.code == "CLIENT_POLL_TIMEOUT":
                        self.output(
                            "原回合仍在服务端处理中；客户端会继续查询同一操作，"
                            "不会重复提交你的发言。"
                        )
                    else:
                        self.output("已刷新服务端权威状态，请按下一页菜单继续。")
            except ValueError as exc:
                self.output(f"[输入错误] {exc}。请按下方菜单重新选择。")

    def _menu_authentication(self) -> bool:
        selected = self._select(
            "账号入口",
            ["登录已有账号", "注册新账号"],
            back_label="退出程序",
        )
        if selected is None:
            return False
        username = self.input("请输入用户名：").strip()
        if not username:
            self.output("用户名不能为空，返回账号入口。")
            return True
        if selected == 0:
            result = self.api.login(username, self.password("请输入密码："))
            self.authenticated = True
            self.output(f"登录成功：{result['account_id']}")
        else:
            result = self.api.register(username, self._read_new_password())
            self.authenticated = True
            self.output(f"注册并登录成功：{result['account_id']}")
        return True

    def _menu_session_entry(self) -> bool:
        if not self.night_dialogue_preference_set:
            selected = self._select(
                "是否观看 NPC 夜间对话",
                ["不观看（正常游玩）", "观看（观察与调试）"],
                back_label="退出程序",
            )
            if selected is None:
                return False
            self.show_night_dialogues = selected == 1
            self.night_dialogue_preference_set = True
            self.output(
                "NPC 夜间对话观察已开启。"
                if self.show_night_dialogues
                else "NPC 夜间对话观察未开启。"
            )
        latest = None
        try:
            latest = self.api.get_latest_active()
        except ApiError as exc:
            if exc.code == "SESSION_CONTENT_UNAVAILABLE":
                self.output(f"[旧存档不可继续] {exc.message}")
                self._handle_unavailable_session()
            elif exc.status != 404 and exc.code != "NOT_FOUND":
                raise
        options: list[tuple[str, str]] = []
        if latest:
            story = latest.get("story", {})
            options.append((
                "continue",
                f"继续活动存档（D{story.get('day', '?')}，{latest.get('session_id')}）",
            ))
        options.extend((
            ("new", "开始新游戏"),
            ("logout", "退出当前账号"),
        ))
        selected = self._select(
            "游戏入口", [label for _, label in options], back_label="退出程序"
        )
        if selected is None:
            return False
        action = options[selected][0]
        if action == "continue":
            self._load(str(latest["session_id"]))
        elif action == "new":
            self._new()
        else:
            self._menu_logout()
        return True

    def _menu_game_step(self) -> bool:
        if self.pending_operation_id:
            self.output("正在确认上一轮会谈结果，请勿再次提交相同发言……")
            self._resume_pending_operation()

        group_conversation = self.state.get("active_group_conversation")
        if group_conversation:
            self._menu_group_conversation(group_conversation)
            return True
        pending = self.state.get("pending_decision")
        if pending:
            self._menu_decision(pending)
            return True
        if self.state.get("status") != "active":
            options = [
                ("review", "查看本局复盘"),
                ("new", "开始新游戏"),
                ("logout", "退出当前账号"),
            ]
            selected = self._select(
                "本局已经结束", [label for _, label in options], back_label="退出程序"
            )
            if selected is None:
                return False
            action = options[selected][0]
            if action == "review":
                self._review()
            elif action == "new":
                self.session_id = None
                self.state = {}
                self._new()
            else:
                self._menu_logout()
            return True

        options: list[tuple[str, str]] = []
        if self.commands.get("can_continue_story"):
            options.append(("next", "继续阅读当日剧情"))
        if self.commands.get("can_talk"):
            active = self.state.get("active_conversation")
            options.append((
                "talk",
                "继续当前 NPC 会谈（调用真实 LLM）"
                if active else "与当前可互动的 NPC 交谈（调用真实 LLM）",
            ))
        if self.commands.get("can_act"):
            options.append(("action", "执行自主行动"))
        if self.commands.get("can_end_day"):
            options.append(("end", "结束当天并执行夜间推进"))
        points = self.state.get("ledger", {}).get("action_points", {})
        if points.get("overtime_available"):
            options.append(("overtime", "申请加班 1–3 点（本章最多三次）"))
        options.extend((
            ("governance", "查看治理、资源与进行中的行动"),
            ("desk", "打开县长案头（任务、政策、资源和材料）"),
            ("knowledge", "查看已掌握的事实、线索和证据"),
            ("map", "查看地图与当前入口"),
            ("review", "查看本局复盘"),
            ("status", "查看当前状态"),
            ("validate", "检查剧本包完整性"),
            ("refresh", "刷新当前剧情"),
            ("logout", "保存并退出当前账号"),
        ))
        if self.show_night_dialogues:
            options.insert(
                next(
                    index
                    for index, item in enumerate(options)
                    if item[0] == "review"
                ),
                ("night_dialogues", "查看 NPC 夜间对话（调试）"),
            )
        selected = self._select(
            "请选择下一步", [label for _, label in options], back_label="退出程序"
        )
        if selected is None:
            return False
        action = options[selected][0]
        if action == "next":
            self._continue_story()
        elif action == "talk":
            self._menu_talk()
        elif action == "action":
            self._menu_action()
        elif action == "end":
            self._end_day()
        elif action == "overtime":
            selected_points = self._select(
                "选择加班额度",
                ["加班 1 点", "加班 2 点", "加班 3 点"],
                back_label="取消",
            )
            if selected_points is not None:
                self._request_overtime(selected_points + 1)
        elif action == "governance":
            self._menu_governance()
        elif action == "desk":
            self._menu_desk()
        elif action == "knowledge":
            self._knowledge()
        elif action == "map":
            self._map()
        elif action == "night_dialogues":
            self._show_new_night_dialogues(force=True)
        elif action == "review":
            self._review()
        elif action == "status":
            self._write_lines(render_state(self.state))
        elif action == "validate":
            self._validate_package()
        elif action == "refresh":
            self._refresh()
        else:
            self._menu_logout()
        return True

    def _menu_group_conversation(self, conversation: dict) -> None:
        type_label = (
            "群众上访"
            if conversation.get("conversation_type") == "petition"
            else "干部会谈"
        )
        phase = str(conversation.get("phase", "active"))
        self.output(f"【强制群组会谈｜{type_label}｜{'等待收起' if phase == 'resolved' else '进行中'}】")
        self.output(f"议题：{conversation.get('agenda')}")
        demands = conversation.get("demands", [])
        if demands:
            self.output("诉求：" + "；".join(str(item) for item in demands))
        self.output(
            "参与NPC：" + "、".join(
                str(item) for item in conversation.get("participant_ids", [])
            )
        )
        self._render_group_conversation_status(conversation)
        if phase == "resolved":
            if self._select(
                "NPC已经停止追问，是否结束并归档本场夜间会谈？",
                ["结束夜间会谈"],
                back_label="继续查看记录",
            ) is None:
                return
            result = self.api.finish_group_conversation(
                self._require_session(),
                state_version=self._require_version(),
            )
            self.state = result["visible_state"]
            self.state_version = int(result["state_version"])
            self.output("夜间会谈已经归档；如有排队会谈将继续显示。")
            return
        response = self.input("请输入你对本轮群组会谈的回应：").strip()
        if not response:
            self.output("强制群组会谈必须作出回应。")
            return
        self._reply_group_conversation(response)

    def _reply_group_conversation(self, player_text: str) -> None:
        result = self.api.reply_group_conversation(
            self._require_session(),
            state_version=self._require_version(),
            player_text=player_text,
        )
        self.state = result["visible_state"]
        self.state_version = int(result["state_version"])
        if result.get("input_rejected"):
            self.output(str(result.get("message", "请输入与本游戏相关的话语")))
            return
        current = self.state.get("active_group_conversation")
        for item in result.get("turn_dialogues", []):
            self.output(
                f"{item.get('npc_name')} [{item.get('model_id')}]："
                f"{item.get('text')}"
            )
        if current:
            self._render_group_conversation_status(current)

    def _render_group_conversation_status(self, conversation: dict) -> None:
        for npc_id, state in dict(
            conversation.get("participant_states", {})
        ).items():
            summary = str(state.get("public_summary", "")).strip()
            status = str(state.get("status", "active"))
            if summary:
                self.output(f"{npc_id}｜{status}｜{summary}")
        closure = str(conversation.get("closure_text", "")).strip()
        if closure:
            self.output(f"结束语：{closure}")

    def _menu_decision(self, pending: dict) -> None:
        kind = pending.get("input_kind", "choice")
        if kind == "sorting":
            remaining = [
                item for item in pending.get("options", []) if item.get("available", True)
            ]
            ordered: list[str] = []
            for position in range(1, len(remaining) + 1):
                selected = self._select(
                    f"请选择第 {position} 优先项",
                    [str(item.get("text", "")) for item in remaining],
                    back_label="取消本次排序",
                )
                if selected is None:
                    return
                item = remaining.pop(selected)
                ordered.append(str(item["option_id"]))
            self._order(ordered)
            return
        if kind == "allocation":
            if self._select("是否开始填写分配额度？", ["开始填写"], back_label="稍后再决定") is None:
                return
            schema = pending.get("input_schema") or {}
            fields = list(schema.get("fields", []))
            labels = schema.get("labels", {})
            total = int(schema.get("total", 0))
            unit = str(schema.get("unit", ""))
            while True:
                values: list[str] = []
                valid = True
                for field in fields:
                    raw = self.input(f"{labels.get(field, field)}（{unit}，请输入非负整数）：").strip()
                    try:
                        value = int(raw)
                        if value < 0:
                            raise ValueError
                    except ValueError:
                        self.output("额度必须是非负整数，本轮分配作废，请重新填写四项。")
                        valid = False
                        break
                    values.append(str(value))
                if not valid:
                    continue
                if sum(int(value) for value in values) != total:
                    self.output(f"四项合计必须等于 {total} {unit}，请重新填写。")
                    continue
                self._allocate(values)
                return
        available = [
            item for item in pending.get("options", []) if item.get("available", True)
        ]
        selected = self._select(
            str(pending.get("title", "请选择")),
            [str(item.get("text", "")) for item in available],
            back_label="暂不选择",
        )
        if selected is not None:
            self._choose(str(available[selected]["option_id"]))

    def _menu_talk(self) -> None:
        document = self.api.get_opportunities(self._require_session())
        opportunities = list(document.get("opportunities", []))
        if not opportunities:
            self.output(str(document.get("blocked_reason") or "当前没有可交谈对象。"))
            return
        selected = self._select(
            "请选择交谈对象",
            [
                (
                    f"{item.get('npc_name') or item.get('npc_id')}｜"
                    f"{item.get('npc_title') or '剧情人物'}｜"
                    + (
                        "会谈进行中，本次继续不再扣行动点\n"
                        if item.get("conversation_active")
                        else f"消耗 {item.get('cost_action_points')} 行动点（进入后不限轮次）\n"
                    )
                    +
                    f"     人物简介：{item.get('npc_introduction') or '暂无公开介绍。'}\n"
                    f"     本次接触：{item.get('conversation_context') or item.get('action_name') or '自由交谈'}\n"
                    f"     前情提要：{item.get('opening_narrative') or '你在当前剧情中获得了与此人交谈的机会。'}\n"
                    f"     会谈方向：{item.get('conversation_goal') or '了解对方当前的真实想法。'}\n"
                    f"     可参考材料：{'; '.join(material.get('title', '材料') for material in item.get('related_materials', [])) or '暂无'}"
                )
                for item in opportunities
            ],
            back_label="返回上一级",
        )
        if selected is None:
            return
        self._run_conversation(opportunities[selected])

    def _run_conversation(self, opportunity: dict) -> None:
        if opportunity.get("conversation_active"):
            conversation_id = str(opportunity["conversation_id"])
        else:
            confirmed = self._select(
                "确认进入会谈",
                ["进入会谈（只在此时扣除行动点，后续交谈不限轮次）"],
                back_label="暂不进入",
            )
            if confirmed is None:
                return
            started = self._start_conversation(opportunity)
            conversation_id = str(started["conversation"]["conversation_id"])

        npc_name = str(opportunity.get("npc_name") or opportunity.get("npc_id"))
        while True:
            selected_action = self._select(
                f"与{npc_name}的会谈",
                ["继续交谈", "查看本次会谈相关材料", "结束本次会谈"],
                back_label="暂时离开终端（会谈仍保持）",
            )
            if selected_action is None:
                return
            if selected_action == 1:
                self._write_related_materials(list(opportunity.get("related_materials", [])))
                continue
            if selected_action == 2:
                self._end_conversation(conversation_id)
                return
            text = self.input("你想说什么（直接回车返回会谈菜单）：").strip()
            if not text:
                self.output("没有提交内容，会谈仍在继续。")
                continue
            result = self._talk(
                str(opportunity["opportunity_id"]), conversation_id, text
            )
            if result.get("conversation", {}).get("status") == "ended":
                self.output(f"{npc_name}已经结束了这次会谈。")
                return

    def _menu_action(self) -> None:
        document = self.api.get_actions(self._require_session())
        self.state_version = int(document["state_version"])
        entries = [
            action for action in document.get("actions", [])
            if action.get("available")
            and action.get("execution_mode") in {"resource_action", "governance"}
        ]
        if not entries:
            self.output("当前没有可执行的治理或资源行动；人物类行动请从“交谈”进入。")
            return

        def action_label(action: dict) -> str:
            cost = action.get("cost", action.get("cost_action_points", 0))
            if action.get("execution_mode") == "governance":
                return f"{action.get('name')}｜消耗 {cost} 行动点｜治理行动"
            return (
                f"{action.get('name')}｜消耗 {cost} 行动点｜"
                f"直接财政支出 {action.get('direct_budget_cost', 0)}"
            )

        selected = self._select(
            "请选择自主行动",
            [action_label(action) for action in entries],
            back_label="返回上一级",
        )
        if selected is not None:
            action = entries[selected]
            if action.get("execution_mode") == "governance":
                self._run_governance_action(action)
            else:
                self._run_resource_action(action)

    def _menu_governance(self) -> None:
        overview = self._show_governance()
        active_actions = [
            item for item in overview.get("governance_actions", [])
            if item.get("status") == "active"
        ]
        if not active_actions:
            return
        selected = self._select(
            "进行中的治理行动",
            [
                f"中止 {item['action_kind']}｜{item.get('topic', '')}｜"
                f"{item['action_instance_id']}"
                for item in active_actions
            ],
            back_label="保留并返回",
        )
        if selected is not None:
            self._cancel_governance(
                str(active_actions[selected]["action_instance_id"])
            )

    def _menu_logout(self) -> None:
        self.api.logout()
        self.authenticated = False
        self.session_id = None
        self.show_night_dialogues = False
        self.night_dialogue_preference_set = False
        self.rendered_night_groups.clear()
        self.pending_operation_id = None
        self.state_version = None
        self.state = {}
        self.commands = {}
        self.output("存档已保留，当前账号已退出。")

    def _select(
        self, title: str, options: list[str], *, back_label: str = "返回上一级"
    ) -> int | None:
        self.output("")
        self.output(f"【{title}】")
        for index, label in enumerate(options, start=1):
            label_lines = label.splitlines() or [""]
            self.output(f"  {index}. {label_lines[0]}")
            for continuation in label_lines[1:]:
                self.output(f"     {continuation.strip()}")
        self.output(f"  0. {back_label}")
        while True:
            raw = self.input("请选择序号：").strip()
            try:
                value = int(raw)
            except ValueError:
                self.output("请输入菜单前的数字序号。")
                continue
            if value == 0:
                return None
            if 1 <= value <= len(options):
                return value - 1
            self.output(f"请输入 0 到 {len(options)} 之间的序号。")

    def _read_new_password(self) -> str:
        while True:
            password = self.password("密码（至少 8 个字符）：")
            if len(password) < 8:
                self.output("密码少于 8 个字符，请重新输入。")
                continue
            if len(password) > 256:
                self.output("密码不能超过 256 个字符，请重新输入。")
                continue
            confirmation = self.password("再次输入密码：")
            if password != confirmation:
                self.output("两次输入的密码不一致，请重新设置。")
                continue
            return password

    def _post_auth_guide(self) -> None:
        try:
            state = self.api.get_latest_active()
        except ApiError as exc:
            if exc.status == 404 or exc.code == "NOT_FOUND":
                if self.menu_mode:
                    self.output("当前账号没有活动存档，请在游戏入口选择“开始新游戏”。")
                else:
                    self.output("当前账号没有活动存档。下一步：输入 new 开始新游戏。")
                return
            self.output("已登录，但暂时无法检查存档。下一步：输入 continue 重试，或 new 新开一局。")
            return
        if self.menu_mode:
            self.output(f"检测到活动存档 {state.get('session_id')}，请在游戏入口选择是否继续。")
        else:
            self.output(
                f"检测到活动存档 {state.get('session_id')}。"
                "下一步：输入 continue 继续；若要另开一局，输入 new。"
            )

    def _command_prompt(self) -> str:
        if self.authentication_required and not self.authenticated:
            return "[未登录｜register/login/help] > "
        if not self.session_id:
            return "[未开始｜new/continue/help] > "
        day = self.state.get("story", {}).get("day", "?")
        pending = self.state.get("pending_decision")
        if pending:
            kind = pending.get("input_kind")
            next_command = "order" if kind == "sorting" else (
                "allocate" if kind == "allocation" else "choose"
            )
            return f"[D{day} 决策｜{next_command}/help] > "
        available = []
        if self.commands.get("can_continue_story"):
            available.append("next")
        if self.commands.get("can_talk"):
            available.append("opportunities")
        if self.commands.get("can_act"):
            available.append("actions")
        if self.commands.get("can_end_day"):
            available.append("end")
        available.extend(("scene", "help"))
        return f"[D{day}｜{'/'.join(available)}] > "

    def _guide_current(self, commands: dict) -> None:
        pending = self.state.get("pending_decision")
        if self.menu_mode:
            if pending:
                self.output("请在下方编号菜单完成当前决策。")
            else:
                self.output("请在下方编号菜单选择下一步。")
            return
        if commands.get("can_choose") and pending:
            input_kind = pending.get("input_kind")
            if input_kind == "sorting":
                self.output("下一步：这是排序决策，请输入 order <完整选项顺序>。")
            elif input_kind == "allocation":
                self.output("下一步：这是分配决策，请输入 allocate <四项整数额度>。")
            else:
                self.output("下一步：输入 choose <字母> 提交当前决策，例如 choose A。")
            return
        choices = []
        if commands.get("can_continue_story"):
            choices.append("next 继续阅读当日剧情")
        if commands.get("can_talk"):
            choices.append("opportunities 查看对象，再用 talk 交谈")
        if commands.get("can_act"):
            choices.append("actions 查看行动，再用 do 执行")
        if commands.get("can_end_day"):
            choices.append("end 结束当天")
        if choices:
            self.output("下一步可选：" + "；".join(choices) + "。")
        else:
            self.output("下一步：输入 scene 刷新剧情；输入 help 查看全部命令。")

    def _safe_refresh(self) -> None:
        if self.session_id:
            try:
                self._refresh()
            except ApiError:
                pass

    def _select_meeting_participants(
        self, people: list[dict], initial_ids: list[str]
    ) -> list[str] | None:
        by_id = {str(item["target_id"]): item for item in people}
        participant_ids = list(dict.fromkeys(
            npc_id for npc_id in initial_ids if npc_id in by_id
        ))
        while True:
            remaining = [
                item for item in people
                if str(item["target_id"]) not in participant_ids
            ]
            if not remaining:
                return participant_ids
            selected_names = "、".join(
                str(by_id[npc_id]["label"]) for npc_id in participant_ids
            ) or "尚未选择"
            selected = self._select(
                f"选择参会人（当前：{selected_names}）",
                [str(item["label"]) for item in remaining],
                back_label="完成选择（至少2人）",
            )
            if selected is None:
                if len(participant_ids) >= 2:
                    return participant_ids
                self.output("班子会议至少需要2名参会人，请继续选择。")
                continue
            participant_ids.append(str(remaining[selected]["target_id"]))

    def _handle_unavailable_session(self) -> None:
        """Detach an incompatible save instead of retrying it forever.

        The server intentionally keeps the package lock strict.  Clearing only
        the client context preserves the old save while allowing a new game to
        be created with the currently published package.
        """
        self.session_id = None
        self.state_version = None
        self.pending_operation_id = None
        self.feed_cursor = 0
        self.rendered_content_ids.clear()
        self.rendered_night_groups.clear()
        self.state = {}
        self.option_labels = {}
        self.commands = {}
        self.output(
            "该存档由另一版剧本创建，不能安全套用当前内容；旧存档仍会保留。"
            "请在游戏入口选择“开始新游戏”。"
        )

    def _resume_pending_operation(self) -> dict:
        client_action_id = self.pending_operation_id
        if not client_action_id:
            raise ValueError("当前没有待确认的服务端操作")
        result = self._await_operation(
            client_action_id,
            {"status": "processing", "poll_after_ms": 1000},
        )
        self.pending_operation_id = None
        self.state_version = int(result["state_version"])
        self._refresh()
        return result

    def _await_operation(self, client_action_id: str, result: dict) -> dict:
        if result.get("status") != "processing":
            return result
        session_id = self._require_session()
        wait_seconds = min(2.0, max(0.05, result.get("poll_after_ms", 500) / 1000))
        self.output("操作处理中，正在等待服务端提交……")
        # The backend can spend up to roughly 90 seconds on three 30-second
        # provider attempts.  Polling for two minutes keeps the same idempotency
        # key alive instead of inviting the player to submit the turn again.
        max_polls = max(1, int(120 / wait_seconds))
        for _ in range(max_polls):
            self.sleep(wait_seconds)
            operation = self.api.get_operation(session_id, client_action_id)
            status = operation.get("status")
            if status == "succeeded" and isinstance(operation.get("response"), dict):
                return operation["response"]
            if status in {"failed_retryable", "failed_final"}:
                error = operation.get("error") or {}
                raise ApiError(
                    str(error.get("message") or "服务端操作失败"),
                    code=str(error.get("code") or "OPERATION_FAILED"),
                    status=error.get("http_status"),
                    details=(
                        error.get("details")
                        if isinstance(error.get("details"), dict)
                        else {}
                    ),
                )
        raise ApiError("服务端操作仍在处理中，请稍后刷新", code="CLIENT_POLL_TIMEOUT")

    def _require_session(self) -> str:
        if not self.session_id:
            raise ValueError("尚未载入游戏；请先输入 new 或 load <session_id>")
        return self.session_id

    def _require_version(self) -> int:
        if self.state_version is None:
            raise ValueError("尚未取得状态版本；请先输入 scene")
        return self.state_version

    def _write_lines(self, lines: list[str]) -> None:
        for line in lines:
            self.output(line)
