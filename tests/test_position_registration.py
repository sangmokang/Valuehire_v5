from __future__ import annotations

import unittest

from tools.multi_position_sourcing.posting_models import (
    ExistingPositionTask,
    ExtractedPosting,
    FetchResult,
    VisionAnalysis,
)
from tools.multi_position_sourcing.request_parser import (
    parse_discord_position_registration_request,
)
from tools.multi_position_sourcing.position_registration import (
    FY26_CLIENTS_POSITION_LIST_ID,
    build_position_custom_fields,
    build_registration_body,
    build_task_title,
    run_position_registration,
)


# --- Fakes for injected callables (DI; never touch real network/ClickUp) ------


def make_http_fetch(html: str, *, ok: bool = True, status_code: int = 200, reason: str = ""):
    """Return a fake http_fetch returning a canned FetchResult; records calls."""

    calls: list[str] = []

    def http_fetch(url: str) -> FetchResult:
        calls.append(url)
        return FetchResult(
            url=url,
            ok=ok,
            status_code=status_code,
            html=html,
            fetch_method="httpx",
            reason=reason,
        )

    http_fetch.calls = calls  # type: ignore[attr-defined]
    return http_fetch


def make_render_fetch(html: str, *, ok: bool = True):
    calls: list[str] = []

    def render_fetch(url: str) -> FetchResult:
        calls.append(url)
        return FetchResult(
            url=url,
            ok=ok,
            status_code=200 if ok else 0,
            html=html,
            fetch_method="playwright",
            reason="" if ok else "render failed",
        )

    render_fetch.calls = calls  # type: ignore[attr-defined]
    return render_fetch


def make_image_downloader(paths: tuple[str, ...]):
    calls: list[tuple[tuple[str, ...], str]] = []

    def image_downloader(urls: tuple[str, ...], artifacts_dir: str) -> tuple[str, ...]:
        calls.append((tuple(urls), artifacts_dir))
        return paths

    image_downloader.calls = calls  # type: ignore[attr-defined]
    return image_downloader


def make_vision(analysis: VisionAnalysis):
    calls: list[tuple[str, ...]] = []

    def analyzer(image_paths: tuple[str, ...]) -> VisionAnalysis:
        calls.append(tuple(image_paths))
        return analysis

    analyzer.calls = calls  # type: ignore[attr-defined]
    return analyzer


def make_clickup_search(existing: list[ExistingPositionTask]):
    calls: list = []

    def clickup_search(recognition) -> list[ExistingPositionTask]:
        calls.append(recognition)
        return existing

    clickup_search.calls = calls  # type: ignore[attr-defined]
    return clickup_search


def make_clickup_create_task(task_id: str = "TASK123", task_url: str = "https://app.clickup.com/t/TASK123"):
    calls: list[tuple[str, str]] = []

    def clickup_create_task(title: str, body: str) -> tuple[str, str]:
        calls.append((title, body))
        return task_id, task_url

    clickup_create_task.calls = calls  # type: ignore[attr-defined]
    return clickup_create_task


def make_clickup_create_comment(comment_id: str = "CMT456"):
    calls: list[tuple[str, str]] = []

    def clickup_create_comment(task_id: str, body: str) -> str:
        calls.append((task_id, body))
        return comment_id

    clickup_create_comment.calls = calls  # type: ignore[attr-defined]
    return clickup_create_comment


# --- Rich Wanted HTML fixture (text path: company + role + JD signals) --------

RICH_WANTED_HTML = """
<html><head>
<meta property="og:site_name" content="Acme">
<meta property="og:title" content="Backend Engineer">
<title>Backend Engineer | Acme</title>
</head><body>
<h2>주요업무</h2><p>백엔드 API 설계 및 구현, 데이터 파이프라인 운영을 담당합니다.</p>
<h2>담당업무</h2><p>대규모 분산 시스템 운영 및 채용 포지션 관련 업무를 수행합니다.</p>
<h2>자격요건</h2><p>Python 3년 이상 경력, 분산 시스템 경험이 필요합니다.</p>
<h2>우대사항</h2><p>Kubernetes 경험 우대.</p>
<h2>회사소개</h2><p>Acme는 핀테크 스타트업입니다. responsibilities requirements qualifications.</p>
</body></html>
"""

