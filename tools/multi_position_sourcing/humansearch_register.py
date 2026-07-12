"""humansearch 결과 묶음 등록 — Discord #ai_search 1메시지 + ClickUp 댓글 1개.

⛔ URL 무결: is_valid_profile_url 통과 + score>=70 후보만(eligible_matches_for_send 동일 기준).
⛔ 알람 폭탄 금지: Discord 는 합격자 전원을 *한 메시지*로, ClickUp 은 *댓글 1개*로 묶는다.
발송(제안/메일)이 아니라 '후보 브리핑' 등록이다(SOT3 안전).
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.multi_position_sourcing.humansearch import (
    PASS_THRESHOLD,
    _normalize,
    hard_exclude_reason,
    is_valid_profile_url,
)
from tools.multi_position_sourcing.models import CapturedProfile, Channel, EmploymentTenure

POSITION_ID = "86ey2cdfj"
POSITION_NAME = "[뤼튼테크놀로지스 AX CIC] AX Sales Team Lead (AI Account Executive 리드)"
FY26_AI_SEARCH_LIST_ID = "901818680208"
FY26_AI_SEARCH_LIST_URL = "https://app.clickup.com/9018789656/v/li/901818680208"
PROFILE_SAVE_EVIDENCE_FIELDS = (
    "screenshot",
    "screenshot_path",
    "evidence_paths",
    "archive_path",
    "saved_profile_path",
    "profile_archive_id",
    "sourcing_result_id",
    "db_row_id",
    "supabase_profile_archive_id",
)
REQUIRED_CANDIDATE_OUTPUT_FIELDS = ("profile_url", "score", "why_fit", "profile_summary")

ClickUpSearchTasks = Callable[..., Sequence[Mapping[str, object]]]
ClickUpCreateTask = Callable[..., Mapping[str, object] | tuple[str, str]]


@dataclass(frozen=True)
class ClickUpCandidateRegistration:
    profile_url: str
    name: str
    action: str
    task_id: str = ""
    task_url: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ClickUpRegistrationPlan:
    list_id: str
    list_url: str
    position_id: str
    position_name: str
    parent_task_id: str
    parent_task_url: str
    parent_action: str
    candidates: tuple[ClickUpCandidateRegistration, ...]
    dry_run: bool
    duplicate_checked: bool = True


def _load_env(key: str) -> str | None:
    env = Path(__file__).resolve().parents[2] / ".env.local"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return os.environ.get(key)


def _reconstruct_tenures(raw: object) -> tuple[EmploymentTenure, ...]:
    """employment_history(dict 리스트) → EmploymentTenure 튜플. start_month 없는 잡음 항목은 skip."""
    out: list[EmploymentTenure] = []
    for e in raw if isinstance(raw, (list, tuple)) else ():
        if isinstance(e, EmploymentTenure):
            out.append(e)
        elif isinstance(e, dict) and str(e.get("start_month") or "").strip():
            out.append(
                EmploymentTenure(
                    company=str(e.get("company", "") or ""),
                    start_month=str(e.get("start_month", "") or ""),
                    end_month=str(e.get("end_month", "") or ""),
                )
            )
        elif isinstance(e, (list, tuple)) and len(e) >= 2 and str(e[1] or "").strip():
            # 위치형 [company, start_month, end_month?] — 잦은이직 신호가 튜플/배열 형상으로 와도 놓치지 않음.
            out.append(
                EmploymentTenure(
                    company=str(e[0] or ""),
                    start_month=str(e[1] or ""),
                    end_month=str(e[2] or "") if len(e) > 2 else "",
                )
            )
    return tuple(out)


def reconstruct_captured_profile(result: object, channel: Channel) -> CapturedProfile | None:
    """register/results dict → 하드제외 판정용 CapturedProfile (판정 불가면 None=fail-closed).

    SOT(fail-open 금지): 신뢰성 있는 하드제외 판정에 필요한 필드가 결손되면 None 을 돌려,
    호출자(등록 게이트 C1a)가 '판정 불가 = 제외'로 처리하게 한다.
    무손실 아님 — ocr_text 등 원본 dict 에 없을 수 있어 *가용* 필드만 복원(2차검증 V2 재정의).
    models.CapturedProfile 재사용(제2 프로필 타입 금지, SOT5).
    """
    if not isinstance(result, dict):
        return None
    url = result.get("url") or result.get("profile_url")
    if not is_valid_profile_url(url):
        return None  # 신원(URL) 결손·무효(공백·제로폭·비http) → fail-closed
    visible_text = str(result.get("visible_text", "") or "")
    summary = str(result.get("summary", "") or "")
    headline = str(result.get("headline", "") or "")
    # 판정 가능한 '본문'(본문·요약·헤드라인)이 전무하거나 보이지 않는 문자·공백뿐이면 판정 불가 → fail-closed.
    # 매처와 동일 _normalize 재사용. name/why_fit 은 스캔하지 않는다 — name 은 신원 필드라 프리랜서 신호가
    # 없고(그 신호는 본문에 있어 스캔됨), name 스캔은 '외주' 등 2글자 마커의 부분문자열 오탐만 키운다(Codex 재검증 재현).
    if not _normalize(visible_text + summary + headline):
        return None
    skills = result.get("skills")
    companies = result.get("current_or_past_companies")
    return CapturedProfile(
        profile_url=url,
        source_channel=channel,
        visible_text=visible_text,
        summary=summary,
        # headline 은 프로필 설명 텍스트 — 매처가 스캔하도록 여분 슬롯(ocr_text)에 싣는다(headline-only 프리랜서 차단).
        ocr_text=headline,
        captured_at=str(result.get("captured_at", "") or ""),
        education=str(result.get("education", "") or ""),
        skills=tuple(skills) if isinstance(skills, (list, tuple)) else (),
        current_or_past_companies=(
            tuple(str(company).strip() for company in companies if _present(company))
            if isinstance(companies, (list, tuple))
            else ()
        ),
        employment_history=_reconstruct_tenures(result.get("employment_history", ())),
    )


def eligible(results: list[dict], channel: Channel) -> list[dict]:
    """등록 브리핑에 내보낼 후보만 — 점수·URL 게이트 + 채점 전 하드제외(프리랜서·잦은이직·전문대).

    현행 계약(score>=PASS_THRESHOLD · 유효 URL) 유지 + PC-C1a1 재구성으로 CapturedProfile 복원 후
    PC-C0 매처(hard_exclude_reason)를 적용해 프리랜서·단기이직2회+·전문대(portal 채널)를 등록 전에 차단한다.
    재구성 불가(결손 dict)는 fail-closed(제외). 학교컷은 PORTAL_SCHOOL_CUT_CHANNELS 채널만(매처가 판단). SOT5·SOT3.
    channel 은 필수 — 기본값을 두면 잘못된 채널로 school-cut 이 조용히 우회되므로 호출자가 명시한다.
    """
    ok: list[dict] = []
    for r in results:
        if not isinstance(r, dict):
            continue  # 비dict 항목 → fail-closed skip(크래시 방지)
        score = r.get("score", 0)
        # NaN/inf 는 '<threshold' 를 통과(NaN 비교 False, inf>=t True) → 유한 수치 + 양수형(>=)으로 판정.
        if not (isinstance(score, (int, float)) and math.isfinite(score) and score >= PASS_THRESHOLD):
            continue  # 점수 미달·비수치·NaN·inf → 제외 (fail-closed)
        # register 스키마 URL 키는 'url'. 하류(build_message·clickup) 도 r['url'] 을 읽으므로 여기서 'url' 로 통일한다.
        if not is_valid_profile_url(r.get("url")):
            continue  # URL 무효/결손 → 제외
        profile = reconstruct_captured_profile(r, channel)
        if profile is None:
            continue  # 재구성 불가(결손) → fail-closed 제외
        if hard_exclude_reason(profile, channel) is not None:
            continue  # 프리랜서·잦은이직·전문대(portal) → 채점 전 하드제외
        ok.append(r)
    return sorted(ok, key=lambda r: -r["score"])


def _present(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(_normalize(value))
    return bool(value)


def has_saved_profile_evidence(result: object) -> bool:
    """프로필 저장 증거가 있는지 검사한다.

    ClickUp FY26AI_Search 등록은 "찾았다"가 아니라 "프로필을 저장했다"는 증거가 있어야 한다.
    스크린샷/아카이브/DB·Supabase id/evidence_paths 중 하나도 없으면 등록 경계에서 fail-closed.
    """
    if not isinstance(result, dict):
        return False

    direct_keys = tuple(key for key in PROFILE_SAVE_EVIDENCE_FIELDS if key != "evidence_paths")
    if any(_present(result.get(key)) for key in direct_keys):
        return True

    evidence = result.get("evidence_paths")
    if isinstance(evidence, str):
        return _present(evidence)
    if isinstance(evidence, (list, tuple, set)):
        return any(_present(item) for item in evidence)
    return False


def _has_profile_summary(result: Mapping[str, object]) -> bool:
    return _present(result.get("profile_summary")) or _present(result.get("summary"))


def _has_why_fit(result: Mapping[str, object]) -> bool:
    why_fit = result.get("why_fit")
    if isinstance(why_fit, (list, tuple, set)):
        return any(_present(item) for item in why_fit)
    return _present(why_fit)


def has_required_candidate_output_fields(result: object) -> bool:
    """ClickUp Subtask 생성 전 후보 출력 계약 4필드를 검사한다.

    humansearch runner 의 내부 dict 는 URL 키를 ``url`` 로 쓴다. 등록 경계에서는 이를
    SOT 의 ``profile_url`` 로 매핑하되, 점수·매칭 이유·프로필 요약은 빠지면 fail-closed 한다.
    """
    if not isinstance(result, dict):
        return False
    score = result.get("score")
    return (
        is_valid_profile_url(result.get("url") or result.get("profile_url"))
        and isinstance(score, (int, float))
        and math.isfinite(score)
        and _has_why_fit(result)
        and _has_profile_summary(result)
    )


def clickup_registration_eligible(results: list[dict], channel: Channel) -> list[dict]:
    """FY26AI_Search Task/Subtask 등록 대상 후보.

    기존 eligible(score>=70, URL 무결성, 하드제외) 위에 후보 출력 4필드와 프로필 저장 증거를 추가로 요구한다.
    """
    return [
        r
        for r in eligible(results, channel)
        if has_required_candidate_output_fields(r) and has_saved_profile_evidence(r)
    ]


def discord_briefing_eligible(results: list[dict], channel: Channel) -> list[dict]:
    """Discord 후보 브리핑은 경력 요약까지 있는 후보만 fail-closed로 통과시킨다."""
    return [
        r
        for r in eligible(results, channel)
        if has_required_candidate_output_fields(r) and _present(r.get("career_summary"))
    ]


def _task_field(task: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = task.get(key)
        if value is not None:
            text = str(value).strip()
            if text:
                return text
    return ""


def _search_clickup_tasks(
    clickup_search_tasks: ClickUpSearchTasks | None,
    *,
    list_id: str,
    query: str,
    parent: str | None = None,
) -> tuple[Mapping[str, object], ...]:
    if clickup_search_tasks is None:
        raise RuntimeError("duplicate_check_required: clickup_search_tasks adapter is mandatory")
    result = clickup_search_tasks(list_id=list_id, query=query, parent=parent)
    return tuple(result or ())


def _create_clickup_task(
    clickup_create_task: ClickUpCreateTask | None,
    *,
    list_id: str,
    name: str,
    description: str,
    parent: str | None = None,
) -> tuple[str, str]:
    if clickup_create_task is None:
        raise RuntimeError("clickup_create_task_required: live ClickUp registration needs a create adapter")
    result = clickup_create_task(
        list_id=list_id,
        name=name,
        description=description,
        parent=parent,
    )
    if isinstance(result, Mapping):
        return (
            _task_field(result, "id", "task_id"),
            _task_field(result, "url", "task_url", "link"),
        )
    if isinstance(result, tuple) and len(result) >= 2:
        return str(result[0]), str(result[1])
    return "", ""


def _saved_profile_evidence_text(result: Mapping[str, object]) -> str:
    for key in (
        "screenshot",
        "screenshot_path",
        "archive_path",
        "saved_profile_path",
        "profile_archive_id",
        "supabase_profile_archive_id",
    ):
        value = result.get(key)
        if _present(value):
            return f"{key}: {value}"
    evidence = result.get("evidence_paths")
    if isinstance(evidence, str) and _present(evidence):
        return f"evidence_paths: {evidence}"
    if isinstance(evidence, (list, tuple, set)):
        first = next((str(item) for item in evidence if _present(item)), "")
        if first:
            return f"evidence_paths: {first}"
    return "missing"


def _lines(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if _present(value) else ()
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if _present(item))
    return ()


def _bullet_text(items: object, *, empty: str = "미기재") -> str:
    lines = _lines(items)
    if not lines:
        return f"- {empty}"
    return "\n".join(f"- {line}" for line in lines)


def _first_present(result: Mapping[str, object], *keys: str) -> str:
    for key in keys:
        value = result.get(key)
        if _present(value):
            return str(value).strip()
    return ""


def _score_breakdown_text(result: Mapping[str, object]) -> str:
    breakdown = result.get("breakdown")
    if not isinstance(breakdown, Mapping):
        return "- 세부 점수 미기재"
    labels = (
        ("education", "학력"),
        ("role_fit", "직무"),
        ("profile_logic", "논리"),
        ("job_stability", "안정"),
    )
    parts = [f"{label} {breakdown[key]}" for key, label in labels if key in breakdown]
    return f"- {' / '.join(parts)}" if parts else "- 세부 점수 미기재"


def _profile_signal_text(result: Mapping[str, object]) -> str:
    signals = []
    for label, key in (("헤드라인", "headline"), ("학력", "education"), ("요약", "summary")):
        value = result.get(key)
        if _present(value):
            signals.append(f"- {label}: {str(value).strip()}")
    skills = result.get("skills")
    if isinstance(skills, (list, tuple, set)):
        skill_text = ", ".join(str(skill).strip() for skill in skills if _present(skill))
        if skill_text:
            signals.append(f"- 기술/키워드: {skill_text}")
    return "\n".join(signals) if signals else "- 프로필 신호 미기재"


def _parent_task_description(*, position_name: str, position_id: str, channel: Channel) -> str:
    return "\n".join(
        [
            "[AI Search / Humansearch 등록]",
            f"원 포지션 ID: {position_id or '(미상)'}",
            f"포지션: {position_name}",
            f"채널: {channel}",
            f"칸반 리스트: FY26AI_Search ({FY26_AI_SEARCH_LIST_URL})",
            "중복검사: 부모 Task 검색 후 재사용, 후보 profile_url Subtask 검색 후 생성",
            "프로필 저장 증거 없는 후보는 등록하지 않음",
            "제안/메일/InMail 자동발송 안 함",
        ]
    )


def _parent_task_name(position_name: str) -> str:
    return f"{position_name} — AI Search"


def _candidate_task_name(result: Mapping[str, object]) -> str:
    name = str(result.get("name") or "후보").strip()
    score = result.get("score", "?")
    otw = " OTW" if result.get("otw") else ""
    summary = str(result.get("headline") or result.get("summary") or "").strip()
    suffix = f" · {summary[:48]}" if summary else ""
    # profile_url 을 이름에도 넣어 이름 기반 ClickUp 검색 어댑터에서도 후보 중복검사가 잡히게 한다.
    return f"{name} — {score}점{otw}{suffix} · {result['url']}"


def _candidate_task_description(
    result: Mapping[str, object],
    *,
    position_id: str,
    channel: Channel,
) -> str:
    profile_summary = _first_present(result, "profile_summary", "summary", "headline") or "미기재"
    return "\n".join(
        [
            f"Profile: {result['url']}",
            f"점수: {result.get('score', '?')}/100",
            f"대상 포지션 ID: {position_id or '(미상)'}",
            f"채널: {channel}",
            f"프로필 저장 증거: {_saved_profile_evidence_text(result)}",
            "",
            "프로필 요약:",
            profile_summary,
            "",
            "왜 이 포지션에 잘 맞는지:",
            _bullet_text(result.get("why_fit")),
            "",
            "점수 근거:",
            _score_breakdown_text(result),
            "",
            "프로필에서 확인한 신호:",
            _profile_signal_text(result),
            "",
            "리스크/확인 필요:",
            _bullet_text(result.get("why_not"), empty="큰 리스크 미기재"),
            "",
            "등록 판단:",
            "- 저장 증거와 profile_url 무결성을 확인한 후보만 FY26AI_Search Subtask로 등록",
            "- 제안/메일/InMail 자동발송 없음",
        ]
    )


def register_clickup_fy26_ai_search(
    *,
    position_name: str,
    position_id: str,
    passers: list[dict],
    channel: Channel,
    clickup_search_tasks: ClickUpSearchTasks | None,
    clickup_create_task: ClickUpCreateTask | None = None,
    dry_run: bool = True,
) -> ClickUpRegistrationPlan:
    """FY26AI_Search 보드에 부모 Task + 후보 Subtask 를 등록/계획한다.

    중복검사 어댑터는 dry-run 에도 필수다. 검색 없이 create 계획을 세우면 같은 포지션/후보가
    칸반에 중복 생성되므로 fail-closed 한다. 실제 쓰기는 ``dry_run=False`` 와 create 어댑터가
    둘 다 있을 때만 일어난다.
    """
    position_name = (position_name or POSITION_NAME).strip()
    position_id = (position_id or POSITION_ID).strip()
    parent_name = _parent_task_name(position_name)
    parent_hits = _search_clickup_tasks(
        clickup_search_tasks,
        list_id=FY26_AI_SEARCH_LIST_ID,
        query=position_name,
    )
    if not parent_hits:
        parent_hits = _search_clickup_tasks(
            clickup_search_tasks,
            list_id=FY26_AI_SEARCH_LIST_ID,
            query=parent_name,
        )

    parent_action = "reused"
    parent_task_id = ""
    parent_task_url = ""
    if parent_hits:
        parent_task_id = _task_field(parent_hits[0], "id", "task_id")
        parent_task_url = _task_field(parent_hits[0], "url", "task_url", "link")
    elif dry_run:
        parent_action = "planned_create"
        parent_task_id = "DRYRUN-FY26AI-SEARCH-PARENT"
        parent_task_url = FY26_AI_SEARCH_LIST_URL
    else:
        parent_action = "created"
        parent_task_id, parent_task_url = _create_clickup_task(
            clickup_create_task,
            list_id=FY26_AI_SEARCH_LIST_ID,
            name=parent_name,
            description=_parent_task_description(
                position_name=position_name,
                position_id=position_id,
                channel=channel,
            ),
            parent=None,
        )
        if not parent_task_id:
            raise RuntimeError("parent_task_id_required: ClickUp parent Task creation returned no id")

    candidates: list[ClickUpCandidateRegistration] = []
    for result in clickup_registration_eligible(passers, channel):
        if not parent_task_id:
            raise RuntimeError("parent_task_id_required: cannot register candidate Subtasks without parent id")
        profile_url = str(result["url"])
        duplicate_hits = _search_clickup_tasks(
            clickup_search_tasks,
            list_id=FY26_AI_SEARCH_LIST_ID,
            query=profile_url,
            parent=parent_task_id,
        )
        name = str(result.get("name") or "후보").strip()
        if duplicate_hits:
            candidates.append(
                ClickUpCandidateRegistration(
                    profile_url=profile_url,
                    name=name,
                    action="skipped_duplicate",
                    task_id=_task_field(duplicate_hits[0], "id", "task_id"),
                    task_url=_task_field(duplicate_hits[0], "url", "task_url", "link"),
                    reason="candidate profile_url already registered under parent",
                )
            )
            continue

        if dry_run:
            candidates.append(
                ClickUpCandidateRegistration(
                    profile_url=profile_url,
                    name=name,
                    action="planned_create",
                    reason="dry-run",
                )
            )
            continue

        task_id, task_url = _create_clickup_task(
            clickup_create_task,
            list_id=FY26_AI_SEARCH_LIST_ID,
            name=_candidate_task_name(result),
            description=_candidate_task_description(
                result,
                position_id=position_id,
                channel=channel,
            ),
            parent=parent_task_id,
        )
        if not task_id:
            raise RuntimeError("candidate_task_id_required: ClickUp candidate Subtask creation returned no id")
        candidates.append(
            ClickUpCandidateRegistration(
                profile_url=profile_url,
                name=name,
                action="created",
                task_id=task_id,
                task_url=task_url,
            )
        )

    return ClickUpRegistrationPlan(
        list_id=FY26_AI_SEARCH_LIST_ID,
        list_url=FY26_AI_SEARCH_LIST_URL,
        position_id=position_id,
        position_name=position_name,
        parent_task_id=parent_task_id,
        parent_task_url=parent_task_url,
        parent_action=parent_action,
        candidates=tuple(candidates),
        dry_run=dry_run,
        duplicate_checked=True,
    )


def _school(education: str) -> str:
    """학력 원문에서 학교명만 — 'Degree details' 앞부분(부분일치 잡음 제거)."""
    head = (education or "").split("Degree details")[0]
    return head.strip()[:34] or "-"


DISCORD_CONTENT_LIMIT = 1990
DISCORD_EMBED_COUNT_LIMIT = 10
DISCORD_EMBED_TITLE_LIMIT = 256
DISCORD_EMBED_DESCRIPTION_LIMIT = 4096
DISCORD_EMBED_URL_LIMIT = 2048
DISCORD_EMBED_TOTAL_TEXT_LIMIT = 6000
TOP_CANDIDATE_SCORE = 85


def _compact_line(value: object, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _discord_candidate_block(index: int, result: Mapping[str, object]) -> str:
    breakdown = result.get("breakdown")
    b = breakdown if isinstance(breakdown, Mapping) else {}
    otw = " 🟢" if result.get("otw") else ""
    education = str(result.get("education", "") or "")
    note = ""
    if "berkeley college" in education.lower():
        note = " ⚠️('Berkeley College'=명문대 오탐, 학력 재판단 요)"
    summary = _first_present(
        result,
        "career_summary",
        "profile_summary",
        "summary",
        "headline",
    ) or "경력 요약 미기재"
    why_fit = "; ".join(_lines(result.get("why_fit"))) or "적합 사유 미기재"
    name = _compact_line(result.get("name", "이름 미기재"), limit=80)
    return (
        f"**{index}. {name} — {result['score']}/100**{otw} · {_school(education)}{note}\n"
        f"  학력{b.get('education','?')}/직무{b.get('role_fit','?')}/논리{b.get('profile_logic','?')}/안정{b.get('job_stability','?')}\n"
        f"  경력 요약: {_compact_line(summary, limit=220)}\n"
        f"  적합 사유: {_compact_line(why_fit, limit=280)}\n"
        f"  {result['url']}"
    )


def _ordered_briefing_candidates(passers: list[dict]) -> list[dict]:
    return sorted(passers, key=lambda item: float(item.get("score", 0)), reverse=True)


def _discord_candidate_embed(index: int, result: Mapping[str, object]) -> dict[str, object]:
    url = str(result["url"])
    if not is_valid_profile_url(url) or len(url) > DISCORD_EMBED_URL_LIMIT:
        raise ValueError("Discord 후보 Profile URL이 유효하지 않거나 embed URL 제한을 초과함")
    if not has_required_candidate_output_fields(result) or not _present(result.get("career_summary")):
        raise ValueError("Discord 후보 카드 필수 필드(profile_url/score/경력요약/why_fit) 누락")
    if float(result.get("score", 0)) < PASS_THRESHOLD:
        raise ValueError("Discord 후보 점수가 합격선 미만")
    summary = _first_present(
        result,
        "career_summary",
        "profile_summary",
        "summary",
        "headline",
    )
    why_fit = "; ".join(_lines(result.get("why_fit")))
    org_fit = _first_present(result, "org_fit") or "neutral"
    education = _school(str(result.get("education", "") or ""))
    description = (
        f"Profile URL: {url}\n"
        f"경력 요약: {_compact_line(summary, limit=180)}\n"
        f"적합 사유: {_compact_line(why_fit, limit=220)}\n"
        f"학력: {education} · org_fit: {org_fit}"
    )
    return {
        "title": _compact_line(
            f"{index}. {result.get('name', '이름 미기재')} — {result['score']}/100",
            limit=240,
        ),
        "url": url,
        "description": description,
        "color": 0x0A66C2,
    }


def _embed_text_size(embed: Mapping[str, object]) -> int:
    return sum(len(str(embed.get(key, ""))) for key in ("title", "description", "footer", "author"))


def _validate_discord_embed(embed: Mapping[str, object]) -> None:
    if len(str(embed.get("title", ""))) > DISCORD_EMBED_TITLE_LIMIT:
        raise ValueError("Discord 후보 embed title 제한 초과")
    if len(str(embed.get("description", ""))) > DISCORD_EMBED_DESCRIPTION_LIMIT:
        raise ValueError("Discord 후보 embed description 제한 초과")
    url = str(embed.get("url", ""))
    if not is_valid_profile_url(url) or len(url) > DISCORD_EMBED_URL_LIMIT:
        raise ValueError("Discord 후보 embed URL 제한 초과")


def build_discord_payloads(passers: list[dict]) -> list[dict[str, object]]:
    """70점 이상 합격 후보 전원을 Discord 제한에 맞춰 10개 이하 embed 메시지로 분할한다."""
    ordered = _ordered_briefing_candidates(passers)
    chunks: list[list[dict[str, object]]] = []
    current: list[dict[str, object]] = []
    current_size = 0
    for index, result in enumerate(ordered, 1):
        embed = _discord_candidate_embed(index, result)
        _validate_discord_embed(embed)
        embed_size = _embed_text_size(embed)
        if embed_size > DISCORD_EMBED_TOTAL_TEXT_LIMIT:
            raise ValueError("Discord 후보 embed 1개가 메시지 총 텍스트 제한을 초과함")
        if current and (
            len(current) >= DISCORD_EMBED_COUNT_LIMIT
            or current_size + embed_size > DISCORD_EMBED_TOTAL_TEXT_LIMIT
        ):
            chunks.append(current)
            current = []
            current_size = 0
        current.append(embed)
        current_size += embed_size
    if current:
        chunks.append(current)

    total_messages = len(chunks)
    payloads: list[dict[str, object]] = []
    for message_index, embeds in enumerate(chunks, 1):
        strong_count = sum(float(item.get("score", 0)) >= TOP_CANDIDATE_SCORE for item in ordered)
        continuation = f" · {message_index}/{total_messages}" if total_messages > 1 else ""
        content = (
            f"📋 **AI Search 후보 브리핑 — {POSITION_NAME}**{continuation}\n"
            f"합격 {len(ordered)}명 · 강력추천 {strong_count}명 · 이번 카드 {len(embeds)}명"
        )
        if len(content) > DISCORD_CONTENT_LIMIT:
            raise ValueError("Discord 후보 브리핑 본문이 1메시지 제한을 초과함")
        payloads.append({"content": content, "embeds": embeds})
    return payloads


def build_discord_payload(passers: list[dict]) -> dict[str, object]:
    """단일 메시지 호환 래퍼. 분할이 필요하면 누락하지 않고 명시적으로 거부한다."""
    payloads = build_discord_payloads(passers)
    if len(payloads) != 1:
        raise ValueError("Discord 후보가 여러 메시지로 분할됨 — build_discord_payloads 사용 필요")
    return payloads[0]


def build_message(passers: list[dict]) -> str:
    head = (
        f"📋 **AI Search 후보 브리핑 — {POSITION_NAME}**\n"
        f"채널: LinkedIn Recruiter(RPS) · 합격선 {PASS_THRESHOLD}점 · 합격 {len(passers)}명\n"
        f"(채점: 학력30·직무50·논리10·이직안정10 / 🟢=Open to work)\n"
        "──────────────"
    )
    core = _ordered_briefing_candidates(passers)
    blocks: list[str] = []
    for i, r in enumerate(core, 1):
        block = _discord_candidate_block(i, r)
        candidate_message = head + "\n" + "\n".join([*blocks, block])
        if len(candidate_message) <= DISCORD_CONTENT_LIMIT:
            blocks.append(block)
            continue

        remaining = len(core) - len(blocks)
        footer = f"⚠️ 합격 후보 {remaining}명은 텍스트 미리보기 한도로 미포함 — embed 분할본 확인"
        with_footer = head + "\n" + "\n".join([*blocks, footer])
        if len(with_footer) <= DISCORD_CONTENT_LIMIT:
            blocks.append(footer)
        else:
            raise ValueError("Discord 후보 브리핑에서 미포함 후보 수를 표시할 공간이 없음")
        break

    message = head + "\n" + "\n".join(blocks)
    if len(message) > DISCORD_CONTENT_LIMIT:
        raise ValueError("Discord 후보 브리핑이 1메시지 제한을 초과함")
    return message


def post_discord(message: str | Mapping[str, object]) -> int:
    if isinstance(message, Mapping):
        payload_body = dict(message)
        content = str(payload_body.get("content", ""))
        if len(content) > DISCORD_CONTENT_LIMIT:
            raise ValueError("Discord 후보 브리핑 본문이 1메시지 제한을 초과함")
        embeds = payload_body.get("embeds", [])
        if not isinstance(embeds, list) or len(embeds) > DISCORD_EMBED_COUNT_LIMIT:
            raise ValueError("Discord 후보 embed 개수 제한 초과")
        embed_total = 0
        for embed in embeds:
            if not isinstance(embed, Mapping):
                raise ValueError("Discord 후보 embed 형식 오류")
            _validate_discord_embed(embed)
            embed_total += _embed_text_size(embed)
        if embed_total > DISCORD_EMBED_TOTAL_TEXT_LIMIT:
            raise ValueError("Discord 후보 embed 총 텍스트 제한 초과")
    else:
        # 완성된 후보 카드 중간을 잘라 URL/요약/적합사유 계약을 깨지 않는다.
        if len(message) > DISCORD_CONTENT_LIMIT:
            raise ValueError("Discord 후보 브리핑이 1메시지 제한을 초과함")
        payload_body = {"content": message, "flags": 4}
    url = _load_env("VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL 없음")
    payload = json.dumps(payload_body).encode()
    # Discord 는 Cloudflare 뒤 — 기본 python-urllib UA 는 403. 브라우저 UA 로 우회.
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    })
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def clickup_comment_body(passers: list[dict]) -> str:
    lines = [f"🔎 **AI Search 결과 — LinkedIn RPS · 합격 {len(passers)}명** (합격선 {PASS_THRESHOLD}점, 🟢=Open to work)",
             "_채점: 학력30·직무50·논리10·이직안정10_", ""]
    for i, r in enumerate(passers, 1):
        b = r.get("breakdown", {})
        otw = " 🟢" if r.get("otw") else ""
        note = " ⚠️('Berkeley College'=명문대 오탐, 학력 재판단)" if "berkeley college" in (r.get("education","").lower()) else ""
        lines.append(f"{i}. **{r['name']}** ({r['score']}/100){otw} · {_school(r.get('education',''))}{note}")
        lines.append(f"   학력{b.get('education','?')}/직무{b.get('role_fit','?')}/논리{b.get('profile_logic','?')}/안정{b.get('job_stability','?')} · [프로필 열기]({r['url']})")
    return "\n".join(lines)


if __name__ == "__main__":
    results_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path.home() / ".vh-search-results" / "linkedin_rps")
    results = json.loads(Path(results_path).read_text())
    passers = discord_briefing_eligible(
        results, "linkedin_rps"
    )  # LinkedIn RPS 포지션(학교컷 미적용) + 후보 출력 계약
    print(f"eligible passers: {len(passers)}")
    for r in passers:
        print(" ", r["score"], r["name"], r["url"])
    if "--send" in sys.argv:
        if "--clickup-register" in sys.argv:
            raise RuntimeError(
                "ClickUp FY26AI_Search registration requires duplicate-check capable "
                "clickup_search_tasks/clickup_create_task adapters; legacy comment body output is blocked."
            )
        statuses = [post_discord(payload) for payload in build_discord_payloads(passers)]
        print("discord statuses:", statuses)
        print("clickup FY26AI_Search registration skipped: use register_clickup_fy26_ai_search with duplicate-check adapters")
