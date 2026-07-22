from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOAL = ROOT / "docs/prompts/discord-single-bot-console-goal-2026-07-22.md"
EXEC = ROOT / "docs/prompts/discord-single-bot-console-exec-prompts-2026-07-22.md"
SOT = ROOT / "docs/sot/33-hermes-retirement.md"

PHASES = tuple(f"HR-{index}" for index in range(8))
RECEIPT_FIELDS = (
    "schema_version",
    "git_sha_v4",
    "git_sha_v5",
    "phase",
    "discord_bot_id",
    "command_fingerprint",
    "direct_gateway_pid",
    "direct_gateway_lease_id",
    "hermes_pid_count",
    "hermes_launchctl_count",
    "queue_nonterminal_count",
    "claude_job_id",
    "claude_response_id",
    "codex_job_id",
    "codex_response_id",
    "duplicate_response_count",
    "quarantine_paths",
    "remaining_runtime_references",
    "rollback_tested",
    "verified_at",
    "verifier_sha256",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"missing contract surface: {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def test_sot33_and_prompts_define_eight_separate_retirement_phases() -> None:
    for path in (SOT, GOAL, EXEC):
        text = _read(path)
        for phase in PHASES:
            assert phase in text, (path, phase)

    exec_text = _read(EXEC)
    assert "한 작업방에는 인수 기준 하나만" in exec_text
    assert "AC-8 — 헤르메스 폐기" not in exec_text


def test_retirement_contract_preserves_direct_gateway_before_destructive_work() -> None:
    text = _read(SOT)
    required = (
        "Discord 입력",
        "단일 direct gateway",
        "자연어/슬래시 해석",
        "영속 큐",
        "fleet worker",
        "Claude Code 또는 Codex",
        "원 요청자에게 결과 회신",
        "새 직결 봇 실증 전에 Hermes를 중단하거나 삭제하지 않는다",
        "봇 토큰당 활성 gateway는 정확히 1개",
        "queued/running/paused_for_human",
        "Claude 실작업 1건",
        "Codex 실작업 1건",
        "Hook만 믿지 않는다",
        "생산 코드의 기동 게이트",
    )
    for marker in required:
        assert marker in text, marker


def test_hr0_inventory_is_exhaustive_and_unknown_is_forbidden() -> None:
    text = _read(SOT)
    for marker in (
        "/Volumes/SSD/valuehire_v4/tools/hermes-agent/",
        "/Volumes/SSD/valuehire_v5/ops/hermes-plugin/",
        "hermes_fleet_bridge.py",
        "hermes_position_context.py",
        "scripts/discord_command_listener.py",
        "~/.hermes/plugins/",
        "~/Library/LaunchAgents/ai.hermes.gateway.plist",
        "live caller",
        "historical-only",
        "removable",
        "UNKNOWN이 0",
    ):
        assert marker in text, marker


def test_live_acceptance_and_atomic_cutover_have_receipts_and_rollback() -> None:
    text = _read(SOT)
    for marker in (
        "gateway lease_id",
        "event_id",
        "job_id",
        "Discord response_id",
        "queued → running → done",
        "Hermes 응답과 직결 봇 응답이 동시에 오는 경우 즉시 FAIL",
        "현재 Discord 명령 payload를 백업",
        "Hermes gateway를 launchctl bootout",
        "Discord 명령 payload를 백업본으로 복구",
        "Hermes gateway를 다시 올린다",
        "rollback",
    ):
        assert marker in text, marker


def test_quarantine_and_24_hour_soak_are_recoverable_and_secret_safe() -> None:
    text = _read(SOT)
    for marker in (
        "quarantine",
        "권한 0700",
        "24시간",
        "Hermes PID 0",
        "중복 응답 0",
        "lease 위반 0",
        "SHA-256 지문",
        "service-role 키를 직결 gateway에 제공하지 않는다",
        "휴지통 등 복구 가능한 방식",
    ):
        assert marker in text, marker
    assert "~/.hermes 같은 넓은 경로를 rm -rf로 삭제하지 않는다" in text
    assert "~/.hermes 전체를 tar 로 백업한 뒤 삭제" not in _read(GOAL)
    assert "~/.hermes 전체를 tar 로 백업한 뒤 삭제" not in _read(EXEC)


def test_required_hooks_stop_gate_and_machine_receipt_are_complete() -> None:
    surfaces = "\n".join((_read(SOT), _read(GOAL), _read(EXEC)))
    for marker in (
        ".claude/hooks/guards/discord-e2e-cutover.py",
        ".claude/hooks/guards/hermes-retirement.py",
        "artifacts/discord-cutover/hermes-retirement-receipt.json",
        "launchctl label 0",
        "플러그인 심링크 0",
        "direct gateway lease 1",
        "reboot 후 유령 재기동 0",
        "rollback 검증 결과",
    ):
        assert marker in surfaces, marker
    for field in RECEIPT_FIELDS:
        assert field in surfaces, field


def test_final_claim_is_fail_closed_until_every_proof_exists() -> None:
    text = _read(SOT)
    for marker in (
        "Hermes 생산 코드 호출자 0",
        "Claude와 Codex 실제 실행·결과 회신 성공",
        "중복 응답 0",
        "재부팅 후 Hermes 재기동 0",
        "전체 테스트 통과",
        "기계 영수증 존재",
        "Hermes 완전 폐기 완료",
    ):
        assert marker in text, marker

