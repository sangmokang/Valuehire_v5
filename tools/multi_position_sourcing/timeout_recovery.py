from __future__ import annotations

import argparse
import glob
import json
import re
from pathlib import Path
from typing import Any

from .request_parser import parse_discord_search_request

CLICKUP_RE = re.compile(r"https?://app\.clickup\.com/t/[A-Za-z0-9]+", re.IGNORECASE)
TIMEOUT_RE = re.compile(r"(?P<seconds>\d+)\s*(?:s|초|seconds?)\s*(?:제한\s*)?(?:시간\s*)?초과|timeout\D{0,12}(?P<timeout_seconds>\d+)", re.IGNORECASE)

ROBOTICS_TERMS = (
    "physical ai",
    "robotics",
    "robot",
    "ros2",
    "ros 2",
    "isaac sim",
    "isaac lab",
    "c++",
    "embedded",
    "fleet",
    "wmx",
    "nvidia",
    "jetson",
    "nav2",
    "제어",
    "로보틱스",
    "로봇",
    "전문연구요원",
)


def _find_timeout_seconds(report: str) -> int | None:
    for match in TIMEOUT_RE.finditer(report):
        value = match.group("seconds") or match.group("timeout_seconds")
        if value:
            return int(value)
    return None


def _claude_limit_detected(report: str) -> bool:
    text = report.lower()
    return "session limit" in text or "세션 한도" in report or "resets" in text


def _side_effects_zero(report: str) -> bool:
    required = ("후보자 저장: 0건", "ClickUp 기록: 0건", "Supabase 저장: 0건", "제안 발송: 0건")
    return all(item in report for item in required)


def _looks_like_physical_ai(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in ROBOTICS_TERMS)


def build_physical_ai_search_plan(position_text: str) -> dict[str, object]:
    base_keywords = (
        "Physical AI",
        "Robotics Engineer",
        "ROS2",
        "NVIDIA Isaac Sim",
        "Isaac Lab",
        "C++ embedded control",
        "fleet management system",
        "robot control",
    )
    korean_keywords = (
        "로보틱스 엔지니어",
        "ROS2 개발자",
        "로봇 제어",
        "임베디드 C++",
        "Isaac Sim",
        "Fleet management",
        "전문연구요원 로봇",
    )
    return {
        "role_family": "ai_ml",
        "target_pool": (
            "robotics software engineers",
            "embedded C/C++ robot-control engineers",
            "simulation/sim-to-real engineers",
            "AMR/fleet-management engineers",
            "NVIDIA Isaac/ROS2 package developers",
        ),
        "must_have_terms": base_keywords,
        "portal_keywords": {
            "saramin": korean_keywords,
            "jobkorea": korean_keywords,
            "linkedin_rps": base_keywords,
            "public_web": (
                'site:linkedin.com/in ("ROS2" OR "ROS 2") ("Isaac Sim" OR "Isaac Lab") Korea',
                'site:linkedin.com/in ("Physical AI" OR robotics) ("C++" OR embedded) Korea',
                'site:github.com Korea ROS2 Isaac Sim robotics C++',
                '"ROS2" "Isaac Sim" "NVIDIA Jetson" Korea robotics engineer',
                '"fleet management" ROS2 robotics engineer Korea',
            ),
        },
        "negative_filters": (
            "marketing-only",
            "sales-only",
            "mechanical-only without software/control evidence",
            "simulation-only without ROS2/C++ package evidence",
        ),
        "position_text_excerpt": position_text.strip()[:1200],
    }


