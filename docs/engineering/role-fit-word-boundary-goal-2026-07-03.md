# Goal — PC-I3 직무 키워드 매칭 정밀도 (substring → 단어경계) · 2026-07-03

> 모드: code-change · 위험등급 L3 (라이브 채점 배선 함수 변경). 근거 스펙: `valuehire-pipeline-consolidation-spec-addendum-2026-07-02.md` R11/PC-I3.

## 현재 상태 (직접 연 file:line)
- `tools/multi_position_sourcing/humansearch.py:203-205` — `_role_fit_subscore`: `kw.lower() in text` 부분문자열 매칭.
- `tools/multi_position_sourcing/scoring.py:140` — `_role_direct_score`: `kw.lower() in skills` 부분문자열 매칭.
- 배선(고아 아님): `humansearch.py:242` `score_humansearch` → `_role_fit_subscore`. `score_humansearch`는 라이브 러너 `humansearch_cdp_run.py:162`가 호출(프로덕션 경로). `role_fit` 가중 0.50(최대축, humansearch.py:33).

## 근본 원인
부분문자열 매칭이 단어경계를 무시 → 'java'가 'javascript'에, 'account'가 'accounting'에, 'ai'가 'email'에 오탐. 지배 가중축(role_fit 0.50)이 부풀려져 부적격 후보가 70점 합격선을 넘음.

## 계약 (SDD — 입출력)
신규 순수함수 `scoring.keyword_in_text(keyword: str, text: str) -> bool`:
- `keyword`가 빈 문자열/공백 → `False`.
- `keyword`가 ASCII 단일 토큰(`[a-z0-9+#.]+`, 대소문자 무시) → **단어경계 매칭**: 앞뒤가 영숫자면 미매칭. (java∉javascript, account∉accounting, ai∉email, react∉reactive; java∈"backend java", c++∈"c++ and rust")
- 그 외(한글 등 비ASCII, 다단어 구) → 부분일치(대소문자 무시). (자바∈자바개발자)
- `_role_fit_subscore`·`_role_direct_score`가 이 함수를 소비(배선).

## 인수기준 (기계검증 1)
`tests/test_role_fit_word_boundary.py` GREEN: (a) `keyword_in_text` 오탐0/정탐/한글/기호/빈값 계약, (b) `_role_fit_subscore(skills=('javascript',), must=('java',))`의 sub==0.0, (c) `_role_direct_score(skills=('accounting',), must=('account',))`의 score==0. + 기존 전체 테스트 회귀 없음(`./verify.sh` exit 0).

## 적용 게이트
harness 0→1→2(RED)→3(GREEN)→4(verify)→4b(자기적대+Codex V1)→5(ship PR).

## 적대검증 정조준
- 경계 정규식이 c++/.net/c# 기호 토큰을 깨지 않는가(re.escape).
- 한글-영문 혼합 토큰, 다단어 must_have("machine learning") 회귀.
- 기존 채점 테스트가 substring 우연매칭에 의존했는가(회귀 시 근거와 함께 수정).
- 대소문자·전각(NFKC 밖) 변형.

## 비범위
- education 'Berkeley College' 오탐(별도 후속). 별칭사전(synonym) 확장(별도). 임베딩(PC-I4).

## 적대 검증 로그
(비움 — 게이트4b에서 채움)
