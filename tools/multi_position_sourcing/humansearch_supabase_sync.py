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


def _briefing(local: dict[str, Any]) -> dict[str, Any] | None:
    """briefing 파싱. 깨진 JSON/비dict/누락 = None (V1 Codex: 조용한 {} 대체 금지)."""
    raw = local.get("candidate_briefing")
    if not raw:
        return None
    try:
        b = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return b if isinstance(b, dict) else None


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
        "structured_json": json.dumps(_briefing(local) or {}, ensure_ascii=False),
    }


def to_sourcing_result_row(local: dict[str, Any], position_title: str) -> dict[str, Any] | None:
    """로컬 후보 1행 → sourcing_results 페이로드. url/점수 무효면 None(fail-closed)."""
    url = local.get("url")
    score = local.get("match_score")
    # bool 은 int 의 하위타입 — True 가 점수 1로 새는 것 차단(V1 Codex). 범위 0~100 강제.
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not (0 <= score <= 100):
        return None
    if not is_valid_profile_url(url):
        return None
    b = _briefing(local)
    if b is None:  # 학력·경력 칸이 비게 됨 — 적재 거부(fail-closed)
        return None
    why_fit = b.get("why_fit") or []
    why_not = b.get("why_not") or []
    # 경력 칸에 학력 문장 금지(V1 Codex·사장님 지적) — 학력은 education_summary 로만.
    career_items = [w for w in why_fit if not str(w).startswith("학력")]
    return {
        "position_id": local.get("position_id") or "",
        "position_title": position_title,
        "channel": local.get("channel") or "linkedin_rps",
        "value_type": "profile_url",
        "value": url,
        "candidate_name": local.get("name") or "",
        "match_score": int(score),
        "education_summary": (b.get("education") or "")[:500],
        "career_summary": "; ".join(career_items)[:800],
        "fit_reason": ("; ".join(career_items) or local.get("fit_reason") or "")[:800],
        "match_points": why_fit,
        "mismatch_points": why_not,
        "candidate_briefing": json.dumps(b, ensure_ascii=False)[:4000],
    }


def to_organization_analysis_row(local: dict[str, Any]) -> dict[str, Any] | None:
    """로컬 조직 분석 1행 → organization_analysis 페이로드. position_id/본문 없으면 None."""
    position_id = str(local.get("position_id", "") or "").strip()
    company_name = str(local.get("company_name", "") or "").strip()
    role_title = str(local.get("role_title", "") or "").strip()
    org = str(local.get("organization_analysis", "") or "").strip()
    density = str(local.get("talent_density_notes", "") or "").strip()
    if not position_id or not company_name or not role_title:
        return None
    if not org and not density:
        return None
    return {
        "position_id": position_id,
        "company_name": company_name,
        "role_title": role_title,
        "company_size": str(local.get("company_size", "") or ""),
        "industry_segment": str(local.get("industry_segment", "") or ""),
        "investment_stage": str(local.get("investment_stage", "") or ""),
        "organization_analysis": org,
        "talent_density_notes": density,
        "org_fit_target": str(local.get("org_fit_target", "") or "neutral_target"),
        "updated_at": str(local.get("updated_at", "") or local.get("created_at", "") or ""),
    }
