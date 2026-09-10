from __future__ import annotations

from dataclasses import replace
from serious_game_backend.application.ending_prose import revise_ending_prose

from serious_game_backend.domain.enums import SessionStatus
from serious_game_backend.domain.errors import ContentValidationError
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.script_package import ScriptPackage


# Shared by runtime selection and editorial exports. Selection priority stays below.
ROSTER_APPENDIX_TEXTS = {
    "未获取": "名册原件没有到你手里；此前见过的检测结果和已有记录，仍须按各自来源追查。",
    "己方封存": "名册原件封存在己方，纸上的名字和检测记录仍待逐项跟进。",
    "呈交上级": "名册原件进了上级机关，纸已经不在你手里。",
    "交给记者": "名册原件到了陈默手里；材料的交付已经记下，是否见报还要看报道的后续。",
    "被销毁": "原始名册被销毁，原件已无法翻查；已经知道的检测结果不会随纸张消失。",
}
IRON_APPENDIX_TEXTS = {
    "账目揭发": "铁盒里的账被完整揭发，成为证据链的一环。",
    "铁盒封存": "己方尚存的铁盒材料被封存归档，账还在，封条也还在；已移交的原件仍由接收单位保管，不因这次封存改变去向。",
    "收受贿赂": "铁盒最后成了别人手里锁住你的把柄。",
    "未入卷": "那只铁盒是否作为实物入卷，还要核对接收记录。县里后续处置只涉及己方尚存材料，已移交的原件仍由接收单位保管。",
}
ROPE_APPENDIX_TEXTS = {
    "暴力驱逐": "暴力驱逐留下的伤害没有随着验收结束。被带离现场的人，仍在等一个交代。",
    "失信": "那些没有接住的诉求留在村民心里。受损的信任，不会因报表归档而回来。",
    "未激化": "在这条冲突记录里，没有留下暴力驱逐或上访升级的结案标记；平静本身并不等于每一项诉求都已解决。",
}