def _iter_json_objects(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if "evidence_excerpt" in value or "url" in value:
            found.append(value)
        for child in value.values():
            found.extend(_iter_json_objects(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_iter_json_objects(child))
    return found


def _candidate_hint_score(candidate: dict[str, Any], terms: tuple[str, ...]) -> int:
    text = " ".join(str(candidate.get(key, "")) for key in ("evidence_excerpt", "summary", "keyword", "url")).lower()
    return sum(1 for term in terms if term.lower() in text)


def collect_local_candidate_hints(paths: list[str], *, limit: int = 5) -> list[dict[str, object]]:
    terms = ("ros", "ros2", "isaac", "jetson", "oak-d", "robot", "parcel tracking", "control", "embedded", "c++", "hardware", "fleet")
    hints: list[dict[str, object]] = []
    for path_text in paths:
        path = Path(path_text)
        if not path.exists() or not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for candidate in _iter_json_objects(data):
            score = _candidate_hint_score(candidate, terms)
            if score < 2:
                continue
            hints.append(
                {
                    "source_file": str(path),
                    "source_rank": candidate.get("source_rank", candidate.get("rank", "")),
                    "channel": candidate.get("channel", ""),
                    "profile_url": candidate.get("url", ""),
                    "local_hint_score": score,
                    "evidence_excerpt": str(candidate.get("evidence_excerpt", ""))[:900],
                    "status": candidate.get("status", "local_hint"),
                }
            )
    hints.sort(key=lambda item: int(item["local_hint_score"]), reverse=True)
    return hints[:limit]


def build_timeout_recovery_payload(
    *,
    discord_report: str,
    latest_message: str,
    local_artifact_paths: list[str] | None = None,
) -> dict[str, object]:
    parsed_request = parse_discord_search_request(latest_message)
    timeout_seconds = _find_timeout_seconds(discord_report)
    clickup_urls = tuple(dict.fromkeys(CLICKUP_RE.findall(f"{discord_report}\n{latest_message}")))
    has_physical_ai = _looks_like_physical_ai(latest_message)
    local_paths = local_artifact_paths or []
    candidate_hints = collect_local_candidate_hints(local_paths) if local_paths else []
    return {
        "mode": "timeout_recovery",
        "issue": {
            "codex_timeout_seconds": timeout_seconds,
            "codex_timed_out": timeout_seconds is not None,
            "claude_session_limited": _claude_limit_detected(discord_report),
            "side_effects_zero": _side_effects_zero(discord_report),
            "clickup_urls": clickup_urls,
        },
        "routing_decision": {
            "should_route_to_search": parsed_request.should_route_to_search,
            "has_position": parsed_request.has_position,
            "input_kind": parsed_request.input_kind,
            "reason": parsed_request.reason,
            "use_discord_text_before_clickup_fetch": parsed_request.input_kind in {"pasted_jd", "url_plus_pasted_jd"},
        },
        "engine_policy": {
            "primary": "local_bounded_strategy_then_queue",
            "codex_timeout_seconds": 180,
            "first_partial_status_seconds": 90,
            "disable_claude_until_limit_resets": _claude_limit_detected(discord_report),
            "do_not_block_on_clickup_when_pasted_jd_exists": True,
        },
        "search_plan": build_physical_ai_search_plan(latest_message) if has_physical_ai else {},
        "local_candidate_hints": candidate_hints,
        "side_effects": {
            "candidate_saved": 0,
            "clickup_written": 0,
            "supabase_written": 0,
            "outreach_sent": 0,
        },
        "operator_message": (
            "Codex 600초 timeout/Claude 한도 조합에서는 ClickUp 재조회 대신 Discord에 붙은 JD 본문으로 "
            "bounded search plan을 즉시 만들고 queue에 넘깁니다. 후보 저장/ClickUp/Supabase/제안 발송은 하지 않았습니다."
        ),
    }


def _expand_globs(patterns: list[str]) -> list[str]:
    paths: list[str] = []
    for pattern in patterns:
        matches = glob.glob(pattern)
        paths.extend(matches if matches else [pattern])
    return list(dict.fromkeys(paths))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a bounded recovery artifact for timed-out Discord Search runs.")
    parser.add_argument("--discord-report-file", required=True)
    parser.add_argument("--latest-message-file", required=True)
    parser.add_argument("--local-artifact-glob", action="append", default=[])
    parser.add_argument("--output", default="artifacts/multi_position_sourcing/timeout-recovery-latest.json")
    args = parser.parse_args()

    report = Path(args.discord_report_file).read_text(encoding="utf-8")
    latest_message = Path(args.latest_message_file).read_text(encoding="utf-8")
    payload = build_timeout_recovery_payload(
        discord_report=report,
        latest_message=latest_message,
        local_artifact_paths=_expand_globs(args.local_artifact_glob),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(output))


if __name__ == "__main__":
    main()
