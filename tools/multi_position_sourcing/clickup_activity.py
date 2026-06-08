from __future__ import annotations

from .models import PositionMatch


def _bullet_lines(items: tuple[str, ...], *, empty: str) -> str:
    if not items:
        return f"- {empty}"
    return "\n".join(f"- {item}" for item in items)


def format_clickup_activity_comment(match: PositionMatch) -> str:
    """Format one AI Search result for a ClickUp Activity/comment entry.

    Required by the multisearch workflow: Profile URL, score, why-fit, and profile
    summary must always be visible together so reviewers do not need to open the
    artifact just to understand the recommendation.
    """
    evidence = _bullet_lines(match.evidence_paths, empty="근거 경로 없음 — 저장 전 확인 필요")
    why_fit = _bullet_lines(match.why_fit, empty="적합 사유 없음 — 점수 확정 전 확인 필요")
    why_not = _bullet_lines(match.why_not, empty="큰 리스크 미기재")
    return (
        "[AI Search / Multisearch 후보 결과]\n"
        f"Profile URL: {match.candidate_url}\n"
        f"점수: {match.score}/100\n"
        f"대상 포지션 ID: {match.position_id}\n"
        "후보자 프로필 요약:\n"
        f"{match.profile_summary}\n\n"
        "왜 잘 맞는지:\n"
        f"{why_fit}\n\n"
        "리스크/확인 필요:\n"
        f"{why_not}\n\n"
        "근거:\n"
        f"{evidence}"
    )
