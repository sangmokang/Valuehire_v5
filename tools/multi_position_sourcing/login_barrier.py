"""login_barrier — 로그인 선행 장벽 단일 검증기 (이슈 #639, 프롬프트 2026-07-25).

계약: v4 docs/engineering/login-first-claude-discord-harness-hook-prompt-2026-07-25.md
- Claude 직접 실행과 Discord queue/worker 가 같은 영수증 validator 를 쓴다.
- 모델 출력 문구("LOGIN_BARRIER=PASS")는 신뢰하지 않는다 — 파일(JSON) 검증만.
- 전 항목 fail-closed: 표에 없는 입력은 전부 명시적 거부.

영수증 저장 위치(기본): ~/.valuehire/login_receipts/<channel>.json
(v4/v5 공용 — login_multidevice 의 ~/.valuehire 관례. env VH_LOGIN_RECEIPT_DIR 우선.)
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

RECEIPT_SCHEMA_VERSION = 1
RECEIPT_MAX_AGE_SECONDS = 1800  # 사람인·잡코리아 서버세션 20~30분(SOT-26 §4) — 보수값
CHANNELS = ("saramin", "jobkorea", "linkedin_rps")
COMMANDS = ("login", "aisearch", "humansearch", "url")
AISEARCH_DEFAULT_CHANNELS = ("saramin", "jobkorea")  # 기존 G4 기본값 유지

_ALIAS_TO_COMMAND = {
    "$login": "login", "/login": "login", "login": "login",
    "$ai-search": "aisearch", "$aisearch": "aisearch",
    "/ai-search": "aisearch", "/aisearch": "aisearch",
    "ai-search": "aisearch", "aisearch": "aisearch",
    "$humansearch": "humansearch", "/humansearch": "humansearch",
    "humansearch": "humansearch",
    "$url": "url", "/url": "url", "url": "url",
}

_SECRET_KEY_MARKERS = (
    "password", "passwd", "cookie", "token", "secret", "credential", "li_at",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EVIDENCE_PATH_FIELDS = ("screenshot_path", "text_path", "manifest_path")
_REASON_CODES = {
    "RECEIPT_MISSING", "STALE_RECEIPT", "CLOCK_SKEW", "HOST_MISMATCH",
    "EVIDENCE_MISSING", "HASH_MISMATCH", "CHANNEL_BLOCKED",
}


def _canonical_hash(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "integrity_sha256"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def seal_channel_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(receipt)
    sealed["integrity_sha256"] = _canonical_hash(sealed)
    return sealed


def _evidence_sha256(path: str) -> str | None:
    candidate = Path(path)
    try:
        if candidate.is_symlink() or not candidate.is_file():
            return None
        if candidate.stat().st_size > 25 * 1024 * 1024:
            return None
        return hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError:
        return None


def receipt_reason_code(reason: str | None) -> str | None:
    if reason is None:
        return None
    prefix = reason.split(":", 1)[0]
    if prefix in _REASON_CODES:
        return prefix
    if "증거 파일" in reason:
        return "EVIDENCE_MISSING"
    if "영수증 없음" in reason:
        return "RECEIPT_MISSING"
    return "CHANNEL_BLOCKED"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate receipt key: {key}")
        result[key] = value
    return result


def default_receipt_dir() -> Path:
    """영수증 디렉토리 — env VH_LOGIN_RECEIPT_DIR 우선, 기본 ~/.valuehire/login_receipts."""
    override = os.environ.get("VH_LOGIN_RECEIPT_DIR", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".valuehire" / "login_receipts"


def normalize_command(text: Any) -> str | None:
    """메시지 맨 앞의 정확한 별칭만 command enum 으로. 그 외 전부 None(비명령)."""
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped:
        return None
    first = stripped.split(None, 1)[0].lower()
    return _ALIAS_TO_COMMAND.get(first)


def _normalize_channel(name: Any) -> str:
    raw = str(name or "").strip().lower()
    if raw in ("linkedin", "linkedin_rps"):
        return "linkedin_rps"
    if raw in ("saramin", "jobkorea"):
        return raw
    raise ValueError(f"알 수 없는 로그인 채널: {name!r}")


def required_channels(
    command: str,
    *,
    channels: Any = None,
    params: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """명령별 필수 로그인 채널. 빈 channels 는 '로그인 불필요'가 아니다 — 기본값
    복구(aisearch) 또는 입력 오류(humansearch)로 처리한다(프롬프트 계약)."""
    if command == "login":
        return CHANNELS
    if command == "url":
        return ("linkedin_rps",)
    if command == "humansearch":
        if not channels:
            raise ValueError("humansearch 는 channels 명시가 필수(빈 값 = 입력 오류)")
        return tuple(dict.fromkeys(_normalize_channel(c) for c in channels))
    if command == "aisearch":
        raw = channels or (params or {}).get("channels")
        if not raw:
            return AISEARCH_DEFAULT_CHANNELS
        return tuple(dict.fromkeys(_normalize_channel(c) for c in raw))
    raise ValueError(f"알 수 없는 command: {command!r}")


def _contains_secret_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, sub in value.items():
            low = str(key).lower()
            if any(marker in low for marker in _SECRET_KEY_MARKERS):
                return True
            if _contains_secret_key(sub):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_secret_key(v) for v in value)
    return False


def validate_channel_receipt(
    receipt: Any,
    *,
    channel: str,
    machine: str,
    now_epoch: float,
    expected_target_id: str | None = None,
) -> str | None:
    """영수증 1건 fail-closed 검증 — 차단 사유 문자열 or None(유효)."""
    if not isinstance(receipt, Mapping):
        return "영수증 형식 오류(JSON object 아님)"
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return "CHANNEL_BLOCKED: schema_version 불일치"
    if _contains_secret_key(receipt):
        return "CHANNEL_BLOCKED: 영수증에 비밀값 성격 키 포함"
    integrity = str(receipt.get("integrity_sha256") or "")
    if not _SHA256_RE.fullmatch(integrity) or integrity != _canonical_hash(receipt):
        return "HASH_MISMATCH: receipt integrity"
    state = receipt.get("state")
    if state in ("HUMAN_AUTH", "HUMAN_AUTH_REQUIRED", "AUTH_CONFLICT"):
        return f"CHANNEL_BLOCKED: {state} 화면"
    if state != "AUTHENTICATED":
        return f"CHANNEL_BLOCKED: state 미인증({state!r})"
    if receipt.get("ready") is not True:
        return "ready != true"
    if str(receipt.get("channel") or "") != channel:
        return f"채널 불일치(요청={channel}, 영수증={receipt.get('channel')!r})"
    if str(receipt.get("host") or "") != str(machine):
        return f"HOST_MISMATCH: current={machine}"
    raw_ts = receipt.get("last_verified_at")
    if not isinstance(raw_ts, str) or not raw_ts.strip():
        return "last_verified_at 없음"
    try:
        dt = datetime.fromisoformat(raw_ts.strip().replace("Z", "+00:00"))
    except ValueError:
        return "last_verified_at 형식 오류"
    if dt.tzinfo is None:
        return "last_verified_at 에 시간대 없음(신뢰 불가)"
    age = float(now_epoch) - dt.timestamp()
    if age < 0:
        return f"CLOCK_SKEW: future receipt(age={age:.0f}s)"
    if age > RECEIPT_MAX_AGE_SECONDS:
        return f"STALE_RECEIPT: age={age:.0f}s"
    if receipt.get("owner_activity_detected") is not False:
        return "owner_activity_detected != false"
    if not str(receipt.get("target_id") or "").strip():
        return "target_id 없음"
    if (
        expected_target_id is not None
        and str(receipt.get("target_id")) != str(expected_target_id)
    ):
        return "HOST_MISMATCH: exact target mismatch"
    proofs = receipt.get("proof_names")
    if (not isinstance(proofs, list) or not proofs
            or not all(isinstance(p, str) and p.strip() for p in proofs)):
        return "proof_names(사이트별 fresh DOM 성공 마커) 없음"
    if receipt.get("mutation_count") != 0:
        return "mutation_count != 0"
    if receipt.get("capture_status") != "saved":
        return "capture_status != saved"
    for field in _EVIDENCE_PATH_FIELDS:
        path = str(receipt.get(field) or "")
        if not path or not os.path.isfile(path):
            return f"EVIDENCE_MISSING: {field}"
    for field in ("screenshot_sha256", "text_sha256", "manifest_sha256"):
        if not _SHA256_RE.fullmatch(str(receipt.get(field) or "")):
            return f"HASH_MISMATCH: {field} format"
    for path_field, hash_field in (
        ("screenshot_path", "screenshot_sha256"),
        ("text_path", "text_sha256"),
        ("manifest_path", "manifest_sha256"),
    ):
        actual = _evidence_sha256(str(receipt[path_field]))
        if actual is None:
            return f"EVIDENCE_MISSING: {path_field}"
        if actual != receipt[hash_field]:
            return f"HASH_MISMATCH: {path_field}"
    return None


def load_receipts(receipt_dir: Path | str) -> tuple[dict[str, Any], str | None]:
    """<dir>/*.json 전부 읽기 → (채널→영수증, 치명 사유).

    같은 채널을 주장하는 파일이 2개면 모순 가능 — 전역 차단 사유 반환.
    개별 파일 파싱 실패는 그 파일을 '깨진 영수증'으로 채널에 남긴다(fail-closed).
    """
    rdir = Path(receipt_dir)
    by_channel: dict[str, Any] = {}
    if not rdir.is_dir():
        return {}, None
    for path in sorted(rdir.glob("*.json")):
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_keys,
            )
        except (OSError, ValueError):
            payload = None
        channel = ""
        if isinstance(payload, Mapping):
            channel = str(payload.get("channel") or "").strip()
        if not channel:
            # 채널 불명 파일은 무시하지 않고 파일명 기반으로 fail-closed 자리 차지
            channel = path.stem.split("-")[0].split(".")[0]
        if channel in by_channel:
            return {}, f"{channel} 로그인 영수증 파일 중복(모순 가능) — 전체 차단"
        by_channel[channel] = payload
    return by_channel, None


def evaluate_barrier(
    command: str,
    *,
    machine: str,
    now_epoch: float,
    receipt_dir: Path | str | None = None,
    channels: Any = None,
    params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """전역 장벽 판정 — {"barrier": "PASS"|"BLOCKED", "required": [...], "reasons": {...}}.

    PASS 는 필수 채널 전부의 영수증이 코드 검증을 통과할 때만. 그 외 전부 BLOCKED.
    """
    def decision(required: tuple[str, ...], details: dict[str, str | None]) -> dict[str, Any]:
        passed = bool(required) and all(value is None for value in details.values())
        codes = [
            code for code in dict.fromkeys(
                receipt_reason_code(details.get(channel)) for channel in required
            ) if code is not None
        ]
        state = "PASS" if passed or not required else "BLOCKED"
        return {
            "barrier": state,
            "state": state,
            "required": list(required),
            "reasons": details,
            "required_channels": list(required),
            "reason_codes": codes,
        }

    try:
        required = required_channels(command, channels=channels, params=params)
    except ValueError as exc:
        return {
            "barrier": "BLOCKED", "required": [], "reasons": {"_input": str(exc)},
            "state": "BLOCKED", "required_channels": [],
            "reason_codes": ["CHANNEL_BLOCKED"],
        }
    rdir = Path(receipt_dir) if receipt_dir is not None else default_receipt_dir()
    receipts, fatal = load_receipts(rdir)
    reasons: dict[str, str | None] = {}
    if fatal:
        for ch in required:
            reasons[ch] = fatal
        return decision(required, reasons)
    for ch in required:
        if ch not in receipts:
            reasons[ch] = "로그인 영수증 없음"
            continue
        reasons[ch] = validate_channel_receipt(
            receipts[ch], channel=ch, machine=machine, now_epoch=now_epoch)
    return decision(required, reasons)


def job_required_channels(job: Mapping[str, Any]) -> tuple[str, ...]:
    """fleet 잡의 포털 채널 — 기존 G4 계약 유지(public_web 등 비포털만이면 게이트 미적용)."""
    skill = str(job.get("skill") or "")
    if skill == "url":
        return ("linkedin_rps",)
    if skill in ("humansearch", "aisearch"):
        raw = (job.get("params") or {}).get("channels") or list(AISEARCH_DEFAULT_CHANNELS)
        mapped = []
        for ch in raw:
            try:
                mapped.append(_normalize_channel(ch))
            except ValueError:
                continue  # 비포털 채널(public_web 등)은 로그인 대상 아님
        return tuple(dict.fromkeys(mapped))
    return ()


def job_block_reason(
    job: Mapping[str, Any],
    *,
    machine: str,
    now_epoch: float,
    receipt_dir: Path | str | None = None,
) -> str | None:
    """fleet worker 1층 장벽 — 차단이면 채널별 사유 요약 문자열, 통과면 None."""
    required = job_required_channels(job)
    if not required:
        return None
    rdir = Path(receipt_dir) if receipt_dir is not None else default_receipt_dir()
    receipts, fatal = load_receipts(rdir)
    if fatal:
        return fatal
    failures = []
    params = job.get("params") if isinstance(job.get("params"), Mapping) else {}
    expected_targets = dict(
        params.get("expected_target_ids")
        if isinstance(params.get("expected_target_ids"), Mapping) else {}
    )
    route = params.get("route_decision")
    if isinstance(route, Mapping):
        for ref in route.get("evidence_refs") or []:
            if not isinstance(ref, str):
                continue
            prefix = f"receipt:{machine}:"
            target_prefix = f"target:{machine}:"
            if ref.startswith(prefix) or ref.startswith(target_prefix):
                expected_targets.setdefault("linkedin_rps", ref.rsplit(":", 1)[-1])
    for ch in required:
        if ch not in receipts:
            failures.append(f"{ch}: 로그인 영수증 없음")
            continue
        reason = validate_channel_receipt(
            receipts[ch], channel=ch, machine=machine, now_epoch=now_epoch,
            expected_target_id=expected_targets.get(ch),
        )
        if reason is not None:
            failures.append(f"{ch}: {reason}")
    if failures:
        return "; ".join(failures)
    return None


def write_channel_receipt_from_episode(
    episode: Mapping[str, Any],
    *,
    machine: str,
    receipt_dir: Path | str | None = None,
    now_epoch: float | None = None,
) -> str | None:
    """session_guard human-auth/capture-evidence 성공 결과 → 채널 영수증 파일.

    status=authenticated 가 아니면 아무것도 쓰지 않는다(None). 비밀값은 받지 않는다.
    """
    if not isinstance(episode, Mapping) or episode.get("status") != "authenticated":
        return None
    if not str(machine).strip():
        return None  # 기기 식별 없이 만든 영수증은 host 검증을 우회할 수 있어 금지
    site = str(episode.get("site") or "").strip()
    if site not in CHANNELS:
        return None
    evidence = episode.get("evidence")
    if not isinstance(evidence, Mapping):
        return None
    from datetime import timezone as _tz
    if now_epoch is None:
        ts = datetime.now(_tz.utc)
    else:
        ts = datetime.fromtimestamp(float(now_epoch), tz=_tz.utc)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "channel": site,
        "state": "AUTHENTICATED",
        "ready": True,
        "host": str(machine),
        "target_id": str(evidence.get("target_id") or episode.get("target_id") or ""),
        "last_verified_at": ts.isoformat(),
        "owner_activity_detected": False,
        "proof_names": [str(p) for p in (episode.get("proof_names") or []) if str(p).strip()],
        "mutation_count": 0,
        "capture_status": str(evidence.get("capture_status") or ""),
        "screenshot_path": str(evidence.get("screenshot_path") or ""),
        "text_path": str(evidence.get("text_path") or ""),
        "manifest_path": str(evidence.get("manifest_path") or ""),
        "screenshot_sha256": str(evidence.get("screenshot_sha256") or ""),
        "text_sha256": str(
            evidence.get("text_sha256") or evidence.get("visible_text_sha256") or ""),
        "manifest_sha256": str(
            evidence.get("manifest_sha256")
            or _evidence_sha256(str(evidence.get("manifest_path") or ""))
            or ""
        ),
    }
    receipt = seal_channel_receipt(receipt)
    # 자기 검증: 쓰기 전에 같은 validator 를 통과 못 하면 쓰지 않는다(fail-closed).
    if validate_channel_receipt(
            receipt, channel=site, machine=str(machine),
            now_epoch=ts.timestamp()) is not None:
        return None
    rdir = Path(receipt_dir) if receipt_dir is not None else default_receipt_dir()
    rdir.mkdir(parents=True, exist_ok=True)
    target = rdir / f"{site}.json"
    fd, tmp_name = tempfile.mkstemp(dir=str(rdir), prefix=f".{site}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(receipt, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_name, target)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return None
    return str(target)