class EndingAxisProjector:
    POSITIVE_PEOPLE_FLAGS = {
        "flag_wu_alliance",
        "flag_vulnerable_household_helped",
        "flag_model_signing",
        "flag_last_mile_success",
        "flag_extra_compensation",
        "flag_shell_truthfully_reported",
        "flag_blood_lead_remediated",
        "flag_listened_to_grievances",
        "flag_livelihood_first",
        "吴秀英同盟", "困难户帮扶", "样板签约", "最后一公里攻坚成功",
        "额外补偿", "毛坯据实", "血铅补实", "俯身接怨", "民生优先",
    }
    NEGATIVE_PEOPLE_FLAGS = {
        "flag_wu_disappointed",
        "flag_petition_escalated",
        "flag_false_signing",
        "flag_coercion",
        "flag_model_padding",
        "flag_face_first",
        "flag_media_suppressed",
        "flag_clan_opposition",
        "秀英寒心", "越级上访", "虚假签约", "强制施压", "样板充数",
        "面子优先", "压制媒体", "宗族对立",
    }
    HEAVY_PEOPLE_FLAGS = {
        "flag_violent_eviction", "flag_grave_conflict", "暴力驱逐", "掘坟结怨"
    }

    def project(self, session: GameSession) -> dict[str, str]:
        flags = session.flags
        signed = session.audited_signed_households()
        if signed != session.game_state.signed_households:
            raise ContentValidationError(
                "D90真实签约总数与分批台账不一致",
                details={
                    "aggregate": session.game_state.signed_households,
                    "audited": signed,
                },
            )
        if signed <= 27:
            axis_a = "溃败"
        elif signed <= 29:
            axis_a = "差一两户"
        elif signed <= 31:
            axis_a = "压线"
        elif signed <= 33:
            axis_a = "宽裕"
        else:
            axis_a = "全额"

        axis_c = self._first(flags, (
            (("flag_accounts_exposed", "账目揭发"), "端掉"),
            (("flag_sacrifice_zhao", "牺牲赵建国"), "弃车保帅"),
            (("flag_bribe_accepted", "flag_truth_concealed", "收受贿赂", "掩盖真相"), "捂住"),
        ), "未触碰")
        dirty = {
            "flag_bribe_accepted", "flag_qian_secret_deal", "收受贿赂", "钱伟密约"
        } & flags
        exposed = {
            "旧账已交巡察组", "两百万已移交立案", "压视频", "谭老六被强压"
        } & flags
        if {"flag_player_fallen", "玩家落马"} & flags or (dirty and exposed):
            axis_d = "入局败露"
        elif dirty:
            axis_d = "入局未败露"
        else:
            axis_d = "干净"
        if {"flag_eia_remediated", "环评已处理"} & flags:
            axis_t = "揭而已治"
        elif {"flag_eia_exposed", "环评揭穿"} & flags:
            axis_t = "揭而未治"
        elif (
            {"flag_eia_concealed", "环评被掩盖"} & flags
            or {"flag_blood_lead_known", "flag_eia_cross_checked", "掌握血铅", "环评存疑·交叉印证"} & flags
        ):
            axis_t = "知而捂"
        else:
            axis_t = "无知"
        axis_m = self._first(flags, (
            (("flag_violent_eviction", "暴力驱逐"), "暴力"),
            (("flag_coercion", "flag_grave_conflict", "强制施压", "掘坟结怨"), "施压"),
        ), "温和")
        axis_x = (
            "假"
            if {
                "flag_false_signing",
                "flag_model_padding",
                "flag_two_million_smoothed",
                "flag_ledger_smoothed",
                "虚假签约", "样板充数", "两百万抹平", "台账做平",
            } & flags
            else "实"
        )
        axis_r = self._first(flags, (
            (("flag_truth_report", "据实以告"), "据实以告"),
            (("flag_full_whitewash", "全面粉饰"), "全面粉饰"),
            (("flag_collusion_line", "串供口径"), "串供口径"),
            (("flag_conceal_report", "瞒报"), "瞒报"),
        ), "瞒报")
        people_score = (
            len(self.POSITIVE_PEOPLE_FLAGS & flags)
            - len(self.NEGATIVE_PEOPLE_FLAGS & flags)
            - 2 * len(self.HEAVY_PEOPLE_FLAGS & flags)
        )
        if people_score >= 5:
            axis_p = "归心"
        elif people_score >= 1:
            axis_p = "认可"
        elif people_score >= -2:
            axis_p = "疏离"
        else:
            axis_p = "离散"
        if self.HEAVY_PEOPLE_FLAGS & flags and axis_p in {"归心", "认可"}:
            axis_p = "疏离"
        axis_f = self._first(flags, (
            (("flag_self_reflection", "反躬自省"), "揽责"),
            (("flag_claim_credit", "居功避重"), "居功"),
            (("flag_truthful_achievement", "如实陈绩"), "中立"),
        ), "中立")
        axis_z = self._first(flags, (
            (("flag_grave_conflict", "掘坟结怨"), "掘坟结怨"),
            (("flag_clan_opposition", "宗族对立"), "对立"),
            (("flag_zhou_aligned", "周大山归心"), "归附"),
        ), "中立")
        axis_j = self._first(flags, (
            (("flag_two_million_case_filed", "两百万已移交立案"), "立案"),
            (("flag_old_accounts_to_inspection", "旧账已交巡察组"), "警觉"),
        ), "未起疑")
        axis_k = self._first(flags, (
            (("flag_team_grudge", "班子结怨"), "结怨"),
            (("flag_team_support", "班子拥护"), "拥护"),
            (("flag_team_detached", "班子离心"), "离心"),
        ), "离心")
        axis_e = self._first(flags, (
            (("flag_media_suppressed", "压制媒体"), "被压制"),
            (("flag_reporter_alliance", "记者结盟"), "结盟发稿"),
        ), "未接触")
        axis_v = self._first(flags, (
            (("flag_jiang_veto", "蒋崇岳否决"), "否决"),
            (("flag_jiang_abandons", "蒋崇岳弃保"), "弃保"),
            (("flag_jiang_endorses", "蒋崇岳背书"), "背书"),
            (("flag_jiang_acquiesces", "蒋崇岳默许"), "默许"),
        ), "默许")
        return {
            "A": axis_a,
            "C": axis_c,
            "D": axis_d,
            "T": axis_t,
            "M": axis_m,
            "X": axis_x,
            "R": axis_r,
            "P": axis_p,
            "F": axis_f,
            "Z": axis_z,
            "J": axis_j,
            "K": axis_k,
            "E": axis_e,
            "V": axis_v,
        }

    @staticmethod
    def _first(flags: set[str], rules: tuple, default: str) -> str:
        for required, value in rules:
            values = {required} if isinstance(required, str) else set(required)
            if values & flags:
                return value
        return default