# Image-heavy, thin-text HTML: not enough text signals so extractor falls to images.
IMAGE_HEAVY_HTML = """
<html><head>
<meta property="og:site_name" content="ImageCorp">
<meta property="og:title" content="Poster Role">
<meta property="og:image" content="https://cdn.example.com/jd-poster.png">
</head><body>
<img src="https://cdn.example.com/jd-1.png">
<img src="/assets/jd-2.png">
<p>채용</p>
</body></html>
"""


class BuildHelpersTests(unittest.TestCase):
    def test_build_task_title_company_role(self) -> None:
        from tools.multi_position_sourcing.posting_models import PostingRecognition

        rec = PostingRecognition(
            is_job_posting=True,
            source_url="https://www.wanted.co.kr/wd/363433",
            recognition_mode="text",
            company="Acme",
            role="Backend Engineer",
        )
        self.assertEqual(build_task_title(rec), "Acme - Backend Engineer")

    def test_build_body_has_url_and_evidence_no_secrets(self) -> None:
        from tools.multi_position_sourcing.posting_models import PostingRecognition

        rec = PostingRecognition(
            is_job_posting=True,
            source_url="https://www.wanted.co.kr/wd/363433",
            recognition_mode="vision",
            company="Acme",
            role="Backend Engineer",
            jd_text="백엔드 엔지니어 채용 요약",
            image_evidence_paths=("artifacts/position_registration/img_0.png",),
        )
        body = build_registration_body(rec)
        self.assertIn("https://www.wanted.co.kr/wd/363433", body)
        self.assertIn("Acme", body)
        self.assertIn("Backend Engineer", body)
        self.assertIn("artifacts/position_registration/img_0.png", body)
        # never any secret-looking tokens
        self.assertNotIn("token", body.lower())


