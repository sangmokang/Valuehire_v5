"""strict 강화 v2의 v5 이식 계약 테스트 (단위⑥ — v4 PR#412 이식).

지시: v5 docs/prompts/strict-decompose-tdd-ladder-prompt-2026-07-19.md (v3)
- v5 SOT-30 = strict 정본(v4) 포인터 + v5 overlay(make 매핑) — 전문 복제 금지(드리프트 방지)
- 30번 충돌 정리: fleet-run-reliability는 31번으로 이동
- 옛사본(.claude/skills/strict, .claude/commands/strict.md) 제거 — 전역 미러가 로드 담당
- 기계 장치 이식: 가드 디스패처 + runner-lease 가드 + Stop 질문금지 게이트 + 리스 판정 모듈
  + 종료 등가 게이트(make strict-exit-gate)
- read-back은 v5 기존 구현(portal_worker) 존재 확인
"""
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_sot30_is_strict_pointer_with_v5_overlay():
    p = ROOT / "docs/sot/30-strict-mode-contract.md"
    assert p.is_file(), "v5 SOT-30(strict 포인터+overlay)이 없다"
    body = p.read_text(encoding="utf-8")
    # 정본 포인터 — v4 전문 복제가 아니라 참조
    assert "valuehire_v4" in body and "정본" in body
    # R1~R8 마커(요약 수준)
    for marker in ["예외 케이스 표", "질문 금지", "read-back", "재발 원장", "단위 관문", "평가 케이스", "세션 리셋"]:
        assert marker in body, f"R 마커 누락: {marker}"
    # v5 overlay — make 기반 게이트 매핑
    for marker in ["make red-ledger", "make task", "./verify.sh", "make ship"]:
        assert marker in body, f"v5 overlay 매핑 누락: {marker}"


def test_fleet_run_reliability_renumbered_to_31():
    old_name = "30-fleet" + "-run-reliability"  # 동적 조합 — 이 테스트 파일 자기매치 방지
    assert not (ROOT / f"docs/sot/{old_name}.md").exists(), "30번 충돌 잔존"
    assert (ROOT / "docs/sot/31-fleet-run-reliability.md").is_file(), "31번 이동본 없음"
    # 남은 참조 0 (추적 파일 한정 — git grep, 매치 없으면 returncode 1)
    r = subprocess.run(["git", "grep", "-l", old_name],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.stdout.strip() == "", f"옛 번호 참조 잔존: {r.stdout}"


def test_old_strict_copies_removed():
    assert not (ROOT / ".claude/skills/strict").exists(), "옛사본 스킬 잔존(전역 미러가 정본)"
    assert not (ROOT / ".claude/commands/strict.md").exists(), "옛사본 커맨드 잔존"


def test_hooks_ported_and_wired():
    for rel, marker in [
        (".claude/hooks/harness-dispatch.py", "load_guards"),
        (".claude/hooks/guards/runner-lease.py", "check_lease"),
        (".claude/hooks/stop-evidence-gate.py", "question_violation"),
        ("tools/harness/runner_lease.py", "def check_lease"),
    ]:
        p = ROOT / rel
        assert p.is_file(), f"이식 파일 없음: {rel}"
        assert marker in p.read_text(encoding="utf-8"), f"{rel} 에 '{marker}' 없음(약화)"
    settings = json.loads(read(".claude/settings.json"))
    pre = json.dumps(settings.get("hooks", {}).get("PreToolUse", []))
    assert "harness-dispatch.py" in pre, "PreToolUse 디스패처 미배선"
    assert "clickup" in pre, "기존 clickup 가드가 유실됨"
    stop = json.dumps(settings.get("hooks", {}).get("Stop", []))
    assert "stop-evidence-gate.py" in stop and "-eq 99 ] && exit 2" in stop, "Stop 게이트 미배선(99→2 승격)"


def test_exit_gate_runner_and_make_target():
    p = ROOT / "scripts/harness/strict-exit-gate.py"
    assert p.is_file(), "종료 등가 게이트 러너 없음"
    assert "PASS" in p.read_text(encoding="utf-8")
    mk = read("Makefile")
    assert re.search(r"^strict-exit-gate:", mk, re.M), "Makefile 타깃 없음"


def test_readback_already_present_in_portal_worker():
    body = read("tools/multi_position_sourcing/portal_worker.py")
    assert "readback" in body, "v5 read-back(포털 워커) 소실"


def test_recurrence_ledger_pointer():
    body = read("docs/sot/30-strict-mode-contract.md")
    assert "31-strict-recurrence-ledger" in body, "재발 원장(v4 SOT-31) 참조 없음"
