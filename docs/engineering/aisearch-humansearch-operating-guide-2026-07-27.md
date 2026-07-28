# AI Search / Humansearch 운영 및 점수 기준 통합 문서

> 상태: 작성중 메모입니다.
> 범위: `aisearch`, `humansearch`, 그리고 v4/v5 후보자 점수 기준을 한 문서에 묶습니다.

## 1. 목적

이 문서는 두 가지를 함께 정리합니다.

1. `aisearch` / `humansearch`를 실제로 돌릴 때 지켜야 할 운영 규칙입니다.
2. 최근에 정리된 후보자 점수 기준을 v4, v5 기준으로 함께 회수한 메모입니다.

핵심은 다음과 같습니다.

- `aisearch`는 JD부터 검색까지 처음부터 끝까지 만드는 흐름입니다.
- `humansearch`는 사람이 이미 걸어둔 검색결과를 순회해서 후보를 수확하는 흐름입니다.
- 최종 합격 점수는 v5의 버전된 계약으로 계산합니다.

## 2. 운영 원칙

### 2.1 Discord / 보고 채널

- 디스코드와의 소통 채널은 별도로 유지합니다.
- 메모상 DM 대상 ID는 `1512101118543397056`입니다.
- 중간 보고와 완료 보고는 분리해서 보냅니다.
- 알림을 여러 번 쪼개서 보내지 않고, 한 번에 묶어서 보냅니다.

### 2.2 브라우저 / 기기 운영

- Macmini, Macbook, Winpc 3대에서 브라우저 상태를 함께 봅니다.
- LinkedIn은 보안이 강하므로 한 번에 1대만 사용합니다.
- LinkedIn 세션이 한 번 연결되면 그 세션을 유지합니다.
- 브라우저를 계속 열고 닫지 않습니다.
- 로그인 정보는 브라우저 프로필에 남겨서 다음에도 이어서 씁니다.
- 사람이 로그인해 주는 동안에는 가만히 기다립니다.

### 2.3 점유 / 양보 규칙

- 사람이 마우스나 키보드로 해당 브라우저를 만지면 잠시 멈춥니다.
- 멈춤 기준은 약 30초입니다.
- 더 이상 사람이 건드리지 않으면 다시 서치를 이어갑니다.
- 사람이 크롬을 쓰는 동안에는 자동 작업이 잠깐 양보합니다.

### 2.4 검색 실행 순서

- 디스코드에서 필터가 걸린 LinkedIn URL을 주면 그 URL을 먼저 돌립니다.
- 그다음에 다른 키워드 조합으로 더 나은 후보를 찾습니다.
- LinkedIn 검색은 Boolean 조합을 씁니다.
- 한국어, 영어, 띄어쓰기 변형을 섞어서 검색식을 만듭니다.
- 서울권 대학 출신을 먼저 찾습니다.
- 서울권 대학 후보가 충분하지 않으면, 그다음은 유명 회사 출신 쪽으로 넓힙니다.
- 페이지네이션은 한 페이지씩 넘기며 봅니다.
- 최대 10페이지까지만 봅니다.
- 무한 스크롤처럼 길게 끌지 않습니다.

### 2.5 검색 안정성

- Cloudflare가 뜨지 않도록 조심합니다.
- 캡차가 뜨면 무리해서 밀어붙이지 않습니다.
- 세션이 끊기지 않도록 같은 세션을 계속 씁니다.
- AI search가 돌아가는 창에는 진행 중 표시가 보여서 사람이 건드리지 않게 합니다.
- LinkedIn은 너무 빠르게 넘기지 않고, 다른 포털도 사람 속도에 맞춰 천천히 봅니다.
- LinkedIn은 프로필과 키워드 사이를 약 20~60초 텀으로 보고, 사람인·잡코리아는 대략 3~8초 텀으로 봅니다.

### 2.6 서치 완료 뒤

