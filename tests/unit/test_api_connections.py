from typing import Any

import httpx
import pytest

from tests.fakes import SITE_URL, FakeAtlassian, add_healthy_site

TOKEN = "atl-token-should-never-leak"


def payload(**overrides: Any) -> dict[str, Any]:
    return {
        "name": "acme",
        "site_url": SITE_URL + "/",
        "email": "ada@acme.com",
        "api_token": TOKEN,
        **overrides,
    }


async def create(client: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/connections", json=payload(**overrides))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_requires_api_key(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/connections", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "unauthenticated"
    assert error["request_id"] == response.headers["X-Request-ID"]


async def test_create_never_returns_token(client: httpx.AsyncClient) -> None:
    body = await create(client)
    assert body["site_url"] == SITE_URL  # trailing slash normalised
    assert body["last_test_status"] is None
    assert TOKEN not in str(body)
    listed = await client.get("/api/v1/connections")
    assert TOKEN not in listed.text
    assert [c["id"] for c in listed.json()] == [body["id"]]


async def test_duplicate_name_conflicts(client: httpx.AsyncClient) -> None:
    await create(client)
    response = await client.post("/api/v1/connections", json=payload())
    assert response.status_code == 409


@pytest.mark.parametrize(
    "site_url",
    [
        "http://acme.atlassian.net",
        "https://evil.example.com",
        "https://acme.atlassian.net/wiki",
        "https://acme.atlassian.net.evil.com",
    ],
)
async def test_rejects_unsafe_site_urls(client: httpx.AsyncClient, site_url: str) -> None:
    response = await client.post("/api/v1/connections", json=payload(site_url=site_url))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_validation_error_does_not_echo_token(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/connections", json=payload(email="not-an-email"))
    assert response.status_code == 422
    assert TOKEN not in response.text


async def test_get_and_delete(client: httpx.AsyncClient) -> None:
    conn = await create(client)
    assert (await client.get(f"/api/v1/connections/{conn['id']}")).status_code == 200
    assert (await client.delete(f"/api/v1/connections/{conn['id']}")).status_code == 204
    missing = await client.get(f"/api/v1/connections/{conn['id']}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


async def test_connection_test_all_products_ok(
    client: httpx.AsyncClient, fake_atlassian: FakeAtlassian
) -> None:
    add_healthy_site(fake_atlassian)
    conn = await create(client)

    response = await client.post(f"/api/v1/connections/{conn['id']}/test")

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ok"
    assert result["is_jira_admin"] is True
    assert result["account"]["display_name"] == "Ada Admin"
    assert {p["product"]: p["available"] for p in result["products"]} == {
        "jira": True,
        "jsm": True,
        "confluence": True,
        "assets": False,  # the fake site has no Assets workspace; must not make status partial
    }
    stored = (await client.get(f"/api/v1/connections/{conn['id']}")).json()
    assert stored["last_test_status"] == "ok"
    assert stored["capabilities"]["is_jira_admin"] is True
    # The decrypted token was actually used for Basic auth.
    assert fake_atlassian.calls[0].headers["Authorization"].startswith("Basic ")


async def test_connection_test_partial_when_products_missing(
    client: httpx.AsyncClient, fake_atlassian: FakeAtlassian
) -> None:
    add_healthy_site(fake_atlassian, admin=False)
    fake_atlassian.set("GET", "/rest/servicedeskapi/info", status=404)
    fake_atlassian.set("GET", "/wiki/api/v2/spaces", status=404)
    conn = await create(client)

    result = (await client.post(f"/api/v1/connections/{conn['id']}/test")).json()

    assert result["status"] == "partial"
    assert result["is_jira_admin"] is False
    products = {p["product"]: p for p in result["products"]}
    assert products["jira"]["available"] is True
    assert products["jsm"]["error_code"] == "atlassian_not_found"
    assert "not enabled" in products["confluence"]["detail"]


async def test_connection_test_bad_credentials_fails_without_further_calls(
    client: httpx.AsyncClient, fake_atlassian: FakeAtlassian
) -> None:
    fake_atlassian.add("GET", "/rest/api/3/myself", status=401, json={"message": "Unauthorized"})
    conn = await create(client)

    result = (await client.post(f"/api/v1/connections/{conn['id']}/test")).json()

    assert result["status"] == "failed"
    assert result["account"] is None
    assert all(p["error_code"] == "atlassian_auth_failed" for p in result["products"])
    assert fake_atlassian.calls_to("/rest/servicedeskapi/info") == []
    assert fake_atlassian.calls_to("/wiki/api/v2/spaces") == []


async def test_audit_log_records_actions(
    client: httpx.AsyncClient, fake_atlassian: FakeAtlassian
) -> None:
    add_healthy_site(fake_atlassian)
    conn = await create(client)
    await client.post(f"/api/v1/connections/{conn['id']}/test")

    entries = (await client.get("/api/v1/audit-logs")).json()

    assert [e["action"] for e in entries] == ["connection.test", "connection.create"]
    assert entries[0]["outcome"] == "ok"
    assert all(e["request_id"] != "-" for e in entries)
    assert TOKEN not in str(entries)
