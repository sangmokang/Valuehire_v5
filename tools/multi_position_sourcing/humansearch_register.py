"""humansearch 결과 묶음 등록 — Discord #ai_search 1메시지 + ClickUp 댓글 1개.

⛔ URL 무결: is_valid_profile_url 통과 + score>=70 후보만(eligible_matches_for_send 동일 기준).
⛔ 알람 폭탄 금지: Discord 는 합격자 전원을 *한 메시지*로, ClickUp 은 *댓글 1개*로 묶는다.
발송(제안/메일)이 아니라 '후보 브리핑' 등록이다(SOT3 안전).
"""
from __future__ import annotations

import base64
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
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
CANDIDATE_SPEC_MARKER = "VALUEHIRE_CANDIDATE_SPEC_V1:"
_CANDIDATE_SPEC_RE = re.compile(
    rf"<!--\s*{CANDIDATE_SPEC_MARKER}([A-Za-z0-9_-]+)\s*-->"
)
_MONTH_NAME = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
_ENGLISH_DATE_RE = re.compile(
    rf"\b(?P<start_month>{_MONTH_NAME})\s+(?P<start_year>\d{{4}})\s*[–—-]\s*"
    rf"(?:(?P<current>Present|Current|현재|재직중)|"
    rf"(?P<end_month>{_MONTH_NAME})\s+(?P<end_year>\d{{4}}))\b",
    re.I,
)
_NUMERIC_DATE_RE = re.compile(
    r"(?<!\d)(?P<start_year>\d{4})\s*(?:[./-]\s*|년\s*)"
    r"(?P<start_month>\d{1,2})\s*월?\s*(?:~|–|—|to|-)\s*"
    r"(?:(?P<current>Present|Current|현재|재직중)|"
    r"(?P<end_year>\d{4})\s*(?:[./-]\s*|년\s*)"
    r"(?P<end_month>\d{1,2})\s*월?)(?!\d)",
    re.I,
)
_MONTH_NUMBER = {
    name: number
    for number, names in enumerate(
        (("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
         ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
         ("sep", "september"), ("oct", "october"), ("nov", "november"),
         ("dec", "december")),
        1,
    )
    for name in names
}
_YEAR_MONTH_RE = re.compile(r"^(?:19|20)\d{2}-(?:0[1-9]|1[0-2])$")

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


def _source_date_ranges(visible_text: object) -> list[dict[str, str]]:
    """영문 월·숫자형 원문 날짜를 별도 추출한다. 같은 날짜의 출현 횟수도 보존한다."""
    text = str(visible_text or "")
    found: list[tuple[int, str, str]] = []
    for match in _ENGLISH_DATE_RE.finditer(text):
        start = (
            f"{match.group('start_year')}-"
            f"{_MONTH_NUMBER[match.group('start_month').lower()]:02d}"
        )
        end = "" if match.group("current") else (
            f"{match.group('end_year')}-"
            f"{_MONTH_NUMBER[match.group('end_month').lower()]:02d}"
        )
        found.append((match.start(), start, end))
    for match in _NUMERIC_DATE_RE.finditer(text):
        start = f"{match.group('start_year')}-{int(match.group('start_month')):02d}"
        end = "" if match.group("current") else (
            f"{match.group('end_year')}-{int(match.group('end_month')):02d}"
        )
        found.append((match.start(), start, end))
    return [
        {"start_month": start, "end_month": end}
        for _offset, start, end in sorted(found)
    ]


def _candidate_spec(result: Mapping[str, object], channel: Channel) -> dict[str, object]:
    visible_text = str(result.get("visible_text", "") or "")
    history = [
        {"company": item.company, "start_month": item.start_month, "end_month": item.end_month}
        for item in _reconstruct_tenures(result.get("employment_history", ()))
    ]
    return {
        "version": 1,
        "profile_url": str(result.get("url") or result.get("profile_url") or ""),
        "channel": channel,
        "score": result.get("score"),
        "summary": str(result.get("summary", "") or ""),
        "headline": str(result.get("headline", "") or ""),
        "visible_text": visible_text,
        "visible_text_sha256": hashlib.sha256(visible_text.encode()).hexdigest(),
        "education": str(result.get("education", "") or ""),
        "employment_history": history,
        "source_date_ranges": _source_date_ranges(visible_text),
        "saved_profile_evidence": _saved_profile_evidence_text(result),
    }


def _encoded_candidate_spec(result: Mapping[str, object], channel: Channel) -> str:
    raw = json.dumps(_candidate_spec(result, channel), ensure_ascii=False, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _candidate_task_description(
    result: Mapping[str, object],
    *,
    position_id: str,
    channel: Channel,
) -> str:
    why_fit = result.get("why_fit")
    if isinstance(why_fit, (list, tuple)):
        why_fit_text = "\n".join(f"- {item}" for item in why_fit if _present(item)) or "- 미기재"
    else:
        why_fit_text = f"- {why_fit}" if _present(why_fit) else "- 미기재"
    return "\n".join(
        [
            f"Profile: {result['url']}",
            f"점수: {result.get('score', '?')}/100",
            f"대상 포지션 ID: {position_id or '(미상)'}",
            f"채널: {channel}",
            f"프로필 저장 증거: {_saved_profile_evidence_text(result)}",
            "",
            "매칭 이유:",
            why_fit_text,
            "",
            f"<!-- {CANDIDATE_SPEC_MARKER}{_encoded_candidate_spec(result, channel)} -->",
        ]
    )


def _tool_text(tool_input: Mapping[str, object]) -> str:
    return json.dumps(tool_input, ensure_ascii=False, default=str)


def _canonical_parent_write(tool_name: str, tool_input: Mapping[str, object]) -> bool:
    name = str(tool_input.get("name", "") or "")
    description = str(
        tool_input.get("description") or tool_input.get("markdown_description") or ""
    )
    suffix = " — AI Search"
    if not name.endswith(suffix):
        return False
    position_name = name[:-len(suffix)]
    return bool(
        "create_task" in tool_name.lower()
        and str(tool_input.get("list_id", "")) == FY26_AI_SEARCH_LIST_ID
        and not tool_input.get("parent")
        and description.startswith("[AI Search / Humansearch 등록]\n")
        and f"\n포지션: {position_name}\n" in description
        and f"칸반 리스트: FY26AI_Search ({FY26_AI_SEARCH_LIST_URL})" in description
        and "중복검사: 부모 Task 검색 후 재사용" in description
    )


def _candidate_write(tool_name: str, tool_input: Mapping[str, object]) -> bool:
    tool = tool_name.lower()
    if "clickup_" not in tool or not ("create_task" in tool or "update_task" in tool):
        return False
    if _canonical_parent_write(tool_name, tool_input):
        return False
    text = _tool_text(tool_input)
    name = str(tool_input.get("name", "") or "")
    return (
        str(tool_input.get("list_id", "")) == FY26_AI_SEARCH_LIST_ID
        and bool(tool_input.get("parent"))
    ) or CANDIDATE_SPEC_MARKER in text or bool(
        re.search(r"https?://\S*(?:linkedin\.com|saramin\.co\.kr|jobkorea\.co\.kr)\S*", text, re.I)
    ) or bool(
        re.search(r"\"score\"|점수|강력추천|\b\d{2,3}\s*점", text, re.I)
    ) or bool(
        re.search(r"후보|candidate", name, re.I)
    )


def _decode_candidate_spec(tool_input: Mapping[str, object]) -> dict[str, object] | None:
    match = _CANDIDATE_SPEC_RE.search(_tool_text(tool_input))
    if not match:
        return None
    try:
        token = match.group(1)
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        value = json.loads(decoded)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _valid_tenure(item: EmploymentTenure) -> bool:
    return bool(
        _YEAR_MONTH_RE.fullmatch(item.start_month)
        and (not item.end_month or _YEAR_MONTH_RE.fullmatch(item.end_month))
        and (not item.end_month or item.start_month <= item.end_month)
    )


def _deduplicated_history(raw: object) -> list[dict[str, str]]:
    """동일 회사·기간의 복수 직함만 합친다. 회사 미상은 안전하게 각각 센다."""
    output: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, item in enumerate(_reconstruct_tenures(raw)):
        company = _normalize(item.company)
        key = (company or f"unknown:{index}", item.start_month, item.end_month)
        if key in seen:
            continue
        seen.add(key)
        output.append({
            "company": item.company,
            "start_month": item.start_month,
            "end_month": item.end_month,
        })
    return output


def candidate_spec_hook_reason(event: object) -> str | None:
    """Claude/Codex 공통 PreToolUse 판정. None이면 허용, 문자열이면 exit 2 차단."""
    if not isinstance(event, Mapping):
        return "candidate_hook_input_invalid"
    tool_name = str(event.get("tool_name", "") or "")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, Mapping):
        return "candidate_hook_input_invalid"
    if not _candidate_write(tool_name, tool_input):
        return None

    is_create = "create_task" in tool_name.lower()
    if is_create and str(tool_input.get("list_id", "")) != FY26_AI_SEARCH_LIST_ID:
        return "wrong_list_id"
    if is_create and not tool_input.get("parent"):
        return "candidate_parent_missing"

    spec = _decode_candidate_spec(tool_input)
    if spec is None:
        return "candidate_spec_missing"
    if spec.get("version") != 1:
        return "candidate_spec_version_invalid"
    profile_url = str(spec.get("profile_url", "") or "")
    if not is_valid_profile_url(profile_url) or profile_url not in _tool_text(tool_input):
        return "candidate_identity_mismatch"
    score = spec.get("score")
    if not (isinstance(score, (int, float)) and math.isfinite(score) and score >= PASS_THRESHOLD):
        return "candidate_score_invalid"
    if spec.get("saved_profile_evidence") in (None, "", "missing"):
        return "candidate_evidence_missing"
    visible_text = str(spec.get("visible_text", "") or "")
    if hashlib.sha256(visible_text.encode()).hexdigest() != spec.get("visible_text_sha256"):
        return "candidate_source_hash_mismatch"

    channel = str(spec.get("channel", "") or "")
    if channel == "linkedin":
        channel = "linkedin_rps"
    if channel not in ("linkedin_rps", "saramin", "jobkorea"):
        return "candidate_channel_invalid"
    source_ranges = _source_date_ranges(visible_text)
    if source_ranges != spec.get("source_date_ranges"):
        return "candidate_source_ranges_mismatch"
    history = _reconstruct_tenures(spec.get("employment_history"))
    if not history:
        return "candidate_history_missing"
    if any(not _valid_tenure(item) for item in history):
        return "candidate_history_invalid"
    source_history = _reconstruct_tenures(source_ranges)
    if not source_history:
        return "candidate_source_dates_missing"
    if any(not _valid_tenure(item) for item in source_history):
        return "candidate_source_dates_invalid"
    source_count = Counter((item.start_month, item.end_month) for item in source_history)
    history_count = Counter((item.start_month, item.end_month) for item in history)
    if any(history_count[period] < count for period, count in source_count.items()):
        return "candidate_history_incomplete"

    profile_input = dict(spec)
    profile_input["employment_history"] = _deduplicated_history(history)
    profile = reconstruct_captured_profile(profile_input, channel)
    if profile is None:
        return "candidate_profile_invalid"
    return hard_exclude_reason(profile, channel)


def _candidate_spec_evaluation(raw: str) -> tuple[int, str, dict[str, object] | None]:
    try:
        event = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return 2, "candidate_hook_input_invalid", None
    reason = candidate_spec_hook_reason(event)
    if reason:
        return 2, reason, None
    if not isinstance(event, dict) or not isinstance(event.get("tool_input"), dict):
        return 0, "", None
    tool_input = dict(event["tool_input"])
    if _decode_candidate_spec(tool_input) is None:
        return 0, "", None
    for key in ("description", "markdown_description"):
        if isinstance(tool_input.get(key), str):
            tool_input[key] = _CANDIDATE_SPEC_RE.sub("", tool_input[key]).rstrip()
    return 0, "", tool_input


def candidate_spec_hook_cli(raw: str) -> tuple[int, str]:
    code, reason, _updated_input = _candidate_spec_evaluation(raw)
    return code, reason


def _run_candidate_spec_hook() -> int:
    code, reason, updated_input = _candidate_spec_evaluation(sys.stdin.read())
    if code:
        sys.stderr.write(reason + "\n")
        return code
    if updated_input is not None:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "updatedInput": updated_input,
            }
        }, ensure_ascii=False))
    return 0


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