- 이 메모에는 사용자가 적어 둔 `서치가 완료되면` 이후 문장이 아직 비어 있습니다.
- 실제 완료 후 흐름은 기존 `humansearch` / `aisearch`의 등록·보고 규칙을 따릅니다.
- 나중에 이 문서에서 완료 후 액션을 한 줄로 더 적으면 됩니다.

## 3. v5 후보자 점수 기준

v5의 현재 기준은 `candidate-match-v2-2026-07-24`입니다.

### 3.1 계약 구조

- Stage 1: JD 구조화
- Stage 2: 이력서 구조화
- Stage 3: gate와 D1~D8 소점수 산출
- Stage 4: 코드만 총점 계산

중요한 점은 다음과 같습니다.

- LLM은 총점과 등급을 직접 내지 않습니다.
- 총점 계산은 코드가 합니다.
- 근거가 없는 점수는 허용하지 않습니다.

### 3.2 D1~D8 가중치

| 항목 | 의미 | 가중치 |
|---|---|---:|
| D1 | 직무 핵심역량 | 27 |
| D2 | 도메인 / 산업 | 10 |
| D3 | 레벨 / 연차 | 14 |
| D4 | 성장궤적 / 재직안정 | 9 |
| D5 | 성과근거 | 7 |
| D6 | 티어 델타 | 10 |
| D7 | 성사 현실성 | 14 |
| D8 | 학벌 | 9 |

### 3.3 점수 보정 규칙

- D2가 `not_applicable`이면 그 가중치를 D1 쪽으로 옮깁니다.
- D6가 `not_applicable`이면 그 가중치를 D1과 D3으로 나눠 옮깁니다.
- 학교 민감 고객이면 D1 일부를 D8로 옮깁니다.
- 총 경력이 10년 이상이면 D8 일부를 D1으로 옮깁니다.
- 실패 gate가 있으면 총점 상한이 더 낮아집니다.
- 불확실 gate가 여러 개면 또 다른 상한이 적용됩니다.

### 3.4 점수 밴드

| 밴드 | 점수 |
|---|---:|
| strong | 85 이상 |
| candidate | 70 ~ 84 |
| conditional | 50 ~ 69 |
| reject | 49 이하 |

### 3.5 합격 기준

- 실사용 합격 기준은 70점 이상입니다.
- `humansearch`의 발송 관문도 70점 이상만 통과합니다.
- 프로필 URL이 무결해야만 다음 단계로 넘깁니다.

## 4. humansearch의 현재 점수 메모

`humansearch`에는 아직도 수집 순서용의 구형 점수 메모가 남아 있습니다.

### 4.1 구형 가중치

| 항목 | 가중치 |
|---|---:|
| education | 0.30 |
| role_fit | 0.50 |
| profile_logic | 0.10 |
| job_stability | 0.10 |

- 이 메모는 수집 순서용입니다.
- 최종 등록 가능 판단은 `candidate-match-v2-2026-07-24` 계약을 따릅니다.

### 4.2 하드 제외

채점 전에 먼저 거르는 조건은 다음과 같습니다.

- 프리랜서
- 잦은 단기 이직
- 하위 학교 신호

추가로 채널별 차이가 있습니다.

- 사람인과 잡코리아는 학교 컷을 적용합니다.
- LinkedIn은 학교 하드 컷을 적용하지 않습니다.
- 지방 국공립대와 단국대 이상은 허용 쪽으로 둡니다.

### 4.3 발송 관문

- 합격선은 70점 이상입니다.
- Discord로 보낼 때는 `profile_url`이 정상이어야 합니다.
- 빈값, 공백, 상대경로, `javascript:void`, 비HTTP URL은 거릅니다.

## 5. v4에서 회수한 비율형 점수 메모

v4 쪽에서는 각 축을 비율로 계산하는 구조가 보입니다.

### 5.1 축별 방식

- `education`
- `company_tier`
- `university_tier`

이 셋은 모두 `matched / total` 형태의 비율 계산을 씁니다.

### 5.2 최대 점수

| 항목 | 최대 점수 |
|---|---:|
| education | 10 |
| company_tier | 10 |
| university_tier | 8 |

### 5.3 v4에서 같이 남겨둘 메모

