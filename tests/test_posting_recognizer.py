from __future__ import annotations

import unittest

from tools.multi_position_sourcing.posting_models import (
    ExtractedPosting,
    VisionAnalysis,
)
from tools.multi_position_sourcing.posting_recognizer import (
    recognize_posting,
    text_jd_signal_score,
)


def _fake_vision(analysis: VisionAnalysis):
    """Return a plain function that ignores its input and returns a canned VisionAnalysis."""

    calls: list[tuple[str, ...]] = []

    def analyzer(image_paths: tuple[str, ...]) -> VisionAnalysis:
        calls.append(tuple(image_paths))
        return analysis

    analyzer.calls = calls  # type: ignore[attr-defined]
    return analyzer


RICH_JD = (
    "주요업무\n- 백엔드 API 설계 및 구현\n"
    "자격요건\n- Python 3년 이상\n- 분산 시스템 경험\n"
    "우대사항\n- Kubernetes 경험\n"
    "담당업무\n- 데이터 파이프라인 운영\n"
    "회사소개\nAcme는 핀테크 스타트업입니다.\n"
    "responsibilities and requirements and qualifications are listed above."
)


class TextSignalScoreTests(unittest.TestCase):
    def test_rich_text_scores_high(self) -> None:
        self.assertGreaterEqual(text_jd_signal_score(RICH_JD), 0.55)

    def test_empty_text_scores_zero(self) -> None:
        self.assertEqual(text_jd_signal_score(""), 0.0)

    def test_thin_text_scores_low(self) -> None:
        self.assertLess(text_jd_signal_score("안녕하세요 반갑습니다 오늘 날씨가 좋네요"), 0.55)


class RecognizePostingTests(unittest.TestCase):
    def test_text_sufficient_recognized_as_text_mode(self) -> None:
        extracted = ExtractedPosting(
            source_url="https://www.wanted.co.kr/wd/12345",
            ok=True,
            company="Acme",
            role="Backend Engineer",
            jd_text=RICH_JD,
            fetch_method="httpx",
        )

        result = recognize_posting(extracted, confidence_threshold=0.55)

        self.assertEqual(result.recognition_mode, "text")
        self.assertTrue(result.is_job_posting)
        self.assertGreaterEqual(result.confidence, 0.55)
        self.assertEqual(result.company, "Acme")
        self.assertEqual(result.role, "Backend Engineer")
        self.assertEqual(result.source_url, "https://www.wanted.co.kr/wd/12345")
        self.assertEqual(result.jd_text, RICH_JD)

    def test_thin_text_with_images_uses_vision(self) -> None:
        extracted = ExtractedPosting(
            source_url="https://example.com/post/1",
            ok=True,
            company="",
            role="",
            jd_text="채용 공고입니다",  # thin: not enough company/role/signals
            image_evidence_paths=("artifacts/position_registration/img_0.png",),
            fetch_method="playwright",
        )
        analyzer = _fake_vision(
            VisionAnalysis(
                is_job_posting=True,
                company="Acme",
                role="Backend Engineer",
                summary="백엔드 엔지니어 채용",
                key_requirements=("Python", "분산 시스템"),
                confidence=0.9,
            )
        )

        result = recognize_posting(
            extracted, vision_analyzer=analyzer, confidence_threshold=0.55
        )

        self.assertEqual(result.recognition_mode, "vision")
        self.assertTrue(result.is_job_posting)
        self.assertEqual(result.company, "Acme")
        self.assertEqual(result.role, "Backend Engineer")
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(
            result.image_evidence_paths,
            ("artifacts/position_registration/img_0.png",),
        )
        # vision analyzer was actually called with the evidence paths
        self.assertEqual(
            analyzer.calls,  # type: ignore[attr-defined]
            [("artifacts/position_registration/img_0.png",)],
        )

    def test_not_ok_extracted_is_fail_closed(self) -> None:
        extracted = ExtractedPosting(
            source_url="https://example.com/blocked",
            ok=False,
            reason="403 blocked",
        )

        result = recognize_posting(extracted)

        self.assertEqual(result.recognition_mode, "none")
        self.assertFalse(result.is_job_posting)
        self.assertNotEqual(result.reason, "")
        self.assertEqual(result.source_url, "https://example.com/blocked")

    def test_thin_text_no_images_is_none_mode_low_confidence(self) -> None:
        extracted = ExtractedPosting(
            source_url="https://example.com/post/2",
            ok=True,
            company="",
            role="",
            jd_text="안녕하세요",
            fetch_method="httpx",
        )

        result = recognize_posting(extracted, confidence_threshold=0.55)

        self.assertEqual(result.recognition_mode, "none")
        self.assertFalse(result.is_job_posting)
        self.assertLess(result.confidence, 0.55)
        self.assertIn("insufficient signal", result.reason)

    def test_vision_says_not_a_posting(self) -> None:
        extracted = ExtractedPosting(
            source_url="https://example.com/post/3",
            ok=True,
            jd_text="채용",
            image_evidence_paths=("artifacts/position_registration/img_x.png",),
            fetch_method="playwright",
        )
        analyzer = _fake_vision(
            VisionAnalysis(is_job_posting=False, confidence=0.2)
        )

        result = recognize_posting(
            extracted, vision_analyzer=analyzer, confidence_threshold=0.55
        )

        self.assertEqual(result.recognition_mode, "vision")
        self.assertFalse(result.is_job_posting)

    def test_vision_path_not_taken_without_analyzer(self) -> None:
        # thin text + images present but no analyzer injected -> fail-closed none
        extracted = ExtractedPosting(
            source_url="https://example.com/post/4",
            ok=True,
            jd_text="채용",
            image_evidence_paths=("artifacts/position_registration/img_y.png",),
            fetch_method="playwright",
        )

        result = recognize_posting(extracted, vision_analyzer=None)

        self.assertEqual(result.recognition_mode, "none")
        self.assertFalse(result.is_job_posting)


if __name__ == "__main__":
    unittest.main()