def build_message(passers: list[dict]) -> str:
    head = (
        f"📋 **AI Search 후보 브리핑 — {POSITION_NAME}**\n"
        f"채널: LinkedIn Recruiter(RPS) · 합격선 {PASS_THRESHOLD}점 · 합격 {len(passers)}명\n"
        f"(채점: 학력30·직무50·논리10·이직안정10 / 🟢=Open to work)\n"
        "──────────────"
    )
    blocks = []
    for i, r in enumerate(passers, 1):
        b = r.get("breakdown", {})
        otw = " 🟢" if r.get("otw") else ""
        note = ""
        if "berkeley college" in (r.get("education", "").lower()):
            note = " ⚠️('Berkeley College'=명문대 오탐, 학력 재판단 요)"
        blocks.append(
            f"**{i}. {r['name']} — {r['score']}/100**{otw} · {_school(r.get('education',''))}{note}\n"
            f"  학력{b.get('education','?')}/직무{b.get('role_fit','?')}/논리{b.get('profile_logic','?')}/안정{b.get('job_stability','?')}\n"
            f"  {r['url']}"
        )
    return head + "\n" + "\n".join(blocks)


def post_discord(message: str) -> int:
    url = _load_env("VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL")
    if not url:
        raise RuntimeError("VALUEHIRE_SEARCH_LIST_DISCORD_WEBHOOK_URL 없음")
    # Discord 2000자 제한 — 넘으면 잘라 1메시지 유지(알람 폭탄 금지 우선).
    payload = json.dumps({"content": message[:1990], "flags": 4}).encode()
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
    if "--candidate-spec-hook" in sys.argv:
        raise SystemExit(_run_candidate_spec_hook())
    results_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path.home() / ".vh-search-results" / "linkedin_rps")
    results = json.loads(Path(results_path).read_text())
    passers = eligible(results, "linkedin_rps")  # 이 러너 경로는 LinkedIn RPS 포지션(학교컷 미적용 채널)
    print(f"eligible passers: {len(passers)}")
    for r in passers:
        print(" ", r["score"], r["name"], r["url"])
    if "--send" in sys.argv:
        if "--clickup-register" in sys.argv:
            raise RuntimeError(
                "ClickUp FY26AI_Search registration requires duplicate-check capable "
                "clickup_search_tasks/clickup_create_task adapters; legacy comment body output is blocked."
            )
        status = post_discord(build_message(passers))
        print("discord status:", status)
        print("clickup FY26AI_Search registration skipped: use register_clickup_fy26_ai_search with duplicate-check adapters")
