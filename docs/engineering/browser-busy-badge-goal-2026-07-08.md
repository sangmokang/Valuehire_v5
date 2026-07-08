# goal: 자동화가 브라우저 점유 중이면 화면에 "사용중" 표시 (배지 오버레이)

- 날짜: 2026-07-08
- 모드: code-change / 위험등급 L2 (공유 CDP 드라이버 + 스킬/Codex 배선, 발송·파괴 없음, 투명성 강화)

## 요구 (사장님)
자동화(Claude/Codex)가 브라우저를 점유해 서치를 돌리는 동안, **그 화면에 "내가 쓰는 중"이라고 표시**.
모든 서치(/url·/aisearch·/humansearch 등)와 **Codex에서도** 동일하게.

## 현재 상태 (직접 확인한 file:line)
- 모든 raw CDP 서치의 공통 드라이버 = `tools/multi_position_sourcing/raw_cdp.py` `CDPTab`(`.eval`=Runtime.evaluate).
  - humansearch: `humansearch_cdp_run.py:423 tab = cdp.attach(t)`. /url·/aisearch 도 raw CDP attach 사용.
- 점유 감지/양보: `owner_activity.py`(detect_owner_activity_snapshot). 배지와 직교(양보 시 배지 제거로 연동).
- 기존 배지/오버레이 표시 기능: **없음**(신규).

## 근본 방식
공통 진입점 `attach()` 가 붙는 즉시 화면에 배지를 주입 → 이 한 곳만 지나면 모든 서치가 자동 표시.
Codex 도 같은 repo `attach()` 를 쓰므로 동일하게 뜬다(who 는 env 로 구분).

## 계약 (스펙 · 입출력)
```
# 순수 헬퍼
_resolve_badge_label(env: Mapping[str,str]) -> str | None
  # VH_BADGE_OFF truthy -> None(표시 안 함)
  # 아니면 "🤖 {agent} 자동화 사용중 · {task}"  (task 없으면 " · {task}" 생략)
  #   agent = env.VH_BUSY_AGENT or "Claude";  task = env.VH_BUSY_TASK or ""
_badge_js(label: str) -> str    # #vh-automation-badge div 주입 JS(idempotent: 기존 제거 후 생성)
_clear_js() -> str              # #vh-automation-badge 제거 JS

# CDPTab
tab.mark_busy(label)  # self._badge_label=label; best-effort eval(_badge_js). eval 실패해도 예외 안 냄(라벨은 기억)
tab.clear_badge()     # self._badge_label=None; best-effort eval(_clear_js)
tab.navigate(url)     # 기존 + 페이지 로드 후 self._badge_label 있으면 배지 재주입(로드로 지워지므로)
tab.close()           # 배지 제거 시도 후 ws close

attach(target, badge=True) -> CDPTab
  # badge True 면 _maybe_auto_badge(tab, os.environ): label=_resolve_badge_label(env); label 있으면 tab.mark_busy(label)
```
DOM 계약: `id=vh-automation-badge`, `position:fixed`(상단중앙), `pointer-events:none`(사장님 클릭 방해 금지),
아주 큰 z-index, 텍스트에 agent + "사용중" 포함.

## 인수 기준 (기계 단언)
1. `_resolve_badge_label`: agent/task env 반영, 기본값 Claude, VH_BADGE_OFF 시 None.
2. `_badge_js`: id=vh-automation-badge · position:fixed · pointer-events:none · 라벨텍스트 포함 · 기존요소 제거(idempotent).
3. `mark_busy` 후 `navigate` 하면 배지가 **재주입**된다(페이지 로드로 사라지는 문제 방지).
4. 배지 주입 중 eval 예외가 나도 **mark_busy/navigate 가 예외를 던지지 않는다**(실 서치를 절대 안 깬다).
5. `attach(badge=True)` + env(VH_BUSY_AGENT) → tab.mark_busy 호출. VH_BADGE_OFF 면 미호출.

## 적용 게이트
harness 0~6, worktree, RED→GREEN, verify, 배선 grep(attach→humansearch), V1.

## 적대검증 정조준
- 배지 실패가 서치를 깨지 않는가(try/except 범위).
- navigate 재주입이 무한/과다 아닌가.
- pointer-events:none 으로 사장님 조작을 진짜 안 막는가.
- Codex 경로가 실제로 같은 attach 를 타는가(문서 배선).

## 비범위
- 양보(pause) 시 "대기중" 상태 표시 문구 세분화(MVP: 양보 시 clear).
- MCP claude-in-chrome 폴백 경로(주력 raw CDP 우선).

## 적대 검증 로그
- G(Claude): raw_cdp.attach 자동배지 + mark_busy/clear/navigate 재주입/close 제거. RED(11 fail)→GREEN(12). mutant(best-effort 제거)→안전테스트 FAIL로 가짜GREEN 배제. 라이브: 실제 talent search 화면에 배지 육안 확인(스크린샷) + pointer-events:none + clear 제거.
- V1(fresh Claude, agentId a759020651179b180): verdict **pass**. 6개 공격 각도 전부 실제 실행으로 시도했으나 못 깸 — 예외안전(죽은 eval/ws SAFE)·JS 이스케이프(node --check)·idempotent·기존 attach 호출부 무영향·navigate 1회 재주입·회귀 19통과. auto_send 기본배지는 SOT 투명성과 일치(버그 아님, VH_BADGE_OFF 로 끔).
- T: verify.sh 1146 passed, 4 xfailed, exit 0.
- 3자 일치(G/V1/T). L2 통과.
