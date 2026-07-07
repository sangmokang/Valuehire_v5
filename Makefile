# Valuehire_v5 — Harness 표준 작업 루프 배관
# 사용법: docs/harness.md (Gate 0 → 1 스펙 → 2 RED → 3 구현 → 4 verify → 5 ship → Gate 6)
SHELL := /bin/bash
.PHONY: help verify red-ledger task ship install-hooks codex-sync codex-sync-dry

help:
	@echo "make verify         — 게이트 4: ./verify.sh (테스트 전체, exit 0 == GREEN)"
	@echo "make red-ledger     — 게이트 0: 미해결 RED 점검 (있으면 비-0)"
	@echo "make task NAME=slug  — 게이트 2: worktree 생성 + ledger에 RED 등록"
	@echo "make ship            — 게이트 5: verify 재실행 → push → PR"
	@echo "make install-hooks   — pre-push 훅을 .git/hooks 에 설치"
	@echo "make codex-sync      — Claude 스킬을 Codex(~/.codex/skills)로 동기화"
	@echo "make codex-sync-dry  — 위 동기화를 모의실행(쓰지 않고 계획만 출력)"

codex-sync:
	@python3 -m tools.codex_skill_sync.sync

codex-sync-dry:
	@python3 -m tools.codex_skill_sync.sync --dry-run

verify:
	@./verify.sh

red-ledger:
	@bash scripts/harness/red-ledger.sh

task:
	@test -n "$(NAME)" || { echo "usage: make task NAME=<slug>"; exit 2; }
	@bash scripts/harness/task.sh "$(NAME)"

ship:
	@bash scripts/harness/ship.sh

install-hooks:
	@bash scripts/harness/install-hooks.sh
