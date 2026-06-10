# Goal Prompt: Search 연속 입력 순차 처리 적용

```text
Goal:
Valuehire Hermes/Discord AI Search에서 같은 Discord 세션에 Search 또는 Multisearch 요청이 연속 입력될 때, 기존 작업을 끊지 않고 FIFO(먼저 들어온 순서)로 순차 처리되도록 설정하고 검증한다.

Context:
현재 운영 기준은 “같은 Discord DM/채널/스레드에서 Search 또는 Multisearch 요청이 연속으로 들어오면 새 병렬 실행이나 interrupt가 아니라 queue로 처리한다”이다.
이 정책은 다음 문서에 정리되어 있다:
- /Users/kangsangmo/Desktop/Valuehire_v5/docs/ai-search/search-skill-concurrency.md
- /Users/kangsangmo/Desktop/Valuehire_v5/docs/ai-search/search-skill-concurrency.html

현재 확인된 설정은:
- /Users/kangsangmo/.hermes/config.yaml
- display.busy_input_mode: interrupt

해야 할 일:
1. /Users/kangsangmo/.hermes/config.yaml을 백업한다.
2. display.busy_input_mode 값을 interrupt에서 queue로 변경한다.
3. 변경 전후 diff를 확인한다.
4. Hermes Gateway 또는 Discord 봇이 설정을 다시 읽도록 안전하게 재시작/리로드하는 방법을 확인한다.
5. 운영 중인 봇을 재시작해야 한다면, 재시작 전 영향 범위를 짧게 보고하고 승인 게이트를 둔다.
6. 재시작/리로드 후 실제 설정이 queue로 반영됐는지 확인한다.
7. 가능하면 Discord 같은 DM/채널/스레드에 짧은 테스트 메시지를 연속으로 보내, 두 번째 요청이 첫 번째 요청을 끊지 않고 대기열로 들어가는지 확인한다.
8. 검증 결과에는 다음을 포함한다:
   - 수정한 파일 경로
   - 백업 파일 경로
   - 변경 diff 요약
   - 적용된 최종 값
   - Gateway 재시작/리로드 여부
   - Discord 실테스트 여부
   - 실테스트를 했다면 메시지 ID 또는 확인 가능한 로그 근거

안전 규칙:
- 토큰, API 키, 비밀번호, 쿠키 값은 절대 출력하지 말고 [REDACTED]로 가린다.
- 운영 Discord 봇 재시작처럼 서비스에 영향을 줄 수 있는 작업은 실행 전 반드시 사용자 승인을 받는다.
- 설정 파일을 수정하기 전 반드시 백업한다.
- 단순히 문서만 수정하고 끝내지 말고, 실제 설정값과 런타임 반영 여부를 확인한다.
- Discord 실테스트가 불가능하면 불가능한 이유를 명확히 보고하고, 대신 로그나 설정 로딩 경로로 확인한다.

Expected final answer:
한국어로 짧고 명확하게 보고한다.
“설정 변경 완료/미완료”, “검증 완료/미완료”, “남은 조치”를 구분해서 말한다.
```

## 짧은 버전

```text
Goal:
Valuehire Hermes/Discord에서 같은 세션의 연속 Search 입력이 interrupt가 아니라 queue로 순차 처리되도록 실제 설정을 바꾸고 검증한다.

Context:
현재 /Users/kangsangmo/.hermes/config.yaml의 display.busy_input_mode가 interrupt로 되어 있다. 이를 queue로 바꾸는 것이 목표다. 관련 SOT 문서는 /Users/kangsangmo/Desktop/Valuehire_v5/docs/ai-search/search-skill-concurrency.md 이다.

Tasks:
1. config.yaml 백업
2. busy_input_mode: interrupt → busy_input_mode: queue 변경
3. diff 확인
4. Gateway/Discord 봇 설정 반영 방법 확인
5. 재시작이 필요하면 승인 받고 재시작
6. 반영 확인
7. 가능하면 Discord 연속 입력 테스트로 첫 작업을 끊지 않고 큐잉되는지 확인
8. 결과를 한국어로 보고

Safety:
운영 봇 재시작 전에는 반드시 승인받는다. 비밀값은 출력하지 않는다.
```
