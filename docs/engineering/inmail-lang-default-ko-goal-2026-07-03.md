# InMail 언어 판정 — 한국어 기본·로마자 한국 이름 오판 제거 (goal, 2026-07-03, L2)

사장님 지시(2026-07-03): "로마자 이름을 외국인으로 이해한다니. 누가 들어도 한국 이름이고,
한국 대학 나왔으면 한국인. **외국인 채용 비율이 현저히 낮으니 한국어가 기본**."

## ① 현재 상태 (증거)
- `tools/multi_position_sourcing/inmail_precheck.py` `body_language_for_profile()` — 이름에 한글이
  없고 라틴 문자가 있으면 무조건 "en". 라이브 오판: 프로필 "HyunJun Jo"(고려대 박사, 한국인)에
  `language_mismatch: 영문 프로필… 본문을 영어로` 경고 발화(2026-07-03 토트 문구 검사 출력).
- Meseret Abayebas Tadese(외국인, 영어 본문이 정답 — 사장님이 "잘한 점"으로 명시)는 "en" 유지 필요.

## ② 근본 원인
"이름이 라틴 문자면 외국인"이라는 가정. 실제 RPS 프로필은 한국인도 로마자 표기가 다수.
판별 신호는 문자셋이 아니라 **한국 성씨(로마자) + 프로필 내 한글 신호**다. 기본값도 en이 아니라 ko여야 한다.

## ③ 인수 기준 (EARS)
- **AC1** Where 프로필 이름에 로마자 한국 성씨(Jo·Kim·Lee·Park 등)가 있으면, `body_language_for_profile`
  은 "ko"를 반환해야 한다. 검증: `pytest tests/test_inmail_precheck.py -k lang_ko -q`.
  counter-AC: "HyunJun Jo"가 en이면 가짜(현행 재현).
- **AC2** Where 이름이 라틴이고 한국 성씨가 아니며 한글 신호가 없으면(예: Meseret Abayebas Tadese,
  John Smith) "en" 유지. counter-AC: 전부 ko로 밀어 외국인 영어 본문 규칙(사장님 명시 잘한 점)이 죽으면 가짜.
- **AC3** Where 이름이 라틴이어도 visible_text 에 한글(예: 고려대학교)이 있으면 "ko".
- **AC4** precheck 통합: 프로필 "HyunJun Jo" + 한국어 본문 → language_mismatch 경고 0 (사장님 불만 재발 봉인).
- **AC5** 기존 테스트 약화 0 (Meseret en·조현용 ko·빈이름 폴백 유지).

## ④ 게이트 계획
워크트리 ../Valuehire_v5-inmail-lang-default-ko → RED 커밋 → 최소 구현(성씨 로마자 목록 + 판정 순서)
→ verify → codex V1 → Claude V2 → ship. 문서(골든샘플·SKILL) 동시 개정 = 드리프트 차단.

## ⑤ 적대검증 정조준
성씨 목록 누락(흔한 로마자 변형 rhee/pak/choe/gwon), 외국 이름 오탐(성씨 목록과 우연 일치 → 기본 ko 편향은
사장님 정책상 허용), 기존 Meseret en 회귀, precheck 경고 재발.

## ⑥ 비범위
범용 국적 판별기, 사람인·잡코리아 프로필 언어(한글 고정), 발송 자동화(영원히 비범위).

## ⑦ 롤백
squash 커밋 revert 1회.

## 적대 검증 로그
(append)
