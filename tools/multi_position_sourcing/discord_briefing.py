from __future__ import annotations

from .models import PositionMatch


def _bullet_lines(items: tuple[str, ...], *, empty: str) -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def format_discord_candidate_briefing(match: PositionMatch) -> str:
    """Format one multisearch candidate for a Discord briefing.

    Discord summaries must be self-contained. Reviewers should see the profile URL,
    score, candidate summary, fit reasons, and mismatch risks without opening a
    ClickUp Activity or raw artifact first.
    """
    why_fit = _bullet_lines(match.why_fit, empty="적합 사유 없음 — 후보 재검토 필요")
    why_not = _bullet_lines(match.why_not, empty="뚜렷한 불일치 사유 없음")
    evidence = _bullet_lines(match.evidence_paths, empty="근거 경로 없음 — 저장 전 확인 필요")
    return (
        "[Multisearch 후보 브리핑]\n"
        f"Profile URL: {match.candidate_url}\n"
        f"점수: {match.score}/100\n"
        f"대상 포지션 ID: {match.position_id}\n"
        "후보자 요약:\n"
        f"{match.profile_summary}\n\n"
        "잘 맞는 이유:\n"
        f"{why_fit}\n\n"
        "안 맞는 이유:\n"
        f"{why_not}\n\n"
        "근거:\n"
        f"{evidence}"
    )
