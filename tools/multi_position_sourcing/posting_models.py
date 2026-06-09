from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class FetchResult:
    url: str
    ok: bool
    status_code: int = 0
    html: str = ""
    fetch_method: Literal["httpx", "playwright", "none"] = "none"
    reason: str = ""


@dataclass(frozen=True)
class ExtractedPosting:
    source_url: str
    ok: bool
    company: str = ""
    role: str = ""
    jd_text: str = ""
    image_urls: tuple[str, ...] = ()
    image_evidence_paths: tuple[str, ...] = ()
    fetch_method: str = "none"
    reason: str = ""


@dataclass(frozen=True)
class VisionAnalysis:
    is_job_posting: bool
    company: str = ""
    role: str = ""
    summary: str = ""
    key_requirements: tuple[str, ...] = ()
    confidence: float = 0.0


@dataclass(frozen=True)
class PostingRecognition:
    is_job_posting: bool
    source_url: str
    recognition_mode: Literal["text", "vision", "none"] = "none"
    company: str = ""
    role: str = ""
    jd_text: str = ""
    image_evidence_paths: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class ExistingPositionTask:
    task_id: str
    task_url: str = ""
    company: str = ""
    role: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class DuplicateMatch:
    task_id: str
    task_url: str
    match_basis: Literal["source_url", "company_role"]


@dataclass(frozen=True)
class RegistrationOutcome:
    status: Literal["created", "linked", "skipped"]
    is_new_task: bool
    reason: str
    task_id: str = ""
    task_url: str = ""
    comment_id: str = ""
    recognition_mode: str = "none"
    confidence: float = 0.0
    external_posting_sent: bool = False
    secret_emitted: bool = False
    dry_run: bool = True
