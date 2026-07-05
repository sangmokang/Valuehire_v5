from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

from .posting_models import ExistingPositionTask, PostingRecognition
from .position_registration import FY26_CLIENTS_POSITION_LIST_ID


JsonRequester = Callable[[str, str, Mapping[str, str], Mapping[str, object] | None], Mapping[str, Any]]


class ClickUpConfigError(RuntimeError):
    pass


class ClickUpApiError(RuntimeError):
    pass


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _strip_secret_markers(text: str) -> str:
    # Keep errors useful but avoid echoing obvious token fields from API/debug bodies.
    return re.sub(r'("?(?:token|authorization|api[_-]?key)"?\s*[:=]\s*)"?[^",}\s]+', r"\1[redacted]", text, flags=re.IGNORECASE)


def _parse_json_response(*, status: int, raw: bytes) -> Mapping[str, Any]:
    text = raw.decode("utf-8", errors="replace")
    try:
        payload: Any = json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        raise ClickUpApiError(f"ClickUp API returned non-JSON response (HTTP {status})") from exc
    if not 200 <= status < 300:
        detail = _strip_secret_markers(text)[:500]
        raise ClickUpApiError(f"ClickUp API HTTP {status}: {detail}")
    if not isinstance(payload, Mapping):
        raise ClickUpApiError(f"ClickUp API returned unexpected JSON shape (HTTP {status})")
    return payload


def _urllib_request_json(
    method: str,
    url: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object] | None = None,
) -> Mapping[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return _parse_json_response(status=response.status, raw=response.read())
    except urllib.error.HTTPError as exc:
        raise ClickUpApiError(
            f"ClickUp API HTTP {exc.code}: {_strip_secret_markers(exc.read().decode('utf-8', errors='replace'))[:500]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ClickUpApiError(f"ClickUp API request failed: {exc.reason}") from exc


def _join_base(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _task_url(task_id: str, payload: Mapping[str, Any]) -> str:
    url = str(payload.get("url") or "").strip()
    if url:
        return url
    return f"https://app.clickup.com/t/{task_id}" if task_id else ""


def _parse_title(name: str) -> tuple[str, str]:
    if " - " not in name:
        return "", name.strip()
    company, role = name.split(" - ", 1)
    return company.strip(), role.strip()


def _field_from_body(body: str, label: str) -> str:
    pattern = re.compile(rf"^{re.escape(label)}\s*:\s*(.+)$", re.MULTILINE)
    match = pattern.search(body or "")
    if not match:
        return ""
    value = match.group(1).strip()
    return "" if value == "(미상)" else value


@dataclass(frozen=True)
class ClickUpClient:
    """Thin ClickUp REST adapter for existing position-registration callables.

    The class is inert until its methods are called. Tests inject ``request_json``;
    production uses stdlib urllib and requires an explicit token from env.
    """

    token: str
    base_url: str = "https://api.clickup.com/api/v2"
    request_json: JsonRequester = field(default=_urllib_request_json, repr=False)

    @classmethod
    def from_env(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        token_key: str = "CLICKUP_API_TOKEN",
        **kwargs: Any,
    ) -> "ClickUpClient":
        source = os.environ if env is None else env
        token = (source.get(token_key) or "").strip()
        if not token:
            raise ClickUpConfigError(f"{token_key} is required for ClickUp write adapter")
        return cls(token=token, **kwargs)

    def create_task(self, title: str, body: str, list_id: str | None = None) -> tuple[str, str]:
        destination = (list_id or FY26_CLIENTS_POSITION_LIST_ID).strip()
        if not destination:
            raise ClickUpConfigError("ClickUp list_id is required")
        payload = {
            "name": (title or "").strip() or "포지션",
            "description": body or "",
            "notify_all": False,
        }
        response = self.request_json(
            "POST",
            _join_base(self.base_url, f"list/{urllib.parse.quote(destination)}/task"),
            _headers(self.token),
            payload,
        )
        task_id = str(response.get("id") or "").strip()
        if not task_id:
            raise ClickUpApiError("ClickUp create task response missing id")
        return task_id, _task_url(task_id, response)

    def create_comment(self, task_id: str, body: str) -> str:
        task_id = (task_id or "").strip()
        if not task_id:
            raise ClickUpConfigError("ClickUp task_id is required")
        payload = {"comment_text": body or "", "notify_all": False}
        response = self.request_json(
            "POST",
            _join_base(self.base_url, f"task/{urllib.parse.quote(task_id)}/comment"),
            _headers(self.token),
            payload,
        )
        comment_id = str(response.get("id") or response.get("comment_id") or "").strip()
        if not comment_id and isinstance(response.get("comment"), Mapping):
            comment_id = str(response["comment"].get("id") or "").strip()  # type: ignore[index]
        if not comment_id:
            raise ClickUpApiError("ClickUp create comment response missing id")
        return comment_id

    def list_position_tasks(
        self,
        *,
        list_id: str = FY26_CLIENTS_POSITION_LIST_ID,
        max_pages: int = 5,
    ) -> tuple[ExistingPositionTask, ...]:
        destination = (list_id or "").strip()
        if not destination:
            raise ClickUpConfigError("ClickUp list_id is required")

        out: list[ExistingPositionTask] = []
        for page in range(max(1, max_pages)):
            query = urllib.parse.urlencode(
                {
                    "archived": "false",
                    "include_closed": "true",
                    "include_markdown_description": "true",
                    "page": str(page),
                }
            )
            response = self.request_json(
                "GET",
                _join_base(self.base_url, f"list/{urllib.parse.quote(destination)}/task?{query}"),
                _headers(self.token),
                None,
            )
            tasks = response.get("tasks")
            if not isinstance(tasks, list) or not tasks:
                break
            for task in tasks:
                if isinstance(task, Mapping):
                    parsed = self._existing_position_task(task)
                    if parsed is not None:
                        out.append(parsed)
        return tuple(out)

    def search_existing_positions(
        self,
        _recognition: PostingRecognition,
        *,
        list_id: str = FY26_CLIENTS_POSITION_LIST_ID,
    ) -> tuple[ExistingPositionTask, ...]:
        return self.list_position_tasks(list_id=list_id)

    @staticmethod
    def _existing_position_task(task: Mapping[str, Any]) -> ExistingPositionTask | None:
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            return None
        name = str(task.get("name") or "").strip()
        body = str(
            task.get("markdown_description")
            or task.get("description")
            or task.get("text_content")
            or ""
        )
        company = _field_from_body(body, "회사")
        role = _field_from_body(body, "포지션")
        if not company or not role:
            title_company, title_role = _parse_title(name)
            company = company or title_company
            role = role or title_role
        return ExistingPositionTask(
            task_id=task_id,
            task_url=str(task.get("url") or "").strip() or f"https://app.clickup.com/t/{task_id}",
            company=company,
            role=role,
            source_url=_field_from_body(body, "원본 URL"),
        )
