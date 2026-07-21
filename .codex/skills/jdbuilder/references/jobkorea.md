# 잡코리아 등록 — 채용포지션 등록

(구 `position-register` §3·§3-R·§3-R2·§3-R3 흡수, 검증된 selector 2026-06-15~2026-07-02 실측)

## 진입
`corp/person/find` → 아무 후보자 상세(`resume/view?rNo=`) → **[포지션 제안]** → 차감안내 모달 **[확인]**(`page.mouse.click` rect, JS `.click()` 안 먹음 — 차감 안내가 생략되는 케이스도 있음, 없으면 곧장 제안 모달로 판정) → 제안 모달 → **[채용포지션 등록]** → 등록 폼(인라인 모달).

## 필드

| 필드 | selector | 내용 |
|---|---|---|
| 포지션명* | `input[name="GI_PSTN"]` | `회사명(서비스) 직무 (약칭)` |
| 직무* | popup | 아래 절차, rect 단순 click 금지 |
| 고용형태* | dropdown(필수) | "선택하세요" click → 정규직/계약직/위촉직 |
| 입사후 업무*(EXEC_WORK) | `textarea[name="EXEC_WORK"]` | [회사소개](5필수요소) + [이 포지션] + [주요업무] + [자격요건] — 사람인 offerComment와 회사소개 동일 |
| 우대사항(ST) | `textarea[name="ST"]` | [우대사항] |
| 근무지/연봉 | 선택 | |
| 등록 | `button` textContent==='포지션 등록' — **정밀 타게팅 필수**(아래 함정 4) | |

**글자수(R5)**: EXEC_WORK/ST도 저장 전 `maxlength` 실측, 없으면 2,100자 이상 하한.
**가독성(R7)**: 저장 전 회사소개/업무/자격/우대가 `[헤더]`와 짧은 줄로 나뉘는지 확인한다. raw JD 덩어리, `**About`, `•`, 한 줄 180자 초과는 등록 금지다.

## 직무선택 popup
1. [직무선택] click → popup
2. `[data-part-ctgr-code="<코드>"]` 카테고리 click → 1.5s wait
3. 하위 `[data-part-code="<코드>"]`는 rect click 아님 — inner checkbox + 이벤트 시퀀스:
```js
const el=document.querySelector('[data-part-code="1000188"]'); const inp=el.querySelector('input');
['pointerover','pointerdown','mousedown','pointerup','mouseup','click'].forEach(t=>(inp||el).dispatchEvent(new MouseEvent(t,{bubbles:true,cancelable:true,view:window})));
if(inp){inp.checked=true; inp.dispatchEvent(new Event('change',{bubbles:true}));}
```
4. [확인] → 직무* 필드 칩 표시 확인.

**직무 카테고리 코드**: 기획전략 10026(PL·PM·PO 1000188) / AI·개발·데이터 10031(백엔드 1000229/프론트 1000230/데이터엔지니어 1000236) / 인사·HR 10028(인사담당자 1000201) / 마케팅광고MD 10030 / 디자인 10032 / 영업 10035 / 회계세무 10029. **가장 가까운 것으로 충분 — 직무 선택에 시간 쓰지 말 것.**

## 함정 (반드시 이 순서로 방어)
1. **connectOverCDP 전체 attach hang** — 탭 30개면 timeout. → raw CDP로 등록폼 탭 1개만 직접 연결(`/json/list` 찾기 → WebSocket 직결).
2. **고용형태 dropdown은 evaluate().click() 무시** — 옵션이 `.devemplybox` 밖 전역에 렌더. 실제 마우스 좌표 클릭(`Input.dispatchMouseEvent`)만 통함.
3. **고용형태 미선택 시 등록 버튼 눌러도 폼 안 닫힘** — `.selectBox-button-text`가 '정규직'으로 바뀐 것 확인 후에만 등록.
4. **`[포지션 등록]`은 `button` 태그만 정밀 타게팅** — 다른 태그의 동일 텍스트로 좌표가 빗나감.
5. **텍스트 중복 오탐** — "고용형태"/"면접 후 결정" 같은 텍스트가 화면 밖(y>1200)에도 존재. 가시영역(`y>0 && y<1200 && width>0`) 필터 필수.
6. **인재 열람 세션 ≠ 제안/등록 세션** — [포지션 제안] 누르면 iframe 안에 로그인 모달이 뜰 수 있음(메인 document에서 안 잡힘). iframe 존재 여부(`querySelectorAll('iframe')`에서 `/login/i.test(src)`)로 판정.
7. **자동 로그인**: 로그인 필요 시 새 탭(`/json/new` PUT) → 메인 document 폼에 value setter 주입(`input[name="id"|"userId"|"M_ID"]`, `input[type="password"]`) → 캡차/2FA 감지 시 즉시 사람 게이트로 STOP. 셀렉터 원본 = `tools/jobkorea-bulk-register/auto-login.mjs`(단, connectOverCDP 전체attach+구포털 URL이라 셀렉터만 차용).
8. **성공 판정은 innerText 아니라 input value** — 폼 닫힘(GI_PSTN 부재) + 제안 모달 "포지션 정보" 자동선택으로 판정.
9. ⛔ [제안보내기]는 누르지 않는다 — 발송=차감(R6).

## 죽은 참조(쓰지 말 것)
`docs/sot/26-portal-login-spec.json`, `tools/multi_position_sourcing/portal_autologin.py` — 둘 다 부재 확인됨.

## 자격증명
`.env.local`: `JOBKOREA_USERNAME`/`JOBKOREA_PASSWORD`
