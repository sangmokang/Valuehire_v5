# Discord direct search aliases — goal (2026-07-21)

## 사용자 요청

Discord에서 프롬프트를 넣을 때 `/url`, `/aisearch`, `/humansearch`를 직접 실행할 수 있게 한다.
기존 `/fleet-run`은 유지한다.

## 수용 기준

1. `/url <position URL>`은 기존 `fleet-run` 안전 경로에서 `skill=url`로 큐 등록한다.
2. `/aisearch <position URL>`은 같은 경로에서 `skill=aisearch`로 큐 등록한다.
3. `/humansearch <position URL>`은 같은 경로에서 `skill=humansearch`로 큐 등록한다.
4. 현재 운영 경로인 Hermes 플러그인과 향후 직결 Discord 게이트웨이 양쪽에 같은 계약을 배선한다.
5. 사용자는 직접 명령의 `skill` 또는 Discord 이벤트 기반 중복 방지 키를 덮어쓸 수 없다.
6. 사용자·채널·역할·DM 여부를 기존 Discord 권한 검사까지 보존한다.
7. 같은 Discord 이벤트는 같은 중복 방지 키를 사용한다. 이벤트 ID가 없으면 직접 명령은 거부한다.
8. URL 없음, 자유문, 닫히지 않은 따옴표, 공백·제어문자 포함 URL은 큐에 들어가지 않는다.
9. 허용 스킬은 `url`, `aisearch`, `humansearch`뿐이며 발송·아웃리치 경로는 추가하지 않는다.
10. 기존 `/fleet-run`, `/fleet-status`, `/fleet-resume`, `/fleet-cancel` 동작을 유지한다.

## 범위 밖

- 후보자 연락·메일·메시지 발송
- Discord 직결 게이트웨이의 라이브 전환 및 단일 임대 구현
- 검색 워커 자체 알고리즘 변경

## 검증 기준

- 실패 검사를 먼저 기록한 뒤 구현한다.
- 관련 검사와 전체 `./verify.sh`를 통과한다.
- 권한 우회, 중복 이벤트, 스킬/중복키 덮어쓰기, 제어문자 URL을 독립 적대 검토한다.
- 운영 반영 전 Hermes 플러그인 심링크·게이트웨이 상태를 확인하고, 재시작 후 새 명령 등록을 확인한다.

GitHub issue: #154
