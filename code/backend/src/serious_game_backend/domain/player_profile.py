"""Fixed player identities and cosmetic signing milestones."""
from __future__ import annotations

SIGNING_MILESTONES = (1, 3, 10, 18, 30, 36)
SIGNING_REWARD_TITLES = {
    1: "新官上任试试水~",
    3: "新手村毕业",
    10: "先天签约圣体",
    18: "优势即将在我",
    30: "来都来了，再签六户",
    36: "县长so easy！",
}


def player_profile(session) -> dict:
    female = getattr(session, "player_gender", "male") == "female"
    return {
        "gender": "female" if female else "male",
        "name": "李琳" if female else "李致远",
        "character_id": "player_li_lin" if female else "player_li_zhiyuan",
        "role": "云溪县县长、县委副书记",
        "portrait_path": "/characters/player_li_lin.png" if female else "/characters/player_li_zhiyuan.png",
    }


def player_identity(session) -> str:
    profile = player_profile(session)
    return f"云溪县县长{profile['name']}（{'女' if profile['gender'] == 'female' else '男'}）"


def player_display_text(session, text: str | None) -> str | None:
    # Presentation only: never rewrite package source, identifiers, or hashes.
    if text is not None and getattr(session, "player_gender", "male") == "female":
        return text.replace("李致远", "李琳")
    return text


def signing_rewards(session) -> list[dict]:
    signed = session.audited_signed_households()
    return [{
        "reward_id": f"signing_{threshold}",
        "threshold": threshold,
        "title": SIGNING_REWARD_TITLES[threshold],
        "earned": signed >= threshold,
        "acknowledged": str(threshold) in session.signing_reward_receipts,
        "received_day": session.signing_reward_receipts.get(str(threshold), {}).get("received_day"),
    } for threshold in SIGNING_MILESTONES]
