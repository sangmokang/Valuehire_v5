from __future__ import annotations

import json
import unittest

from tools.multi_position_sourcing.posting_models import PostingRecognition
from tools.multi_position_sourcing.request_parser import parse_discord_position_registration_request


class RecordingRequester:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, payload=None):
        self.calls.append((method, url, headers, payload))
        if not self.responses:
            raise AssertionError("unexpected request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class ClickUpAdapterTests(unittest.TestCase):
    def test_create_task_uses_existing_registration_contract_and_raw_token_header(self) -> None:
        from tools.multi_position_sourcing.clickup_adapter import ClickUpClient

        requester = RecordingRequester(
            [{"id": "86new", "url": "https://app.clickup.com/t/86new"}]
        )
        client = ClickUpClient(token="secret-token", request_json=requester)

        task_id, task_url = client.create_task(
            "Acme - Backend Engineer",
            "회사: Acme\n포지션: Backend Engineer",
            "901814621569",
        )

        self.assertEqual((task_id, task_url), ("86new", "https://app.clickup.com/t/86new"))
        method, url, headers, payload = requester.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://api.clickup.com/api/v2/list/901814621569/task")
        self.assertEqual(headers["Authorization"], "secret-token")
        self.assertNotIn("Bearer", headers["Authorization"])
        self.assertEqual(payload["name"], "Acme - Backend Engineer")
        self.assertEqual(payload["description"], "회사: Acme\n포지션: Backend Engineer")
        self.assertFalse(payload["notify_all"])

    def test_create_comment_uses_task_comment_endpoint_without_notify(self) -> None:
        from tools.multi_position_sourcing.clickup_adapter import ClickUpClient

        requester = RecordingRequester([{"id": "comment-1"}])
        client = ClickUpClient(token="secret-token", request_json=requester)

        comment_id = client.create_comment("86abc", "검색 세팅 완료")

        self.assertEqual(comment_id, "comment-1")
        method, url, headers, payload = requester.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://api.clickup.com/api/v2/task/86abc/comment")
        self.assertEqual(headers["Authorization"], "secret-token")
        self.assertEqual(payload, {"comment_text": "검색 세팅 완료", "notify_all": False})

    def test_search_existing_positions_maps_tasks_for_existing_dedup_contract(self) -> None:
        from tools.multi_position_sourcing.clickup_adapter import ClickUpClient

        requester = RecordingRequester(
            [
                {
                    "tasks": [
                        {
                            "id": "86old",
                            "name": "Acme - Backend Engineer",
                            "url": "https://app.clickup.com/t/86old",
                            "description": "회사: Acme\n포지션: Backend Engineer\n원본 URL: https://www.wanted.co.kr/wd/363433",
                        }
                    ]
                },
                {"tasks": []},
            ]
        )
        client = ClickUpClient(token="secret-token", request_json=requester)
        recognition = PostingRecognition(
            is_job_posting=True,
            source_url="https://www.wanted.co.kr/wd/363433?utm=mail",
            company="Acme",
            role="Backend Engineer",
        )

        existing = client.search_existing_positions(recognition, list_id="901814621569")

        self.assertEqual(len(existing), 1)
        self.assertEqual(existing[0].task_id, "86old")
        self.assertEqual(existing[0].company, "Acme")
        self.assertEqual(existing[0].role, "Backend Engineer")
        self.assertEqual(existing[0].source_url, "https://www.wanted.co.kr/wd/363433")
        self.assertEqual(requester.calls[0][0], "GET")
        self.assertIn("/list/901814621569/task?", requester.calls[0][1])
        self.assertIn("page=0", requester.calls[0][1])

    def test_from_env_requires_token_without_printing_secret_value(self) -> None:
        from tools.multi_position_sourcing.clickup_adapter import ClickUpClient, ClickUpConfigError

        with self.assertRaises(ClickUpConfigError) as caught:
            ClickUpClient.from_env(env={})

        self.assertIn("CLICKUP_API_TOKEN", str(caught.exception))
        self.assertNotIn("secret", str(caught.exception).lower())

    def test_urllib_requester_raises_sanitized_error(self) -> None:
        from tools.multi_position_sourcing.clickup_adapter import ClickUpApiError, _parse_json_response

        with self.assertRaises(ClickUpApiError) as caught:
            _parse_json_response(status=500, raw=b'{"err":"bad","token":"secret-token"}')

        message = str(caught.exception)
        self.assertIn("ClickUp API HTTP 500", message)
        self.assertNotIn("secret-token", message)

    def test_payloads_are_json_serializable(self) -> None:
        from tools.multi_position_sourcing.clickup_adapter import ClickUpClient

        requester = RecordingRequester([{"id": "86new"}])
        client = ClickUpClient(token="secret-token", request_json=requester)
        client.create_task("Title", "Body", "901814621569")

        json.dumps(requester.calls[0][3], ensure_ascii=False)

    def test_adapter_wires_into_run_position_registration_live_contract(self) -> None:
        from tools.multi_position_sourcing.clickup_adapter import ClickUpClient
        from tools.multi_position_sourcing.position_registration import run_position_registration

        requester = RecordingRequester(
            [
                {"tasks": []},
                {"id": "86live", "url": "https://app.clickup.com/t/86live"},
            ]
        )
        client = ClickUpClient(token="secret-token", request_json=requester)
        parsed = parse_discord_position_registration_request(
            "포지션 등록\n"
            "시니어 백엔드 엔지니어\n"
            "회사소개\nAcme는 B2B SaaS 회사입니다.\n"
            "주요업무\n- 백엔드 API 설계\n"
            "자격요건\n- Python 5년 이상\n"
            "우대사항\n- Kubernetes 경험\n"
            "채용 포지션 JD입니다."
        )

        outcome = run_position_registration(
            parsed,
            clickup_search=lambda recognition: client.search_existing_positions(
                recognition, list_id="901814621569"
            ),
            clickup_create_task=client.create_task,
            clickup_list_id="901814621569",
            dry_run=False,
        )

        self.assertEqual(outcome.status, "created")
        self.assertEqual(outcome.task_id, "86live")
        self.assertFalse(outcome.external_posting_sent)
        self.assertEqual([call[0] for call in requester.calls], ["GET", "POST"])
        self.assertEqual(requester.calls[1][1], "https://api.clickup.com/api/v2/list/901814621569/task")


if __name__ == "__main__":
    unittest.main()
