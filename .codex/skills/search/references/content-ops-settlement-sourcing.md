# Content Operations / Settlement Sourcing Notes

Use for non-engineering recruiting searches where the role is content operations, content billing/settlement, partner operations, licensing, or rights/admin work rather than growth/AI/engineering.

## Intake signals

Public career-page JDs may be the source of truth instead of ClickUp. Extract the structured JD from page HTML/Next.js data when available, then normalize into:
- service/team and content format (OTT, short-form drama, webtoon/webnovel, creator/video platform)
- contract type and seniority fit (e.g. 1-year contract, junior/mid hands-on)
- core ops duties: contract data registration, settlement/billing review, closing deadlines, partner/vendor communication
- adjacent ops duties: content ingest/outbound, QA, rights protection, unauthorized-upload monitoring/reporting
- tool/process needs: Google Workspace/Sheets, data hygiene, deadline tracking
- language/global needs: English/Japanese or localization/partner communication

## Target pools

Primary:
- OTT/streaming platform content operations: Watcha, Wavve, TVING, Coupang Play, Netflix Korea, Disney+ Korea, KOCOWA, Rakuten Viki
- Webtoon/webnovel/IP platform operations: Kakao Entertainment, Naver Webtoon, RIDI, Lezhin, Laftel, Storywiz
- Content production/distribution/MCN/short-form operations: CJ ENM, Studio Dragon, SLL, Playlist, Dingo, Sandbox Network, Collab Asia

Adjacent:
- music/creator/digital-content platform partner settlement or content admin
- global content localization/delivery/asset-management coordinator
- anti-piracy/takedown monitoring operations

Lower priority:
- pure content planning/production without settlement, contract, data ops, or partner communication evidence
- overly senior content business-development executives for hands-on contract roles
- freelance/consulting-centered candidates for contract internal operations roles

## Query matrix

Role titles:
- `Content Operations Manager`, `Content Operations Coordinator`, `Content Billing Manager`
- `Content Settlement`, `Royalty Operations`, `Payout Operations`, `Content Admin`
- `Partner Operations Manager`, `Content Partnership Operations`
- `Content Licensing Coordinator`, `Rights Management Coordinator`
- `Content Delivery`, `Content Ingest`, `Metadata Operations`
- Korean: `콘텐츠 운영 담당자`, `콘텐츠 정산 담당자`, `콘텐츠 계약 관리`, `콘텐츠 유통 운영`, `플랫폼 운영 담당자`, `IP 운영`, `권리 운영`

Core terms:
- `settlement`, `billing`, `royalty`, `payout`, `closing`, `invoice`
- `contract data`, `metadata`, `asset management`, `content ingest`, `content delivery`
- `partner communication`, `vendor communication`, `QA`, `quality control`, `rights protection`, `anti-piracy`, `takedown`
- Korean: `정산`, `마감`, `검토`, `계약 데이터`, `입출고`, `검수`, `품질 확인`, `파트너 운영`, `업체 커뮤니케이션`, `무단 업로드`, `신고 처리`

Representative queries:
```text
site:linkedin.com/in ("Content Operations" OR "Content Coordinator" OR "Content Admin") (OTT OR streaming OR "Coupang Play" OR TVING OR Wavve OR WATCHA) Korea
site:linkedin.com/in ("content billing" OR settlement OR royalty OR payout) (content OR OTT OR webtoon OR webnovel) Korea
site:linkedin.com/in ("content licensing" OR "rights management" OR "content delivery") (Korea OR Korean) (OTT OR streaming)
site:linkedin.com/in ("KOCOWA" OR "Rakuten Viki" OR "Coupang Play" OR "TVING") ("Content Operations" OR "Content Acquisition" OR "Partner Operations")
"콘텐츠 정산" "콘텐츠 운영" "LinkedIn"
"콘텐츠 입출고" "검수" "OTT"
"콘텐츠 계약" "정산" "파트너" "운영"
"무단 업로드" "모니터링" "콘텐츠" "운영"
"웹툰" "정산 담당자" "콘텐츠 운영"
```

## Scoring rubric (100)

1. Core operations fit — 30
- content contract/metadata/system registration: 8
- settlement/billing/closing/royalty/payout: 10
- content ingest/outbound/QA/admin operations: 7
- fast, accurate data handling: 5

2. Content platform domain fit — 20
- OTT/streaming/short-form/web-drama/content distribution: 10
- webtoon/webnovel/IP/licensing/rights ops: 5
- content-consumer/platform sense: 5

3. Partner communication fit — 15
- multiple external partners/vendors: 8
- settlement/contract/ops issue handling: 5
- internal cross-functional ops communication: 2

4. Tools & process fit — 15
- Google Workspace/Sheets/Excel operations: 6
- schedule/deadline management: 5
- process documentation/improvement: 4

5. Language/global fit — 10
- English communication: 4
- Japanese communication: 4
- global content/localization operations: 2

6. Evidence quality — 10
- role directly visible in public profile/article: 5
- recency/current role visible: 3
- low uncertainty: 2

## Search-channel pitfalls

- The word `content` causes heavy dictionary/SEO pollution in generic search. Prefer exact role phrases plus company names, or Korean operational terms (`정산`, `입출고`, `검수`, `파트너 운영`) rather than broad `content` alone.
- If Google/Bing/Brave/DuckDuckGo are captcha-limited or polluted, do not invent names. Report “candidate discovery limited by search channel quality” and provide the verified strategy/queries plus any partial candidate-pool directions.
- ChatGPT Search/CDP can remain in `Pro 생각 중` with only intermediate assistant messages. Set a bounded polling timeout, save the latest assistant text as a partial artifact, and do not block the whole workflow indefinitely waiting for a final JSON list.
