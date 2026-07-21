# 사람인 등록 — candidate-manage 포지션 추가

(구 `position-register` §2·§4·§5·§7 흡수, 검증된 selector 2026-06-15~2026-07-02 실측)

## 진입
GNB "인재풀 ▾" > "포지션 관리" = `https://www.saramin.co.kr/zf_user/memcom/talent-pool/main/candidate-manage`.
- ⚠️ **tutorial 리다이렉트 함정**: 로딩 미완 순간 URL이 `.../main/tutorial`로 보여도 일시적 상태. `waitUntil:'networkidle'` + 2~3초 대기 후 정상 화면 확인. URL만 보고 미로그인 단정 금지.
- 우상단 **[+ 포지션 추가]**(`button.btn_add_position`) → 슬라이드 패널.

## 필드

| 필드 | selector | 내용 |
|---|---|---|
| 포지션명* | `input[name="hiringTitle"]` | `회사명(서비스), 직무 (약칭)` |
| 제안 내용(offerComment) | `textarea[name="offerComment"]` | ①개인화 인사 + valuehire 도입부 + ②[회사소개](5필수요소 — company-research.md) + ③포지션 셀링 + ④CTA(SOT-10 §1④) + 서명 |
| 업무 내용(chargeWork) | `textarea[name="chargeWork"]` | [주요업무]+[자격요건]+[우대사항]+[근무조건] — JD 원문 1:1, 창작 금지 |
| 저장 | `button` textContent==='저장' | |

- **글자수(R5 — 2026-07-09)**: 저장 전 두 textarea의 `maxlength` 속성을 DOM에서 읽어 실측. 있으면 그 값의 95%+ 채움 목표. 없으면 2,000자 이상(SOT-10 상단값)을 하한으로 JD 원문 전체 포함.
- **valuehire 도입부(고정 문구)**: "밸류커넥트의 커리어 구독 서비스 valuehire를 통해 본 제안을 수락해 주시면, 보다 정교하게 다듬은 이력서 피드백을 회신드리고, 앞으로 커리어 방향과 맞닿은 포지션이 생길 때마다 가장 먼저 안내드리고자 합니다. (제안 수락 시 개인정보 수집·이용에 동의하신 것으로 간주됩니다.)"
- 입력: raw CDP value setter(`Object.getOwnPropertyDescriptor(proto,'value').set` + input/change dispatch). Playwright `fill()` 비사용(SOT-26 raw CDP 단일탭).
- 검증: `offer-readability-gate.mjs` 통과 + offer/charge 모두 헤더/불릿/줄길이 정상 + 한글 깨짐 없음 → 저장. 패널 클릭 후 3.5초 대기 후 필드 탐지.
- 금지: `.slice(0,N)`로 조용히 절단한 본문 저장. 저장 후 `textarea[name="offerComment"]`, `textarea[name="chargeWork"]` 실제 value 길이와 끝 문장을 읽어 잘림이 없음을 확인한다.
- 성공 판정 = 패널 닫힘 + 목록 맨 앞 카드 생성 + 진행중 카운트 +1.

## 함정 (2026-06-22 방어 원칙)
- 페이지 로드/상호작용 전 URL·DOM 3단계 교차검증: `candidate-manage` 요청인데 URL에 `tutorial`/`auth` 포함 → 세션 만료로 즉시 로그인 플로우 분기.
- `[role="dialog"]` 존재 ≠ 원하는 모달. 내부에 최종 타깃 필드가 `offsetWidth>0`인지 확인 후에만 "OPEN" 판정.
- 텍스트 매칭은 완전일치 대신 정규식(`/이직|제안/`)으로 UI 문구 변경에 대비.
- native alert/confirm은 `window.alert=()=>true` 등으로 freeze 방지(R40).

## 자격증명/캐시
- `.env.local`: `SARAMIN_USERNAME`/`SARAMIN_PASSWORD`
- 회사 조사 캐시: `~/.cache/saramin-company-research/<slug>.json`
- 포지션 본문 캐시: `~/.cache/saramin-positions/<slug>-<pos>.json`
