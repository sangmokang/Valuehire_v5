"""guards/discord-bot-send.py — H1: fleet 잡 실행 중 제안·메일 발송 차단 (AC-3, G3 2층).

SOT28: 봇 경유 잡은 발송(Send)을 자동으로 누르지 않는다. 1층은 잡 프롬프트의 발송 금지
규칙(fleet_worker 규칙 18)과 SOT28 게이트 — 이 훅은 2층으로, fleet 잡 컨텍스트
(env VH_BUSY_TASK)에서 발송성 도구 호출·발송성 셸 명령을 차단한다.

정직 표기: 브라우저 좌표 클릭의 '의도'는 훅이 판정할 수 없다(그 경로는 runner-lease
가드 + 잡 프롬프트 1층이 맡는다). 이 훅은 이름/명령 문자열로 식별 가능한 발송 경로만
좁힌다 — 완전 차단 장치가 아니라 주요 경로 좁히기다(SOT-30 R3 과 동일 원칙).
"""
import os
import re

NAME = "discord-bot-send"

# 이름만으로 발송이 명백한 도구(현재 및 장래 대비 패턴).
_SEND_TOOL_RE = re.compile(r"(gmail|mail|inmail|offer|proposal).{0,20}send|send.{0,20}(mail|inmail|offer|proposal)", re.I)
# 발송성 셸 명령 신호 — 정식 발송 러너/플래그·메일 CLI·SMTP 원라이너.
_SEND_BASH_RE = re.compile(
    r"(--send\b|\bsendmail\b|\bsmtplib\b|smtp\.(send_message|sendmail)"
    r"|send_inmail|send_offer|offer_send|proposal_send"
    r"|users\.messages\.send|messages/send)",
    re.I,
)
# 예외: 발송이 아닌 이름 충돌 (에이전트 간 메시지, draft 생성 등)
_SAFE_TOOLS = frozenset({"SendMessage"})


def _in_fleet_job() -> bool:
    return bool((os.environ.get("VH_BUSY_TASK") or "").strip())


def check(tool, tool_input):
    if not _in_fleet_job():
        return None
    if tool in _SAFE_TOOLS:
        return None
    if _SEND_TOOL_RE.search(tool or ""):
        return (
            "⛔ 차단(discord-bot-send): fleet 잡 안에서는 제안·메일 발송 도구를 호출할 수 "
            "없습니다(SOT28 — 발송은 게이트 통과 건 또는 사장님 수동). 초안(draft)까지만 "
            "만들고 발송은 하지 마세요(G3, goal §7)."
        )
    if tool == "Bash":
        cmd = str((tool_input or {}).get("command") or "")
        if _SEND_BASH_RE.search(cmd):
            return (
                "⛔ 차단(discord-bot-send): fleet 잡 안에서 발송성 명령이 감지됐습니다"
                "(SOT28). 초안 생성까지만 허용 — Send/발송 실행은 금지입니다(G3)."
            )
    return None
