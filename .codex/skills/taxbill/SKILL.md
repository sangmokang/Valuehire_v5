---
name: taxbill
description: 홈택스 계산서 스크린샷 1장으로 등록→정산배분→증빙문서→이메일 자동 발송까지 한 번에 처리. 트리거 — "계산서 발행", "taxbill", "증빙 문서 보내", "계산서 스샷", "정산 배분", "계산서 등록".
---

# /taxbill — 계산서 발행→정산배분→증빙문서→이메일 자동화

사장님이 홈택스 전자계산서 스크린샷 1장만 주면, 등록부터 이메일 발송까지 한 번에 끝낸다.

## 절차

### 1단계: 스크린샷 Vision 추출
- 스크린샷에서 자동 추출: 상호(공급받는자), 사업자등록번호, 대표자명, 작성일자, 승인번호, 공급가액
- Vision API(Claude)로 OCR 추출 후 JSON 구조화

### 2단계: 부족 필드 질의 (한 메시지로 모아서, 알람 폭탄 금지)
스크린샷만으로 알 수 없는 필드를 사장님에게 되묻는다:
- 입사자명(후보자)
- 기준 연봉, 수수료율(%) — 공급가액과 대조해 자동 검산(연봉 x 수수료% ≈ 공급가액, 어긋나면 경고)
- 담당 컨설턴트(오너): tim/kcs/julian/rogan 중 택1 + 보상율(%)
- 코워커: tim/kcs/julian/rogan 중 택1(컨설턴트와 다른 사람) + 배분율(%), 없으면 생략
- 사장님이 이미 한 문장에 연봉/수수료율을 같이 줬으면 되묻지 않고 바로 사용

### 3단계: 검산
- 연봉 x 수수료율 ≈ 공급가액 확인 (10% 이상 차이나면 경고)
- 컨설턴트 보상율 + 코워커 배분율 ≤ 100% 확인 (초과 시 에러)
- 컨설턴트 ≠ 코워커 확인 (같은 사람이면 경고)

### 4단계: 등록
`POST /api/admin/owner/invoices` 호출:
```json
{
  "write_date": "2026-07-09",
  "issue_date": "2026-07-09",
  "client_name": "덕화푸드",
  "client_biz_no": "000-00-00000",
  "supply_amount": 12750000,
  "candidate_name": "홍길동",
  "consultant": { "key": "tim", "rate": 0.35 },
  "coworker": { "key": "kcs", "rate": 0.40 }
}
```
- 성공 시 revenue_invoices 1행 + commission_payouts 3행 자동 생성
- payee_name/payee_email이 ASSIGNEE_EMAILS 기준으로 자동 채워짐

### 5단계: 증빙 문서 생성 + 이메일 발송
- API 등록 성공 시 자동으로 컨설턴트/코워커에게 증빙 문서 이메일 발송
- 증빙 문서 = 인라인 HTML (고객사/입사자/발행일/공급가액/배분표/세후입금액)
- 발송 실패해도 등록은 롤백하지 않음 (에러 메시지로 보고)

### 6단계: 라이브 화면 재확인
- `admin.valuehire.cc/admin/owner` 매출/계산서 탭에서 신규 행 확인
- 스크린샷 증거 필수 (코드 테스트 통과만으로 완료 주장 금지)

## 담당자 SOT (절대 새 명단 파일 만들지 않음)

`app/kanban/_lib/assigneeMap.ts` ASSIGNEE_EMAILS 그대로 재사용:
- tim → sangmokang@valueconnect.kr (Tim강상모)
- kcs → kcs@valueconnect.kr (Dragon김충수)
- julian → julian@valueconnect.kr (Julian)
- rogan → rogan@valueconnect.kr (Rogan이상혁)

## 배분 계산 SOT

- 기본값: 코워커 40% / 컨설턴트(오너) 35% / 회사 25% — 딜마다 변경 가능
- 원천징수 3.3%: 코워커·컨설턴트에게만 적용, 회사는 0% (고정)
- 반올림 오차는 회사 행이 흡수 (Σgross === supplyAmount 항상 보장)
- 계산 함수: `src/lib/owner/settlement.ts` computePayouts(supplyAmount, cfg)

## STOP 조건

- 배분율 합 > 100%
- 유효하지 않은 담당자 key
- 스크린샷 OCR 실패 (재촬영 요청)
- Gmail 자격증명 없음 (등록은 진행, 이메일만 SKIP 보고)

## 관련 파일

- `src/lib/owner/settlement.ts` — 배분 계산 순수함수 + validateSplitRates + buildPayoutRows
- `src/lib/owner/financeConfig.ts` — 기본 배분율 SOT
- `src/lib/owner/taxbillDocument.ts` — 증빙 문서 HTML 렌더러 + 이메일 빌더
- `app/api/admin/owner/invoices/route.ts` — 계산서 등록 API (커스텀 배분율 지원)
- `app/(admin)/admin/owner/_components/tabs/RevenueTab.tsx` — 신규 등록 폼 (컨설턴트/코워커 필드)
- `app/pipeline/_lib/messageProviders.ts` — Gmail 발송 인프라
- `tests/ownerInvoicesSplitOverride.test.ts` — AC-1~AC-6 테스트
