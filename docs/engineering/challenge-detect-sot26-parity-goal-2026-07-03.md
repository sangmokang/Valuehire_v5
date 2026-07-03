# Goal — PC-F3 보안챌린지 감지를 SOT26 unified_regex 전체 토큰으로 통일 · 2026-07-03

> 모드: code-change · 위험등급 L3 (프로덕션 로그인 안전 게이트 — 봇 차단·계정 보호, SOT2). 근거: addendum-2026-07-02 PC-F3 + SOT26.

## 현재 상태 (직접 연 file:line)
- `tools/multi_position_sourcing/portal_login.py:81-84` — `_has_security_challenge(text, url)`가 **7개 토큰만** 검사: `("보안문자","CAPTCHA","2단계","인증번호","이상 접근","checkpoint","challenge")`.
- SOT(단일 진실) `docs/sot/26-portal-login-spec.json:65` `block_detection.unified_regex` = **18개 토큰**: captcha·recaptcha·보안문자·자동입력 방지·checkpoint·/uas/login·login-cap·unusual activity·verify you·multiple sign-ins·Only one session·enterprise-authentication·이상 접근·2단계·authwall·challenge·인증번호·protechts.
- **누락 11개** — 특히 `multiple sign-ins`·`Only one session`·`enterprise-authentication`(LinkedIn RPS 멀티세션 락)·`authwall`·`/uas/login`·`recaptcha`·`unusual activity`. SOT26:163이 명시적으로 "추가하라"고 지시.
- 배선(고아 아님): `_has_security_challenge` 프로덕션 호출 7곳 — portal_login.py:252·268·282·373·428·481, portal_autologin.py:159 (로그인/준비체크가 챌린지 감지 시 STOP=사람 게이트).

## 근본 원인
감지 토큰이 SOT26 단일 진실과 어긋나(부분집합) RPS 멀티세션 락·authwall·recaptcha 등을 못 잡음 → 봇이 STOP 못 하고 계속 두드림(SOT2 봇 금지 위반, 계정 차단 위험).

## 계약 (SDD)
- `_CHALLENGE_TOKENS: tuple[str,...]` = SOT26 unified_regex 토큰 집합과 **동일**(소문자 비교). 파리티 테스트가 단일 진실을 강제.
- `_has_security_challenge(text, url="") -> bool`: `text+url` 소문자에 `_CHALLENGE_TOKENS` 중 하나라도 부분일치하면 True.

## 인수기준 (기계검증 1)
`tests/test_challenge_detect_parity.py` GREEN: (a) SOT26 누락 11토큰 각각을 담은 텍스트에서 `_has_security_challenge`가 True, (b) 기존 7토큰 회귀 유지, (c) 무해 텍스트 False, (d) 파리티: `{t.lower() for t in _CHALLENGE_TOKENS} == {SOT26 unified_regex split('|') lower}`. + `./verify.sh` exit 0.

## 적용 게이트
harness 0→1→2(RED)→3(GREEN)→4(verify)→4b(자기적대+Codex V1+Claude V2)→5(ship PR).

## 적대검증 정조준
- 파리티 테스트가 SOT26 파일을 실제로 읽어 드리프트를 잡는가(경로 견고성).
- 과잉 매칭(무해 텍스트에 'challenge'/'verify you' 오탐? 'verify you' 흔한 문구?).
- URL vs body 텍스트 양쪽 커버.
- 대소문자·한글·하이픈·슬래시 토큰(/uas/login).

## 비범위
멀티세션 락 후속 처리 규정(linkedin_multi_session 핸들링), portal_autologin 부재 참조(별도), 러너면.

## 적대 검증 로그
(비움 — 게이트4b에서 채움)
