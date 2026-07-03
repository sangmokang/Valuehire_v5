"""humansearch 후보 → Supabase 적재 (2026-07-03 사장님 지시).

사장님 계약:
 1. profile_archives  — 레쥬메 전문(text_content) + profile url. url 무효/본문 공허 = 적재 거부.
 2. sourcing_results  — 포지션별 profile url(value)·학력(education_summary)·경력(career_summary)·
    점수(match_score)·왜 잘 맞는지(fit_reason).

이 모듈은 *매핑(순수 함수)* 만 담아 기계 검증 대상으로 고정한다. HTTP 적재는
scripts/humansearch_supabase_backfill.py 가 수행(REST upsert, 중복은 url+position 조회 후 스킵).
"""
from __future__ import annotations

import json
from typing import Any

from .humansearch import is_valid_profile_url


def _briefing(local: dict[str, Any]) -> dict[str, Any]:
    try:
        b = json.loads(local.get("candidate_briefing") or "{}")
        return b if isinstance(b, dict) else {}
    except (ValueError, TypeError):
        return {}


def to_profile_archive_row(local: dict[str, Any]) -> dict[str, Any] | None:
    """로컬 후보 1행 → profile_archives 페이로드. url·본문 없으면 None(fail-closed)."""
    url = local.get("url")
    text = (local.get("raw_text") or "").strip()
    if not is_valid_profile_url(url) or not text:
        return None
    shot = local.get("screenshot_path") or ""
    # captured_at 은 NOT NULL — 로컬 수집시각(created_at) 사용, 없으면 적재기가 채움
    captured = local.get("created_at") or local.get("captured_at")
    return {
        "url": url,
        **({"captured_at": captured} if captured else {}),
        "site": local.get("channel") or "linkedin_rps",
        "page_title": (local.get("name") or "") + (" — " + local["headline"] if local.get("headline") else ""),
        "text_content": local.get("raw_text"),
        "text_length": len(local.get("raw_text") or ""),
        "screenshot_count": 1 if shot else 0,
        "screenshot_paths": [shot] if shot else [],
        "structured_json": json.dumps(_briefing(local), ensure_ascii=False),
    }


def to_sourcing_result_row(local: dict[str, Any], position_title: str) -> dict[str, Any] | None:
    """로컬 후보 1행 → sourcing_results 페이로드. url/점수 무효면 None(fail-closed)."""
    url = local.get("url")
    score = local.get("match_score")
    if not is_valid_profile_url(url) or not isinstance(score, (int, float)):
        return None
    b = _briefing(local)
    why_fit = b.get("why_fit") or []
    why_not = b.get("why_not") or []
    return {
        "position_id": local.get("position_id") or "",
        "position_title": position_title,
        "channel": local.get("channel") or "linkedin_rps",
        "value_type": "profile_url",
        "value": url,
        "candidate_name": local.get("name") or "",
        "match_score": int(score),
        "education_summary": (b.get("education") or "")[:500],
        "career_summary": "; ".join(why_fit)[:800],
        "fit_reason": (local.get("fit_reason") or "; ".join(why_fit))[:800],
        "match_points": why_fit,
        "mismatch_points": why_not,
        "candidate_briefing": json.dumps(b, ensure_ascii=False)[:4000],
    }
