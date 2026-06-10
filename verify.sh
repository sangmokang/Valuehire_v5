#!/usr/bin/env bash
# Harness 검증 게이트 (게이트 4). exit 0 == GREEN, 그 외 == 진행 중.
# 어떤 인터프리터/환경에서도 "기계 판정"이 동일하도록 pytest 보유 인터프리터를 자동 탐색한다.
set -uo pipefail
cd "$(dirname "$0")"

PY=""
for cand in ".venv-playwright/bin/python" ".venv/bin/python" "python3" "python"; do
  if "$cand" -c "import pytest" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done

if [ -z "$PY" ]; then
  echo "verify: pytest를 가진 인터프리터를 찾지 못했습니다." >&2
  echo "        python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 2
fi

echo "verify: interpreter=$PY"
"$PY" -m pytest tests/ -q
rc=$?
echo "verify: pytest exit=$rc"
exit $rc
