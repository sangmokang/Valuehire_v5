"""guards/discord-bot-skill-whitelist.py — H3: fleet 잡 안 스킬 화이트리스트 (AC-3, G2 2층).

fleet 잡 컨텍스트(워커가 주입하는 env VH_BUSY_TASK — fleet_worker._busy_badge_env)에서
허용 목록 밖 스킬 발동을 차단한다. 1층은 큐 입구(new_job_payload/QUEUE_SKILLS)와
게이트웨이 화이트리스트 — 이 훅은 2층(fail-open 전제, goal §9)이다.

정직 표기: 훅은 로드 실패 시 통과(fail-open)라 보안의 최종 방어선이 아니다.
"""
import os

NAME = "discord-bot-skill-whitelist"

# 허용 = 큐 화이트리스트 3종 + login(로그인 준비 스킬 — G4 영수증 갱신 경로).
_ALLOWED_SKILLS = frozenset({"humansearch", "aisearch", "url", "login", "jdintake"})


def _in_fleet_job() -> bool:
    return bool((os.environ.get("VH_BUSY_TASK") or "").strip())


def check(tool, tool_input):
    if tool != "Skill" or not _in_fleet_job():
        return None
    skill = str((tool_input or {}).get("skill") or "").strip()
    # plugin 접두사(codex:rescue 등)는 전체 이름으로 비교 — 접두사 우회 불가.
    if skill and skill not in _ALLOWED_SKILLS:
        return (
            f"⛔ 차단(discord-bot-skill-whitelist): fleet 잡 안에서는 허용 스킬"
            f"({', '.join(sorted(_ALLOWED_SKILLS))})만 발동할 수 있습니다 — "
            f"'{skill}' 은 목록 밖입니다(G2, goal §7)."
        )
    return None
