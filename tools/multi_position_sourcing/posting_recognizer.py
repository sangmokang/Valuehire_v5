from __future__ import annotations

from typing import Callable, Optional

from tools.multi_position_sourcing.posting_models import (
    ExtractedPosting,
    PostingRecognition,
    VisionAnalysis,
)

# JD signal vocabulary shared with posting_extractor (kept in sync with the contract).
_JD_SIGNALS: tuple[str, ...] = (
    "담당업무",
    "자격요건",
    "우대사항",
    "주요업무",
    "채용",
    "포지션",
    "JD",
    "회사소개",
    "responsibilities",
    "requirements",
    "qualifications",
)

# Number of distinct signals at which the text-signal score saturates to 1.0.
_SIGNAL_SATURATION = 4

VisionAnalyzer = Callable[[tuple[str, ...]], VisionAnalysis]


def text_jd_signal_score(text: str) -> float:
    """Return a 0..1 strength estimate of JD signals present in ``text``.

    The score is the count of distinct JD-signal terms found (case-insensitive),
    normalised against ``_SIGNAL_SATURATION`` and clamped to ``[0.0, 1.0]``.
    Empty/whitespace text scores ``0.0``.
    """

    if not text or not text.strip():
        return 0.0

    lowered = text.lower()
    distinct_hits = sum(1 for signal in _JD_SIGNALS if signal.lower() in lowered)
    if distinct_hits == 0:
        return 0.0

    score = distinct_hits / _SIGNAL_SATURATION
    if score > 1.0:
        return 1.0
    return score


def _text_is_sufficient(extracted: ExtractedPosting, score: float, threshold: float) -> bool:
    """Text path is sufficient only when company AND role are present and the
    signal score clears the confidence threshold (fail-closed otherwise)."""

    return bool(extracted.company) and bool(extracted.role) and score >= threshold


def recognize_posting(
    extracted: ExtractedPosting,
    *,
    vision_analyzer: Optional[VisionAnalyzer] = None,
    confidence_threshold: float = 0.55,
) -> PostingRecognition:
    """Recognise whether ``extracted`` is a job posting.

    Resolution order (fail-closed):
      1. If extraction failed -> mode "none", not a posting, carry the reason.
      2. If text is sufficient (company & role present and signal score high)
         -> mode "text".
      3. Else if image evidence paths exist and a vision analyzer is injected
         -> call it -> mode "vision" (company/role/confidence from VisionAnalysis).
      4. Otherwise -> mode "none", low confidence, reason "insufficient signal".

    Confidence is reported honestly; the registration handler is responsible for
    gating on (is_job_posting and confidence >= threshold).
    """

    source_url = extracted.source_url

    # 1. Fail-closed when extraction did not succeed.
    if not extracted.ok:
        reason = extracted.reason or "extraction failed"
        return PostingRecognition(
            is_job_posting=False,
            source_url=source_url,
            recognition_mode="none",
            confidence=0.0,
            reason=reason,
        )

    score = text_jd_signal_score(extracted.jd_text)

    # 2. Sufficient structured text -> text mode.
    if _text_is_sufficient(extracted, score, confidence_threshold):
        return PostingRecognition(
            is_job_posting=True,
            source_url=source_url,
            recognition_mode="text",
            company=extracted.company,
            role=extracted.role,
            jd_text=extracted.jd_text,
            image_evidence_paths=extracted.image_evidence_paths,
            confidence=score,
            reason="text signals sufficient",
        )

    # 3. Thin text but image evidence + a vision analyzer -> vision mode.
    if extracted.image_evidence_paths and vision_analyzer is not None:
        analysis = vision_analyzer(extracted.image_evidence_paths)
        company = analysis.company or extracted.company
        role = analysis.role or extracted.role
        return PostingRecognition(
            is_job_posting=bool(analysis.is_job_posting),
            source_url=source_url,
            recognition_mode="vision",
            company=company,
            role=role,
            jd_text=analysis.summary or extracted.jd_text,
            image_evidence_paths=extracted.image_evidence_paths,
            confidence=analysis.confidence,
            reason="vision analysis" if analysis.is_job_posting else "vision: not a posting",
        )

    # 4. Insufficient signal -> fail-closed none.
    return PostingRecognition(
        is_job_posting=False,
        source_url=source_url,
        recognition_mode="none",
        company=extracted.company,
        role=extracted.role,
        jd_text=extracted.jd_text,
        image_evidence_paths=extracted.image_evidence_paths,
        confidence=score,
        reason="insufficient signal",
    )
