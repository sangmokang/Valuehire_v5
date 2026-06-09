from __future__ import annotations

import urllib.parse

URL_SAFE_SCHEMES = {"http", "https"}


def safe_artifact_url(url: str) -> str:
    """Return a URL safe for logs/artifacts: scheme + host + path only."""
    raw = str(url or "")
    if not raw:
        return ""
    try:
        parsed = urllib.parse.urlsplit(raw)
    except Exception:
        return ""

    if parsed.scheme in URL_SAFE_SCHEMES and parsed.hostname:
        host = parsed.hostname.lower()
        try:
            port = parsed.port
        except ValueError:
            port = None
        if port is not None:
            host = f"{host}:{port}"
        return urllib.parse.urlunsplit((parsed.scheme, host, parsed.path, "", ""))
    if parsed.scheme == "about":
        return urllib.parse.urlunsplit((parsed.scheme, "", parsed.path, "", ""))
    if parsed.scheme:
        return f"{parsed.scheme}://<redacted>"
    return parsed.path


def safe_exception_label(exc: BaseException, *, action: str) -> str:
    return f"{type(exc).__name__}: {action} without exposing details"
