"""Restore the author's repeat, concrete questioning path (source 4783-4789)."""
from serious_game_backend.domain.gameplay_governance import ArchiveRecord
import re

LUO_COPY_ID = "archive_luo_compensation_copy"
COPY_INQUIRY_WORDS = ("箱子", "留底", "复印件", "底稿", "副本")


def is_copy_inquiry(player_text):
    text = player_text or ""
    if not any(word in text for word in COPY_INQUIRY_WORDS):
        return False
    # Cancelling, postponing or forbidding an inquiry remains a non-inquiry even
    # when softened with 好吗/行吗 and regardless of which side the material is on.
    if re.search(r"(?:不(?:想|愿|再|必|用|需要|要|打算)?(?:问|谈|讨论|说|提|看|查|找|拿|出示|提供|给|交|核对|追问)|别(?:再)?(?:问|谈|说|提|看|查|找|拿|出示|提供|给|交|核对)|不用|不要|无需|暂缓|暂不|先不|下次再|以后再|改天再|回头再|不着急)", text):
        return False
    if not any(cue in text for cue in ("为什么", "为何", "哪里", "在哪", "吗", "有没有", "是否", "请问",
            "想问", "能否", "可否", "能不能", "请把", "请出示", "请核对", "我问", "给我看", "谁", "哪儿")):
        return False
    copy_named = any(word in text for word in COPY_INQUIRY_WORDS[1:])
    if copy_named:
        # A copy's price/colour is not a request about preservation or evidence.
        return bool(re.search(r"(?:留(?:着|存|下|了|有)|保管|保存|来源|哪里|哪儿|在哪|出示|给我|交给|核对|有没有|是否有|还有|还在|有.{0,6}(?:留底|复印件|底稿|副本))", text))
    # The author's precise box-preservation question is meaningful in this scene;
    # unrelated questions about the price/location of any box are not.
    return bool(re.fullmatch(r"(?:请问|我想问)?(?:你)?(?:为什么|为何).{0,4}(?:留着|留存|保留|保存).{0,5}箱子[？?吗呢。]*", text.strip()))


def luo_copy_context(session, npc_id, player_text):
    if npc_id != "npc_luo_jian" or session.package_id != "pkg_gameplay_v3":
        return {}
    previous_inquiry = any(log.get("type") == "luo_material_inquiry" for log in session.logs)
    concrete = is_copy_inquiry(player_text)
    can_confirm = (32 <= session.game_state.story_day <= 45 and "见过原件" in session.flags
                   and previous_inquiry and concrete)
    return {"original_checked": "见过原件" in session.flags,
            "copy_confirmed": "罗健留底" in session.flags, "confirm_copy_this_turn": can_confirm,
            "interpretation": ("玩家已核对原件并再次具体追问经手材料，本次可按既定剧情确认家中留有复印件。"
                               "系统登记的是留底确认记录，不能声称已搬走原件或收到其他环境、血铅材料。"
                               if can_confirm else "只答具体问到的补偿材料；未核对原件或尚未具体追问时，不主动泄露留底。")}


def record_luo_copy_inquiry(session, npc_id, player_text, event_id):
    if (npc_id != "npc_luo_jian" or session.package_id != "pkg_gameplay_v3"
            or not is_copy_inquiry(player_text)):
        return False
    if any(log.get("type") == "luo_material_inquiry" and log.get("event_id") == event_id for log in session.logs):
        return False
    context = luo_copy_context(session, npc_id, player_text)
    session.logs.append({"type": "luo_material_inquiry", "event_id": event_id,
                         "story_day": session.game_state.story_day, "visible_to_player": False})
    if not context.get("confirm_copy_this_turn") or "罗健留底" in session.flags:
        return False
    session.flags.add("罗健留底")
    session.archive_records[LUO_COPY_ID] = ArchiveRecord(
        archive_id=LUO_COPY_ID, title="罗健补偿明细留底确认记录", category="户籍与签约",
        content="你核对过柳林村补偿明细原件，并再次具体询问经手材料。罗健确认家中留有一份复印件。"
                "这份记录确认留底的存在与来源，不表示原件已经移交，也不是环评或儿童检测名册。",
        source_type="interaction", source_id=event_id, acquired_day=session.game_state.story_day,
        acquired_via="罗健具体质证", evidence_level="E2", confidentiality="内部",
        read_at_days=[session.game_state.story_day], related_npc_ids=("npc_luo_jian", "npc_zhang_li", "npc_zhao_jianguo"))
    session.append_narrative(story_day=session.game_state.story_day, kind="action_result",
        text="经原件核对和具体追问，罗健的补偿明细留底已登记。可在档案中查看确认记录。",
        content_instance_id=f"material:{LUO_COPY_ID}")
    return True
