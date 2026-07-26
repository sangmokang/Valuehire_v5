"""login_barrier — 로그인 선행 장벽 단일 검증기 (이슈 #639, 프롬프트 2026-07-25).

계약: v4 docs/engineering/login-first-claude-discord-harness-hook-prompt-2026-07-25.md
- Claude 직접 실행과 Discord queue/worker 가 같은 영수증 validator 를 쓴다.
- 모델 출력 문구("LOGIN_BARRIER=PASS")는 신뢰하지 않는다 — 파일(JSON) 검증만.
- 전 항목 fail-closed: 표에 없는 입력은 전부 명시적 거부.

영수증 저장 위치(기본): ~/.valuehire/login_receipts/<channel>.json
(v4/v5 공용 — login_multidevice 의 ~/.valuehire 관례. env VH_LOGIN_RECEIPT_DIR 우선.)
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

RECEIPT_SCHEMA_VERSION = 1
RECEIPT_MAX_AGE_SECONDS = 1800  # 사람인·잡코리아 서버세션 20~30분(SOT-26 §4) — 보수값
CLOCK_SKEW_SECONDS = 60
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
) -> str | None:
    """영수증 1건 fail-closed 검증 — 차단 사유 문자열 or None(유효)."""
    if not isinstance(receipt, Mapping):
        return "영수증 형식 오류(JSON object 아님)"
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        return "schema_version 불일치"
    if _contains_secret_key(receipt):
        return "영수증에 비밀값 성격 키 포함(secret_material) — 저장 금지 계약 위반"
    state = receipt.get("state")
    if state == "HUMAN_AUTH":
        proof_names = receipt.get("proof_names")
        if (
            receipt.get("challenge_verified") is True
            and receipt.get("challenge_type") in ("captcha", "2fa", "checkpoint")
            and isinstance(proof_names, list)
            and proof_names
            and all(isinstance(proof, str) and proof.strip() for proof in proof_names)
            and str(receipt.get("target_id") or "").strip()
        ):
            return f"HUMAN_AUTH: verified {receipt.get('challenge_type')} challenge"
        return "사람 인증 양성 증거 없음"
    if state == "AUTH_CONFLICT":
        proof_names = receipt.get("proof_names")
        if (
            receipt.get("conflict_verified") is True
            and receipt.get("conflict_type") in (
                "multiple_authenticated_machines",
                "linkedin_multiple_signins",
            )
            and isinstance(receipt.get("authenticated_machine_count"), int)
            and not isinstance(receipt.get("authenticated_machine_count"), bool)
            and receipt.get("authenticated_machine_count") >= 2
            and isinstance(proof_names, list)
            and proof_names
            and all(isinstance(proof, str) and proof.strip() for proof in proof_names)
        ):
            return f"AUTH_CONFLICT: verified {receipt.get('conflict_type')}"
        return "다중 로그인 충돌 양성 증거 없음"
    if state != "AUTHENTICATED":
        return f"state 미인증({state!r})"
    if receipt.get("ready") is not True:
        return "ready != true"
    if str(receipt.get("channel") or "") != channel:
        return f"채널 불일치(요청={channel}, 영수증={receipt.get('channel')!r})"
    if str(receipt.get("host") or "") != str(machine):
        return f"host 불일치(현재={machine}, 영수증={receipt.get('host')!r})"
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
    if age < -CLOCK_SKEW_SECONDS:
        return f"미래 시각 영수증(age={age:.0f}s)"
    if age > RECEIPT_MAX_AGE_SECONDS:
        return f"영수증 만료(age={age:.0f}s > {RECEIPT_MAX_AGE_SECONDS}s)"
    if receipt.get("owner_activity_detected") is not False:
        return "owner_activity_detected != false"
    if not str(receipt.get("target_id") or "").strip():
        return "target_id 없음"
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
            return f"증거 파일 없음({field})"
    for field in ("screenshot_sha256", "text_sha256"):
        if not _SHA256_RE.fullmatch(str(receipt.get(field) or "")):
            return f"{field} 형식 오류"
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
            payload = json.loads(path.read_text(encoding="utf-8"))
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
    try:
        required = required_channels(command, channels=channels, params=params)
    except ValueError as exc:
        return {"barrier": "BLOCKED", "required": [], "reasons": {"_input": str(exc)}}
    rdir = Path(receipt_dir) if receipt_dir is not None else default_receipt_dir()
    receipts, fatal = load_receipts(rdir)
    reasons: dict[str, str | None] = {}
    if fatal:
        for ch in required:
            reasons[ch] = fatal
        return {"barrier": "BLOCKED", "required": list(required), "reasons": reasons}
    for ch in required:
        if ch not in receipts:
            reasons[ch] = "로그인 영수증 없음"
            continue
        reasons[ch] = validate_channel_receipt(
            receipts[ch], channel=ch, machine=machine, now_epoch=now_epoch)
    barrier = "PASS" if required and all(v is None for v in reasons.values()) else "BLOCKED"
    if not required:
        barrier = "PASS"  # 포털 채널 무관 명령은 장벽 미적용(호출부가 스킬로 선별)
    return {"barrier": barrier, "required": list(required), "reasons": reasons}


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
    for ch in required:
        if ch not in receipts:
            failures.append(f"{ch}: 로그인 영수증 없음")
            continue
        reason = validate_channel_receipt(
            receipts[ch], channel=ch, machine=machine, now_epoch=now_epoch)
        if reason is not None:
            failures.append(f"{ch}: {reason}")
    if failures:
        return "; ".join(failures)
    return None


def classify_job_block_reason(reason: str | None) -> str:
    """Map barrier evidence to one non-overlapping terminal state.

    AUTH_CONFLICT always wins. HUMAN_AUTH is allowed only when every failed
    channel has positive HUMAN_AUTH evidence. Missing, malformed, mixed, and
    unknown evidence fail closed as HANDOFF.
    """
    if reason is None:
        return "PASS"
    failures = [part.strip() for part in str(reason).split(";") if part.strip()]
    if any("AUTH_CONFLICT" in failure for failure in failures):
        return "AUTH_CONFLICT"
    if failures and all("HUMAN_AUTH" in failure for failure in failures):
        return "HUMAN_AUTH"
    return "HANDOFF"


def human_auth_channels(reason: str | None) -> tuple[str, ...]:
    """Return only channels with positive HUMAN_AUTH evidence."""
    channels: list[str] = []
    for failure in str(reason or "").split(";"):
        channel, separator, detail = failure.strip().partition(":")
        if separator and "HUMAN_AUTH" in detail and channel in CHANNELS:
            channels.append(channel)
    return tuple(dict.fromkeys(channels))


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
    }
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