class EndingService:
    def __init__(self, axes: EndingAxisProjector) -> None:
        self._axes = axes

    def finalize(self, session: GameSession, package: ScriptPackage) -> dict:
        if session.ending_result is not None:
            return self.project_result(session)
        session.game_state = replace(session.game_state, days_left=0)
        signed = session.audited_signed_households()
        if signed != session.game_state.signed_households:
            raise ContentValidationError(
                "D90验收拒绝不一致的签约台账",
                details={
                    "aggregate": session.game_state.signed_households,
                    "audited": signed,
                },
            )
        if signed >= 30:
            session.flags.add("最后一公里攻坚成功")
        axes = self._axes.project(session)
        main = next(
            (
                item
                for item in sorted(package.main_endings, key=lambda value: value.order)
                if self._matches(item.condition, axes, session.flags)
            ),
            None,
        )
        if main is None:
            raise ContentValidationError("主结局表没有命中且缺少恒真兜底")
        axis_value = axes[main.free_axis]
        sub = next(
            (
                item
                for item in package.sub_endings
                if item.main_ending_id == main.ending_id
                and item.axis_value == axis_value
            ),
            None,
        )
        if sub is None:
            raise ContentValidationError(
                f"主结局 {main.ending_id} 缺少自由轴 {axis_value} 的亚结局"
            )
        rendered_sub_text = self._render_sub_text(
            sub.text, signed
        )
        rendered_main_text = self._render_sub_text(main.text, signed)
        result = {
            "signed_households": signed,
            "total_households": 36,
            "target_signed_households": 30,
            "main_ending_id": main.ending_id,
            "main_ending_name": main.name,
            "tone": main.tone,
            "sub_ending_id": sub.sub_ending_id,
            "sub_ending_title": sub.title,
            "main_text": rendered_main_text,
            "sub_text": rendered_sub_text,
            "axes": axes,
            "appendices": self._appendices(session, package),
            "governance_obligations": self._governance_obligations(session),
        }
        session.ending_result = result
        session.status = SessionStatus.ENDED
        session.logs.append({
            "type": "ending_resolved",
            "story_day": 90,
            "main_ending_id": main.ending_id,
            "sub_ending_id": sub.sub_ending_id,
            "visible_to_player": True,
        })
        session.append_narrative(
            story_day=90,
            kind="ending",
            text=f"余波：{sub.title}\n\n{rendered_main_text}\n\n{rendered_sub_text}",
            content_instance_id="ending:final",
        )
        return result

    @staticmethod
    def project_result(session: GameSession) -> dict | None:
        """Enrich old results on reads without reselecting endings or changing the save."""
        if session.ending_result is None:
            return None
        signed = session.audited_signed_households()
        result = dict(session.ending_result)
        result.update(
            signed_households=signed,
            total_households=36,
            target_signed_households=30,
        )
        for key in ("main_text", "sub_text"):
            if isinstance(result.get(key), str):
                result[key] = EndingService._render_sub_text(result[key], signed)
        return result

    @staticmethod
    def _governance_obligations(session: GameSession) -> dict:
        signed = [c for c in session.household_contracts.values() if c.status == "signed"]
        return {
            "signed_contracts": len(signed),
            "allocated_contracts": sum(bool(c.fulfillment.get("resources_allocated")) for c in signed),
            "assessment": "按实际签署合同与剧情结果记录；资源分配不代表搬迁、治疗等后续事项已经完成",
        }

    @staticmethod
    def _render_sub_text(text: str, signed_households: int) -> str:
        """Render actual ledger counts; editorial bands and target rules stay unchanged."""
        count = f"{signed_households}/36 户"
        replacements = {
            "台账停在 27/36 户以下": f"台账最终签到了 {count}",
            "台账没有超过 27/36 户": f"台账最终签到了 {count}",
            "台账还是没过 27/36 户": f"台账最终签到了 {count}",
            "台账已经落在 32—33/36 户这一档": f"台账已经签到了 {count}",
            "台账落在 32—33/36 户这一档": f"台账签到了 {count}",
            "台账进入 34—36/36 户这一档，离满盘已经很近": f"台账签到了 {count}，进入全额档",
            "台账已经过了 32/36 户": f"台账已经签到了 {count}",
            "台账过了 32/36 户": f"台账签到了 {count}",
            "台账过了 34/36 户": f"台账签到了 {count}",
            "台账最终停在 29/36 户，离三十户差一个门牌号": f"台账最终签到了 {count}，离三十户还差 {max(0, 30 - signed_households)} 户",
            "台账停在 29/36 户": f"台账签到了 {count}",
            "台账走到 29/36 户": f"台账签到了 {count}",
            "硬是啃到 29/36 户": f"硬是争取到 {count}",
            "追到 29/36 户": f"争取到 {count}",
            "你从别处凑到 29/36 户": f"你从别处争取到 {count}",
            "三十六户全签下来了": f"台账签到了 {count}",
            "34/36 户以上，一个不落地清完了": f"台账签到了 {count}，已经进入全额档",
            "三十六户全签了，一户不差": f"台账签到了 {count}，已经进入全额档",
            "三十户是够了": f"{count}，目标线是够了",
            "三十户签下来了": f"{count} 签下来了",
            "三十户，": f"{count}，",
            "三十户以上签了字": f"{count} 签了字",
            "三十户以上，压线": f"{count}，达线",
        }
        for source, replacement in replacements.items():
            text = text.replace(source, replacement)
        return revise_ending_prose(text)

    @staticmethod
    def _appendices(session: GameSession, package: ScriptPackage) -> list[dict]:
        roster_text = ROSTER_APPENDIX_TEXTS[session.state_values.get("lead_roster_disposition", "未获取")]
        if "账目揭发" in session.flags:
            iron_text = IRON_APPENDIX_TEXTS["账目揭发"]
        elif "铁盒封存" in session.flags:
            iron_text = IRON_APPENDIX_TEXTS["铁盒封存"]
        elif "收受贿赂" in session.flags:
            iron_text = IRON_APPENDIX_TEXTS["收受贿赂"]
        else:
            iron_text = IRON_APPENDIX_TEXTS["未入卷"]
        if "暴力驱逐" in session.flags:
            rope_text = ROPE_APPENDIX_TEXTS["暴力驱逐"]
        elif "秀英寒心" in session.flags or "越级上访" in session.flags:
            rope_text = ROPE_APPENDIX_TEXTS["失信"]
        else:
            rope_text = ROPE_APPENDIX_TEXTS["未激化"]
        values = {
            "lead_roster_disposition": roster_text,
            "iron_box_flags": iron_text,
            "coercion_flags": rope_text,
        }
        return [
            {
                "appendix_id": item.appendix_id,
                "title": item.title,
                "text": values[item.source],
            }
            for item in package.ending_appendices
        ]

    def _matches(self, condition: dict, axes: dict, flags: set[str]) -> bool:
        if condition.get("always") is True:
            return True
        if "axis" in condition:
            return all(axes.get(key) == value for key, value in condition["axis"].items())
        if "axis_in" in condition:
            return all(
                axes.get(key) in values
                for key, values in condition["axis_in"].items()
            )
        if "flag" in condition:
            return condition["flag"] in flags
        if "all" in condition:
            return all(self._matches(item, axes, flags) for item in condition["all"])
        if "any" in condition:
            return any(self._matches(item, axes, flags) for item in condition["any"])
        if "not" in condition:
            return not self._matches(condition["not"], axes, flags)
        raise ContentValidationError("结局条件 DSL 非法", details={"condition": condition})
