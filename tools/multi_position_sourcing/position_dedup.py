from __future__ import annotations

import re
from typing import Sequence
from urllib.parse import urlparse, urlunparse

from tools.multi_position_sourcing.posting_models import (
    DuplicateMatch,
    ExistingPositionTask,
    PostingRecognition,
)

# Company suffix / legal-entity markers stripped during normalization.
# Korean markers are removed via _KOREAN_CORP_RE; English markers here.
_ENGLISH_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:co\.?\s*,?\s*ltd\.?|company\s+limited|inc\.?|llc|ltd\.?|corp\.?|"
    r"corporation|incorporated|gmbh|plc)\b",
    re.IGNORECASE,
)
_KOREAN_CORP_RE = re.compile(r"㈜|\(\s*주\s*\)|주식회사")
_PUNCT_RE = re.compile(r"[^0-9a-z가-힣\s]+", re.IGNORECASE)
_WHITESPACE_RE = re.compile(r"\s+")
_MULTISLASH_RE = re.compile(r"/+")


def normalize_company(name: str) -> str:
    """Normalize a company name for duplicate matching.

    Lowercases, strips Korean (㈜/(주)/주식회사) and English (Inc/Co.,Ltd/LLC/
    Corp...) entity markers, drops punctuation, and collapses whitespace.
    """
    text = (name or "").strip().lower()
    if not text:
        return ""
    text = _KOREAN_CORP_RE.sub(" ", text)
    text = _ENGLISH_COMPANY_SUFFIX_RE.sub(" ", text)
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def normalize_role(title: str) -> str:
    """Normalize a role/title for duplicate matching.

    Lowercases, drops punctuation, and collapses whitespace.
    """
    text = (title or "").strip().lower()
    if not text:
        return ""
    text = _PUNCT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def canonical_posting_url(url: str) -> str:
    """Canonicalize a posting URL for equality comparison.

    Forces https, lowercases the host, drops query/fragment, collapses
    duplicate slashes, and strips any trailing slash. Wanted posting paths
    (/wd/{id}) are preserved as-is by the generic rules.
    """
    raw = (url or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path = _MULTISLASH_RE.sub("/", parsed.path).rstrip("/")
    return urlunparse(("https", host, path, "", "", ""))


def find_duplicate_position(
    recognition: PostingRecognition,
    existing: Sequence[ExistingPositionTask],
) -> DuplicateMatch | None:
    """Find an existing task that duplicates the recognized posting.

    Source-URL match (canonicalized) takes precedence over a
    normalized company+role match. Empty/blank keys never match.
    Returns None when nothing matches.
    """
    canonical_source = canonical_posting_url(recognition.source_url)
    norm_company = normalize_company(recognition.company)
    norm_role = normalize_role(recognition.role)

    company_role_match: DuplicateMatch | None = None

    for task in existing:
        if canonical_source and canonical_posting_url(task.source_url) == canonical_source:
            return DuplicateMatch(
                task_id=task.task_id,
                task_url=task.task_url,
                match_basis="source_url",
            )
        if (
            company_role_match is None
            and norm_company
            and norm_role
            and normalize_company(task.company) == norm_company
            and normalize_role(task.role) == norm_role
        ):
            company_role_match = DuplicateMatch(
                task_id=task.task_id,
                task_url=task.task_url,
                match_basis="company_role",
            )

    return company_role_match
