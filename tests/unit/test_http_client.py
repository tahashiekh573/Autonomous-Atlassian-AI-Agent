import httpx
import pytest
from pydantic import SecretStr

from app.clients.atlassian.credentials import AtlassianCredentials, HttpPolicy
from app.clients.atlassian.errors import extract_error_message
from app.clients.atlassian.http_client import AtlassianHttpClient
from app.core.exceptions import (
    AtlassianApiError,
    AtlassianAuthError,
    AtlassianConnectionError,
    AtlassianNotFoundError,
    AtlassianPermissionError,
    AtlassianRateLimitError,
)
from tests.fakes import SITE_URL, FakeAtlassian

CREDS = AtlassianCredentials(SITE_URL, "ada@acme.com", SecretStr("secret-token"))


class SleepRecorder:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def make_client(
    fake: FakeAtlassian, sleep: SleepRecorder, max_retries: int = 3
) -> AtlassianHttpClient:
    policy = HttpPolicy(max_retries=max_retries, backoff_base_seconds=0.5, backoff_max_seconds=10)
    return AtlassianHttpClient(CREDS, policy, transport=fake.transport, sleep=sleep)


@pytest.fixture
def fake() -> FakeAtlassian:
    return FakeAtlassian()


@pytest.fixture
def sleep() -> SleepRecorder:
    return SleepRecorder()


async def test_get_returns_json_and_sends_basic_auth(
    fake: FakeAtlassian, sleep: SleepRecorder
) -> None:
    fake.add("GET", "/rest/api/3/myself", json={"accountId": "1"})
    client = make_client(fake, sleep)
    assert await client.request("GET", "/rest/api/3/myself", service="jira") == {"accountId": "1"}
    assert fake.calls[0].headers["Authorization"].startswith("Basic ")


async def test_204_returns_none(fake: FakeAtlassian, sleep: SleepRecorder) -> None:
    fake.add("DELETE", "/rest/api/3/issue/X-1", status=204)
    client = make_client(fake, sleep)
    assert await client.request("DELETE", "/rest/api/3/issue/X-1", service="jira") is None


async def test_429_honours_retry_after(fake: FakeAtlassian, sleep: SleepRecorder) -> None:
    fake.add("POST", "/rest/api/3/issue", status=429, headers={"Retry-After": "2"})
    fake.add("POST", "/rest/api/3/issue", status=201, json={"id": "10001"})
    client = make_client(fake, sleep)
    body = await client.request("POST", "/rest/api/3/issue", service="jira", json={})
    assert body == {"id": "10001"}
    assert sleep.delays == [2.0]


async def test_429_exhausted_raises_rate_limit(fake: FakeAtlassian, sleep: SleepRecorder) -> None:
    fake.add("GET", "/x", status=429)
    with pytest.raises(AtlassianRateLimitError):
        await make_client(fake, sleep, max_retries=2).request("GET", "/x", service="jira")
    assert len(fake.calls) == 3


async def test_post_500_is_not_retried(fake: FakeAtlassian, sleep: SleepRecorder) -> None:
    fake.add("POST", "/rest/api/3/issue", status=500, json={"errorMessages": ["boom"]})
    with pytest.raises(AtlassianApiError, match="boom"):
        await make_client(fake, sleep).request("POST", "/rest/api/3/issue", service="jira")
    assert len(fake.calls) == 1
    assert sleep.delays == []


async def test_get_503_is_retried_then_succeeds(fake: FakeAtlassian, sleep: SleepRecorder) -> None:
    fake.add("GET", "/x", status=503)
    fake.add("GET", "/x", status=200, json={"ok": True})
    assert await make_client(fake, sleep).request("GET", "/x", service="jira") == {"ok": True}
    assert len(sleep.delays) == 1
    assert 0 <= sleep.delays[0] <= 0.5


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, AtlassianAuthError),
        (403, AtlassianPermissionError),
        (404, AtlassianNotFoundError),
        (400, AtlassianApiError),
    ],
)
async def test_status_maps_to_typed_error(
    fake: FakeAtlassian, sleep: SleepRecorder, status: int, error: type[Exception]
) -> None:
    fake.add("GET", "/x", status=status, json={"errorMessages": ["nope"]})
    with pytest.raises(error) as info:
        await make_client(fake, sleep).request("GET", "/x", service="jira")
    assert info.value.upstream_status == status
    assert "secret-token" not in str(info.value)


async def test_network_error_retried_then_raises(sleep: SleepRecorder) -> None:
    def explode(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    fake = FakeAtlassian()
    fake.add_handler("GET", "/x", explode)
    with pytest.raises(AtlassianConnectionError):
        await make_client(fake, sleep, max_retries=2).request("GET", "/x", service="jira")
    assert len(sleep.delays) == 2


async def test_paginate_offset_jira_style(fake: FakeAtlassian, sleep: SleepRecorder) -> None:
    def page(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["startAt"])
        values = [{"n": i} for i in range(start, min(start + 2, 5))]
        return httpx.Response(200, json={"values": values, "total": 5, "isLast": start + 2 >= 5})

    fake.add_handler("GET", "/rest/api/3/project/search", page)
    client = make_client(fake, sleep)
    items = [
        i
        async for i in client.paginate_offset(
            "/rest/api/3/project/search", service="jira", page_size=2
        )
    ]
    assert [i["n"] for i in items] == [0, 1, 2, 3, 4]
    assert len(fake.calls) == 3


async def test_paginate_offset_jsm_style_and_max_items(
    fake: FakeAtlassian, sleep: SleepRecorder
) -> None:
    def page(request: httpx.Request) -> httpx.Response:
        start = int(request.url.params["start"])
        return httpx.Response(
            200, json={"values": [{"n": start}, {"n": start + 1}], "isLastPage": False}
        )

    fake.add_handler("GET", "/rest/servicedeskapi/servicedesk", page)
    client = make_client(fake, sleep)
    items = [
        i
        async for i in client.paginate_offset(
            "/rest/servicedeskapi/servicedesk",
            service="jsm",
            start_param="start",
            limit_param="limit",
            last_page_key="isLastPage",
            page_size=2,
            max_items=3,
        )
    ]
    assert [i["n"] for i in items] == [0, 1, 2]


async def test_paginate_cursor_follows_next_link(fake: FakeAtlassian, sleep: SleepRecorder) -> None:
    def page(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("cursor") == "abc":
            return httpx.Response(200, json={"results": [{"key": "B"}], "_links": {}})
        return httpx.Response(
            200,
            json={"results": [{"key": "A"}], "_links": {"next": "/wiki/api/v2/spaces?cursor=abc"}},
        )

    fake.add_handler("GET", "/wiki/api/v2/spaces", page)
    client = make_client(fake, sleep)
    keys = [s["key"] async for s in client.paginate_cursor("/wiki/api/v2/spaces", service="c")]
    assert keys == ["A", "B"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"errorMessages": ["bad"], "errors": {"summary": "required"}}, "bad; summary: required"),
        ({"errors": [{"title": "Forbidden", "detail": "no access"}]}, "no access"),
        ({"errorMessage": "JSM says no"}, "JSM says no"),
    ],
)
def test_extract_error_message_formats(body: dict[str, object], expected: str) -> None:
    assert extract_error_message(httpx.Response(400, json=body)) == expected
