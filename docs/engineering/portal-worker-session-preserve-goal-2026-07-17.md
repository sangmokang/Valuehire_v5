# Goal — portal_worker.stop() 세션 보존 (SOT-28 TODO-2, 현상6 "로그인됐는데 꺼짐")

## 현재 상태 (직접 확인)
- `tools/multi_position_sourcing/portal_worker.py:656-670` (수정 전): `stop()` 이
  `channel != "linkedin_rps"` 이면 `await self._context.close()` 호출 → 사람인·잡코리아의
  로그인 세션이 담긴 persistent context(탭/창)가 통째로 닫힘.
- SOT-28 §12 현상6 판정 ⛔: 가드(`guards/login.py`)는 러너 내부 close 를 원리적으로 못 막음
  (argv 문자열 가드 사각) → 유일 방어 = 이 코드 수정.

## 인수 기준 (기계 검사)
1. saramin/jobkorea 채널에서 `start()`→`stop()` 후 `context.close()` 호출 0회.
2. linkedin_rps 무-close 회귀 봉인.
3. `stop()` 의 프로필 lock 해제는 유지(재획득 가능). 같은 프로필 재-launch 는
   실제 playwright 의미론상 미지원("already in use") — 재접속은 TODO-2b CDP 재부착으로.
4. 전체 verify exit 0, 기존 단언 삭제 0 (옛 계약 단언 2건은 새 계약으로 반전·카나리아화만).
5. v4 `.claude/hooks/tests/test_login_guard.py` 29/29 유지.

## 비범위 / 정직한 한계 (후속)
- 워커가 playwright manager 를 스스로 만든 경우, `stop()` 의 manager `__aexit__` 이나
  파이썬 프로세스 종료 시 playwright 드라이버가 내려가면 그 드라이버가 띄운
  persistent Chrome 이 함께 종료될 수 있다 — context.close() 제거만으로는
  "프로세스 수명 너머" 세션 보존이 완성되지 않는다. 완성형은 SOT-28 §2b ①
  (portal_browsers.sh 가 띄운 크롬에 CDP attach) 로의 채널 이행이며 별도 TODO.
- 실기기 플릿 재기동 라이브 검증은 사장님 로그인 세션 리스크로 이번엔 보류(수동 판정 필요).

## 적대 검증 로그
- `portal-worker-session-preserve.verdict.json` 참조 (G/V1/V2).