- 한글 학위 표기도 긍정 신호로 봅니다.
- `학사`, `석사`, `박사`, `대학교 졸업`, `대학 졸업`, `4년제 졸업`, `대졸`, `공학사`, `이학사`가 여기에 들어갑니다.
- `전문학사`는 만점 긍정 신호에서 빼 둡니다.
- 별칭 개수는 분모가 아닙니다.
- `total == 0 -> 1` 같은 v4 관행과 한글 제거 정규화는 이 문서의 현재 후보자 평가 기준으로 가져오지 않습니다.

### 5.4 해석

- v4 메모는 "근거가 있느냐"와 "긍정 신호가 잡히느냐"를 나눠 보는 방식입니다.
- v5는 그보다 더 구조화된 계약으로 바뀌었습니다.
- 따라서 v4는 참고용, v5는 현재 실행 기준으로 보면 됩니다.

## 6. 검색 우선순위 메모

### 6.1 학교 우선순위

1. 서울권 대학 출신을 먼저 봅니다.
2. 서울권 후보가 충분하지 않으면 비서울이더라도 유명 회사 출신으로 넓힙니다.
3. 학교가 약하면 직무 적합성과 회사 경력을 더 강하게 봅니다.

### 6.2 키워드 우선순위

- LinkedIn RPS에서는 Boolean 조합이 우선입니다.
- 한국어 / 영어 / 띄어쓰기 변형을 함께 넣습니다.
- 디스코드에서 받은 필터 URL이 있으면 그 URL을 먼저 씁니다.
- 그 뒤에 키워드를 늘려서 재탐색합니다.

### 6.3 세션 우선순위

- 한번 열린 세션은 끝까지 씁니다.
- 새로 로그인할 수 있으면 새로 만들기보다 기존 세션을 유지합니다.
- 브라우저를 자꾸 새로 열거나 닫는 방식은 피합니다.

## 7. 최종 정리

- 운영 쪽은 `humansearch`가 이미 걸린 검색을 안전하게 수확하는 흐름입니다.
- 생성 쪽은 `aisearch`가 JD부터 검색을 만드는 흐름입니다.
- 점수 쪽은 v5 계약이 현재 기준입니다.
- v4 비율형 점수는 참고용으로 남겨 두되, 현재 최종 판정은 v5 기준으로 봅니다.

## 8. 참고 원본

- [docs/sot/24-position-jd-sot.json](/Volumes/SSD/valuehire_v5/docs/sot/24-position-jd-sot.json)
- [tools/multi_position_sourcing/matching_score_contract.py](/Volumes/SSD/valuehire_v5/tools/multi_position_sourcing/matching_score_contract.py)
- [tools/multi_position_sourcing/humansearch.py](/Volumes/SSD/valuehire_v5/tools/multi_position_sourcing/humansearch.py)
- [skills/humansearch/humansearch.config.json](/Volumes/SSD/valuehire_v5/skills/humansearch/humansearch.config.json)
- [docs/engineering/scoring-ratio-signals-goal-2026-07-15.md](/Volumes/SSD/valuehire_v5/docs/engineering/scoring-ratio-signals-goal-2026-07-15.md)
- [docs/engineering/unified-matching-prompt-goal-2026-07-24.md](/Volumes/SSD/valuehire_v5/docs/engineering/unified-matching-prompt-goal-2026-07-24.md)
- [docs/engineering/skill-trio-url-aisearch-humansearch-guide-2026-07-05.md](/Volumes/SSD/valuehire_v5/docs/engineering/skill-trio-url-aisearch-humansearch-guide-2026-07-05.md)
- [docs/engineering/hermes-fleet-portal-search-humansearch-goal-2026-07-14.md](/Volumes/SSD/valuehire_v5/docs/engineering/hermes-fleet-portal-search-humansearch-goal-2026-07-14.md)

## 9. 메모

- 이 문서는 작성 중인 초안입니다.
- 나중에 실제 브라우저 체크리스트와 완료 후 후속 문장을 더 붙이면 됩니다.