class DoD1NewDryRunTests(unittest.TestCase):
    def test_new_position_dry_run_created_no_task_call(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        self.assertTrue(parsed.should_route_to_registration)

        http_fetch = make_http_fetch(RICH_WANTED_HTML)
        clickup_search = make_clickup_search([])
        clickup_create_task = make_clickup_create_task()

        outcome = run_position_registration(
            parsed,
            http_fetch=http_fetch,
            clickup_search=clickup_search,
            clickup_create_task=clickup_create_task,
            dry_run=True,
        )

        self.assertEqual(outcome.status, "created")
        self.assertTrue(outcome.is_new_task)
        self.assertTrue(outcome.dry_run)
        # planned only: create_task must NOT be called in dry-run
        self.assertEqual(clickup_create_task.calls, [])  # type: ignore[attr-defined]
        self.assertFalse(outcome.external_posting_sent)
        self.assertFalse(outcome.secret_emitted)


class DoD2ImageVisionTests(unittest.TestCase):
    def test_image_path_uses_vision_and_body_has_company_role(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        # thin-text but image-heavy for both fetchers
        http_fetch = make_http_fetch(IMAGE_HEAVY_HTML)
        render_fetch = make_render_fetch(IMAGE_HEAVY_HTML)
        image_downloader = make_image_downloader(
            ("artifacts/position_registration/img_0.png",)
        )
        vision = make_vision(
            VisionAnalysis(
                is_job_posting=True,
                company="VisionCo",
                role="Data Engineer",
                summary="데이터 엔지니어 채용 공고",
                key_requirements=("Python", "SQL"),
                confidence=0.92,
            )
        )
        clickup_search = make_clickup_search([])
        clickup_create_task = make_clickup_create_task()

        outcome = run_position_registration(
            parsed,
            http_fetch=http_fetch,
            render_fetch=render_fetch,
            image_downloader=image_downloader,
            vision_analyzer=vision,
            clickup_search=clickup_search,
            clickup_create_task=clickup_create_task,
            dry_run=True,
        )

        self.assertEqual(outcome.recognition_mode, "vision")
        self.assertIn(outcome.status, ("created", "linked"))
        # vision analyzer was invoked with the downloaded evidence
        self.assertEqual(len(vision.calls), 1)  # type: ignore[attr-defined]
        self.assertFalse(outcome.external_posting_sent)
        self.assertFalse(outcome.secret_emitted)

        # The body that would have been registered must carry vision company/role.
        from tools.multi_position_sourcing.posting_models import PostingRecognition

        # Build the recognition the same way to assert body content.
        # (handler carries recognition into outcome via mode/confidence; body
        # content is validated by re-running build with the recognition derived.)
        # Run again with dry_run False to capture the actual body sent.
        http_fetch2 = make_http_fetch(IMAGE_HEAVY_HTML)
        render_fetch2 = make_render_fetch(IMAGE_HEAVY_HTML)
        image_downloader2 = make_image_downloader(
            ("artifacts/position_registration/img_0.png",)
        )
        vision2 = make_vision(
            VisionAnalysis(
                is_job_posting=True,
                company="VisionCo",
                role="Data Engineer",
                summary="데이터 엔지니어 채용 공고",
                confidence=0.92,
            )
        )
        create_task2 = make_clickup_create_task()
        run_position_registration(
            parsed,
            http_fetch=http_fetch2,
            render_fetch=render_fetch2,
            image_downloader=image_downloader2,
            vision_analyzer=vision2,
            clickup_search=make_clickup_search([]),
            clickup_create_task=create_task2,
            dry_run=False,
        )
        self.assertEqual(len(create_task2.calls), 1)  # type: ignore[attr-defined]
        title, body = create_task2.calls[0]  # type: ignore[attr-defined]
        self.assertIn("VisionCo", title)
        self.assertIn("Data Engineer", title)
        self.assertIn("VisionCo", body)
        self.assertIn("Data Engineer", body)


class DoD3DuplicateTests(unittest.TestCase):
    def test_duplicate_dry_run_linked_no_calls(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        http_fetch = make_http_fetch(RICH_WANTED_HTML)
        existing = [
            ExistingPositionTask(
                task_id="EXIST1",
                task_url="https://app.clickup.com/t/EXIST1",
                company="Acme",
                role="Backend Engineer",
                source_url="https://www.wanted.co.kr/wd/363433",
            )
        ]
        clickup_search = make_clickup_search(existing)
        clickup_create_task = make_clickup_create_task()
        clickup_create_comment = make_clickup_create_comment()

        outcome = run_position_registration(
            parsed,
            http_fetch=http_fetch,
            clickup_search=clickup_search,
            clickup_create_task=clickup_create_task,
            clickup_create_comment=clickup_create_comment,
            dry_run=True,
        )

        self.assertEqual(outcome.status, "linked")
        self.assertFalse(outcome.is_new_task)
        self.assertEqual(outcome.task_id, "EXIST1")
        # planned only in dry-run: no comment created
        self.assertEqual(clickup_create_comment.calls, [])  # type: ignore[attr-defined]
        self.assertEqual(clickup_create_task.calls, [])  # type: ignore[attr-defined]

    def test_duplicate_live_creates_comment_not_task(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        http_fetch = make_http_fetch(RICH_WANTED_HTML)
        existing = [
            ExistingPositionTask(
                task_id="EXIST1",
                task_url="https://app.clickup.com/t/EXIST1",
                source_url="https://www.wanted.co.kr/wd/363433",
            )
        ]
        clickup_search = make_clickup_search(existing)
        clickup_create_task = make_clickup_create_task()
        clickup_create_comment = make_clickup_create_comment("CMT789")

        outcome = run_position_registration(
            parsed,
            http_fetch=http_fetch,
            clickup_search=clickup_search,
            clickup_create_task=clickup_create_task,
            clickup_create_comment=clickup_create_comment,
            dry_run=False,
        )

        self.assertEqual(outcome.status, "linked")
        self.assertFalse(outcome.is_new_task)
        self.assertEqual(outcome.comment_id, "CMT789")
        self.assertEqual(len(clickup_create_comment.calls), 1)  # type: ignore[attr-defined]
        self.assertEqual(clickup_create_task.calls, [])  # type: ignore[attr-defined]


class DoD4FailClosedTests(unittest.TestCase):
    def test_extractor_blocked_is_skipped_no_clickup_calls(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        http_fetch = make_http_fetch("", ok=False, status_code=403, reason="403 blocked")
        clickup_search = make_clickup_search([])
        clickup_create_task = make_clickup_create_task()
        clickup_create_comment = make_clickup_create_comment()

        outcome = run_position_registration(
            parsed,
            http_fetch=http_fetch,
            clickup_search=clickup_search,
            clickup_create_task=clickup_create_task,
            clickup_create_comment=clickup_create_comment,
            dry_run=False,
        )

        self.assertEqual(outcome.status, "skipped")
        self.assertNotEqual(outcome.reason, "")
        self.assertEqual(clickup_create_task.calls, [])  # type: ignore[attr-defined]
        self.assertEqual(clickup_create_comment.calls, [])  # type: ignore[attr-defined]
        self.assertEqual(clickup_search.calls, [])  # type: ignore[attr-defined]
        self.assertFalse(outcome.external_posting_sent)
        self.assertFalse(outcome.secret_emitted)

    def test_recognizer_low_confidence_is_skipped(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        # ok html but thin text, no images/vision -> recognizer returns none/low
        thin_html = (
            '<html><head><meta property="og:site_name" content="Acme">'
            "<title>hi</title></head><body><p>안녕하세요</p></body></html>"
        )
        http_fetch = make_http_fetch(thin_html)
        clickup_search = make_clickup_search([])
        clickup_create_task = make_clickup_create_task()

        outcome = run_position_registration(
            parsed,
            http_fetch=http_fetch,
            clickup_search=clickup_search,
            clickup_create_task=clickup_create_task,
            dry_run=True,
        )

        self.assertEqual(outcome.status, "skipped")
        self.assertNotEqual(outcome.reason, "")
        self.assertEqual(clickup_create_task.calls, [])  # type: ignore[attr-defined]

    def test_not_routed_request_is_skipped(self) -> None:
        # An AI Search request must not route to registration.
        parsed = parse_discord_position_registration_request("후보자 찾아줘")
        self.assertFalse(parsed.should_route_to_registration)

        http_fetch = make_http_fetch(RICH_WANTED_HTML)
        clickup_search = make_clickup_search([])

        outcome = run_position_registration(
            parsed,
            http_fetch=http_fetch,
            clickup_search=clickup_search,
            dry_run=True,
        )
        self.assertEqual(outcome.status, "skipped")
        self.assertEqual(http_fetch.calls, [])  # type: ignore[attr-defined]
        self.assertEqual(clickup_search.calls, [])  # type: ignore[attr-defined]


class WiringLiveCreateTests(unittest.TestCase):
    def test_live_new_creates_task_returns_id_url(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        http_fetch = make_http_fetch(RICH_WANTED_HTML)
        clickup_search = make_clickup_search([])
        clickup_create_task = make_clickup_create_task(
            "TASK123", "https://app.clickup.com/t/TASK123"
        )

        outcome = run_position_registration(
            parsed,
            http_fetch=http_fetch,
            clickup_search=clickup_search,
            clickup_create_task=clickup_create_task,
            dry_run=False,
        )

        self.assertEqual(outcome.status, "created")
        self.assertTrue(outcome.is_new_task)
        self.assertEqual(outcome.task_id, "TASK123")
        self.assertEqual(outcome.task_url, "https://app.clickup.com/t/TASK123")
        self.assertEqual(len(clickup_create_task.calls), 1)  # type: ignore[attr-defined]
        self.assertFalse(outcome.dry_run)


class PastedJdTests(unittest.TestCase):
    def test_pasted_jd_no_url_recognized_and_created(self) -> None:
        jd = (
            "포지션 등록\n"
            "회사소개\nAcme는 핀테크 스타트업입니다.\n"
            "주요업무\n- 백엔드 API 설계 및 구현\n- 데이터 파이프라인 운영\n"
            "담당업무\n- 대규모 분산 시스템 운영\n"
            "자격요건\n- Python 3년 이상\n- 분산 시스템 경험\n"
            "우대사항\n- Kubernetes 경험\n"
            "responsibilities requirements qualifications 채용 포지션"
        )
        parsed = parse_discord_position_registration_request(jd)
        self.assertEqual(parsed.input_kind, "pasted_jd")

        # No fetchers needed for pasted JD; pass a fetch that would fail if called.
        def exploding_fetch(url: str) -> FetchResult:  # pragma: no cover - must not run
            raise AssertionError("http_fetch must not be called for pasted JD")

        clickup_search = make_clickup_search([])
        clickup_create_task = make_clickup_create_task()

        outcome = run_position_registration(
            parsed,
            http_fetch=exploding_fetch,
            clickup_search=clickup_search,
            clickup_create_task=clickup_create_task,
            dry_run=True,
        )

        self.assertEqual(outcome.status, "created")
        self.assertTrue(outcome.is_new_task)
        self.assertFalse(outcome.external_posting_sent)


def make_clickup_create_task_capturing(
    task_id: str = "TASK123", task_url: str = "https://app.clickup.com/t/TASK123"
):
    """3-인자 계약(title, body, list_id)을 기록하는 페이크 — 목적지 전달 단언용."""
    calls: list[tuple[str, str, "str | None"]] = []

    def clickup_create_task(title: str, body: str, list_id: str | None = None) -> tuple[str, str]:
        calls.append((title, body, list_id))
        return task_id, task_url

    clickup_create_task.calls = calls  # type: ignore[attr-defined]
    return clickup_create_task


class DestinationListIdTests(unittest.TestCase):
    """PC-A0 — ClickUpCreateTask 계약에 목적지 list_id 추가(순수 확장·회귀 0)."""

    def test_list_id_forwarded_to_create_task(self) -> None:
        # 목적지 list_id 를 주면 create_task 어댑터까지 그대로 전달돼야 한다(PC-A1 단언의 선행 seam).
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        create_task = make_clickup_create_task_capturing()
        outcome = run_position_registration(
            parsed,
            http_fetch=make_http_fetch(RICH_WANTED_HTML),
            clickup_search=make_clickup_search([]),
            clickup_create_task=create_task,
            clickup_list_id="901814621569",
            dry_run=False,
        )
        self.assertEqual(outcome.status, "created")
        self.assertEqual(len(create_task.calls), 1)  # type: ignore[attr-defined]
        _title, _body, list_id = create_task.calls[0]  # type: ignore[attr-defined]
        self.assertEqual(list_id, "901814621569")

    def test_legacy_two_arg_fake_still_works_without_list_id(self) -> None:
        # list_id 미지정 시 기존 2-인자 페이크가 회귀 없이 그대로 호출돼야 한다(동작 불변).
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        legacy = make_clickup_create_task()  # def clickup_create_task(title, body)
        outcome = run_position_registration(
            parsed,
            http_fetch=make_http_fetch(RICH_WANTED_HTML),
            clickup_search=make_clickup_search([]),
            clickup_create_task=legacy,
            dry_run=False,
        )
        self.assertEqual(outcome.status, "created")
        self.assertEqual(len(legacy.calls), 1)  # type: ignore[attr-defined]
        # (title, body) 2-튜플 그대로 — list_id 미전달로 시그니처 불변 보장.
        self.assertEqual(len(legacy.calls[0]), 2)  # type: ignore[attr-defined]

    def test_empty_string_list_id_treated_as_absent(self) -> None:
        # codex V1 caveat: clickup_list_id="" 를 3번째 인자로 흘리면 기존 2-인자 어댑터가
        # 깨진다 → 빈 문자열은 '목적지 없음'으로 보고 2-인자 호출한다(footgun 차단).
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        legacy = make_clickup_create_task()  # 2-인자 전용 어댑터
        outcome = run_position_registration(
            parsed,
            http_fetch=make_http_fetch(RICH_WANTED_HTML),
            clickup_search=make_clickup_search([]),
            clickup_create_task=legacy,
            clickup_list_id="",
            dry_run=False,
        )
        self.assertEqual(outcome.status, "created")  # TypeError 없이 생성 성공
        self.assertEqual(len(legacy.calls), 1)  # type: ignore[attr-defined]
        self.assertEqual(len(legacy.calls[0]), 2)  # type: ignore[attr-defined]

    def test_list_id_none_calls_two_arg_form(self) -> None:
        # clickup_list_id=None(기본) 이면 3-인자 페이크에도 list_id 로 None 이 흘러야 한다(중립).
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        create_task = make_clickup_create_task_capturing()
        run_position_registration(
            parsed,
            http_fetch=make_http_fetch(RICH_WANTED_HTML),
            clickup_search=make_clickup_search([]),
            clickup_create_task=create_task,
            dry_run=False,
        )
        self.assertEqual(len(create_task.calls), 1)  # type: ignore[attr-defined]
        _title, _body, list_id = create_task.calls[0]  # type: ignore[attr-defined]
        self.assertIsNone(list_id)


class PcA1LiveWriteFy26DestinationTests(unittest.TestCase):
    """PC-A1 — 라이브 경로가 설정된 FY26ClientsPosition 목적지로 정확히 1회 create."""

    def test_live_create_routes_exactly_once_to_fy26_clients_position(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        create_task = make_clickup_create_task_capturing()
        outcome = run_position_registration(
            parsed,
            http_fetch=make_http_fetch(RICH_WANTED_HTML),
            clickup_search=make_clickup_search([]),  # 비중복
            clickup_create_task=create_task,
            clickup_list_id=FY26_CLIENTS_POSITION_LIST_ID,
            dry_run=False,
        )
        self.assertEqual(outcome.status, "created")
        self.assertTrue(outcome.is_new_task)
        # 정확히 1회 — dedup/dry_run 분기에서 2회/0회로 새지 않음.
        self.assertEqual(len(create_task.calls), 1)  # type: ignore[attr-defined]
        _title, _body, list_id = create_task.calls[0]  # type: ignore[attr-defined]
        # 상수→리터럴 SOT 고정(search-access.md:425 FY26ClientsPosition). 오타면 잘못된 리스트에 쓰기.
        self.assertEqual(list_id, "901814621569")
        # SOT3 불변식 — ClickUp 인입은 발송 아님.
        self.assertFalse(outcome.external_posting_sent)
        self.assertFalse(outcome.secret_emitted)

    def test_duplicate_does_not_write_to_fy26_destination(self) -> None:
        # 실패경로: 중복이면 create 0회(코멘트 경로) → 목적지에 잘못된 신규 쓰기 없음.
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        existing = [
            ExistingPositionTask(
                task_id="EXIST1",
                task_url="https://app.clickup.com/t/EXIST1",
                source_url="https://www.wanted.co.kr/wd/363433",
            )
        ]
        create_task = make_clickup_create_task_capturing()
        outcome = run_position_registration(
            parsed,
            http_fetch=make_http_fetch(RICH_WANTED_HTML),
            clickup_search=make_clickup_search(existing),
            clickup_create_task=create_task,
            clickup_create_comment=make_clickup_create_comment("CMT1"),
            clickup_list_id=FY26_CLIENTS_POSITION_LIST_ID,
            dry_run=False,
        )
        self.assertEqual(outcome.status, "linked")
        self.assertEqual(len(create_task.calls), 0)  # type: ignore[attr-defined]


class PositionCustomFieldsTests(unittest.TestCase):
    """PC-A2a — 등록 커스텀필드 매퍼(순수). 고용형태 정규직 기본 + 근무지 주입 리졸버."""

    def _rec(self, **kw):
        from tools.multi_position_sourcing.posting_models import PostingRecognition

        base = dict(
            is_job_posting=True,
            source_url="https://www.wanted.co.kr/wd/363433",
            recognition_mode="text",
            company="Acme",
            role="Backend Engineer",
            jd_text="",
        )
        base.update(kw)
        return PostingRecognition(**base)

    def test_basic_fields_mapped_from_recognition(self) -> None:
        fields = build_position_custom_fields(self._rec(jd_text="백엔드 채용"))
        self.assertEqual(fields["company"], "Acme")
        self.assertEqual(fields["role"], "Backend Engineer")
        self.assertEqual(fields["source_url"], "https://www.wanted.co.kr/wd/363433")

    def test_employment_type_defaults_to_regular_when_unmentioned(self) -> None:
        # 사장님 규칙: JD에 고용형태 언급이 없으면 무조건 정규직.
        fields = build_position_custom_fields(self._rec(jd_text="주요업무: 백엔드 API 설계·운영"))
        self.assertEqual(fields["employment_type"], "정규직")

    def test_employment_type_detects_explicit_markers(self) -> None:
        cases = {
            "계약직 6개월": "계약직",
            "인턴 채용": "인턴",
            "파견 근무": "파견",
            "프리랜서 협업": "프리랜서",
            "기간제 근로": "기간제",
        }
        for jd, expected in cases.items():
            with self.subTest(jd=jd):
                fields = build_position_custom_fields(self._rec(jd_text=jd))
                self.assertEqual(fields["employment_type"], expected)

    def test_employment_no_false_positive_on_compound_words(self) -> None:
        # codex V1 결함1: 부분문자열 오탐 — '기간제한'·'계약직무'는 고용형태 언급 아님 → 정규직.
        for jd in (
            "지원 기간제한 없음",
            "기간제도 운영 경험",
            "계약직무 경험 우대",
            "계약 직접 관리 업무",
        ):
            with self.subTest(jd=jd):
                self.assertEqual(
                    build_position_custom_fields(self._rec(jd_text=jd))["employment_type"],
                    "정규직",
                )

    def test_employment_zero_width_still_detected(self) -> None:
        # codex V1 결함2a: 제로폭 삽입 우회 — strip 후 계약직 정탐.
        self.assertEqual(
            build_position_custom_fields(self._rec(jd_text="고용형태: 계​약직"))[
                "employment_type"
            ],
            "계약직",
        )

    @unittest.expectedFailure
    def test_employment_whitespace_obfuscation_known_open(self) -> None:
        # codex V1 결함2b(알려진 미해결): '계 약 직' 공백 난독. 공백 collapse 로 풀면 '계약 직접'→
        # '계약직접' 오탐이 더 나빠지므로 이 조각에선 열어둔다(정규직 기본, 사람 검수 backstop·SOT3).
        self.assertEqual(
            build_position_custom_fields(self._rec(jd_text="고용형태: 계 약 직"))[
                "employment_type"
            ],
            "계약직",
        )

    def test_work_location_from_injected_resolver(self) -> None:
        # 근무지는 웹서치 리졸버(주입)로 유추 — 매퍼는 순수, 검색은 주입 어댑터.
        fields = build_position_custom_fields(
            self._rec(), location_resolver=lambda company, jd: "서울 강남"
        )
        self.assertEqual(fields["work_location"], "서울 강남")

    def test_work_location_fail_closed_to_unknown(self) -> None:
        # 리졸버 없음/공허/예외 → "미상"(임의값 지어내지 않음, fail-closed).
        self.assertEqual(build_position_custom_fields(self._rec())["work_location"], "미상")
        self.assertEqual(
            build_position_custom_fields(
                self._rec(), location_resolver=lambda company, jd: "  "
            )["work_location"],
            "미상",
        )

        def boom(company: str, jd: str) -> str:
            raise RuntimeError("web search down")

        self.assertEqual(
            build_position_custom_fields(self._rec(), location_resolver=boom)["work_location"],
            "미상",
        )

    def test_segment_optional_passthrough(self) -> None:
        # status(segment)는 이 조각에서 선택 주입(빈 기본). 13 status→segment 전면해결은 밖.
        self.assertEqual(build_position_custom_fields(self._rec())["segment"], "")
        self.assertEqual(
            build_position_custom_fields(self._rec(), segment="engineering")["segment"],
            "engineering",
        )

    def test_no_salary_field(self) -> None:
        # SOT5: 연봉(salary_raw)은 포지션 등록 본문 밖(사장님 결정) — 명명 충돌 제거.
        fields = build_position_custom_fields(self._rec())
        self.assertNotIn("salary_raw", fields)
        self.assertNotIn("salary", fields)


class SafetyTests(unittest.TestCase):
    def test_every_outcome_no_external_no_secret(self) -> None:
        parsed = parse_discord_position_registration_request(
            "포지션 등록 https://www.wanted.co.kr/wd/363433"
        )
        outcome = run_position_registration(
            parsed,
            http_fetch=make_http_fetch(RICH_WANTED_HTML),
            clickup_search=make_clickup_search([]),
            clickup_create_task=make_clickup_create_task(),
            dry_run=True,
        )
        self.assertFalse(outcome.external_posting_sent)
        self.assertFalse(outcome.secret_emitted)

    def test_module_has_no_external_send_surface(self) -> None:
        import tools.multi_position_sourcing.position_registration as mod

        source_names = set(dir(mod))
        forbidden = {
            "send_email",
            "post_to_saramin",
            "post_to_jobkorea",
            "post_to_linkedin",
            "send_inmail",
            "post_external",
        }
        self.assertEqual(source_names & forbidden, set())


if __name__ == "__main__":
    unittest.main()
