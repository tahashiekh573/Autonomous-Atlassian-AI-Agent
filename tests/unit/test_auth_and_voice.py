import httpx
import pytest
from fastapi import FastAPI

from tests.conftest import tested_connection, wait_for_run
from tests.fakes import FakeAtlassian, FakeLLM, FakeSTT, StatefulSite


async def _user(client: httpx.AsyncClient, email: str, role: str) -> dict[str, str]:
    created = await client.post(
        "/api/v1/users",
        json={
            "email": email,
            "display_name": email.split("@")[0],
            "password": "correct-horse-battery",
            "role": role,
        },
    )
    assert created.status_code == 201, created.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
        headers={"Authorization": ""},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_login_and_me(client: httpx.AsyncClient) -> None:
    headers = await _user(client, "op@acme.com", "operator")
    me = await client.get("/api/v1/auth/me", headers=headers)
    assert me.json()["role"] == "operator"


async def test_bad_password_is_rejected_and_audited(client: httpx.AsyncClient) -> None:
    await _user(client, "v@acme.com", "viewer")
    bad = await client.post("/api/v1/auth/login", json={"email": "v@acme.com", "password": "nope"})
    assert bad.status_code == 401
    audit = (await client.get("/api/v1/audit-logs")).json()
    assert any(a["action"] == "auth.login" and a["outcome"] == "denied" for a in audit)


async def test_short_passwords_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/users",
        json={"email": "x@acme.com", "display_name": "x", "password": "short", "role": "viewer"},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("role", "can_create_connection", "can_create_run"),
    [("viewer", False, False), ("operator", False, True), ("admin", True, True)],
)
async def test_role_permissions(
    client: httpx.AsyncClient,
    fake_atlassian: FakeAtlassian,
    role: str,
    can_create_connection: bool,
    can_create_run: bool,
) -> None:
    StatefulSite(fake_atlassian)
    connection_id = await tested_connection(client)
    headers = await _user(client, f"{role}@acme.com", role)
    conn = await client.post(
        "/api/v1/connections",
        headers=headers,
        json={
            "name": f"c-{role}",
            "site_url": "https://acme.atlassian.net",
            "email": "a@acme.com",
            "api_token": "t",
        },
    )
    assert (conn.status_code == 201) is can_create_connection
    run = await client.post(
        "/api/v1/runs", headers=headers, json={"connection_id": connection_id, "text": "x"}
    )
    assert (run.status_code == 202) is can_create_run
    assert (await client.get("/api/v1/runs", headers=headers)).status_code == 200


async def test_operator_cannot_approve_destructive_step(
    client: httpx.AsyncClient, app: FastAPI, fake_atlassian: FakeAtlassian, fake_llm: FakeLLM
) -> None:
    site = StatefulSite(fake_atlassian)
    site.issues["BANK-1"] = {
        "id": "1",
        "key": "BANK-1",
        "fields": {"summary": "Old", "labels": [], "subtasks": []},
    }
    fake_llm.plan = {
        "summary": "Delete",
        "operations": [
            {
                "id": "s1",
                "operation": "jira.delete_issue",
                "description": "d",
                "params": {"issue_key": "BANK-1"},
            }
        ],
    }
    connection_id = await tested_connection(client)
    headers = await _user(client, "op2@acme.com", "operator")
    run = (
        await client.post(
            "/api/v1/runs", headers=headers, json={"connection_id": connection_id, "text": "x"}
        )
    ).json()
    await wait_for_run(app, run["id"])
    denied = await client.post(
        f"/api/v1/runs/{run['id']}/approve", headers=headers, json={"operation_ids": ["s1"]}
    )
    assert denied.status_code == 403
    assert "BANK-1" in site.issues


async def test_voice_command_uses_same_pipeline(
    client: httpx.AsyncClient,
    app: FastAPI,
    fake_atlassian: FakeAtlassian,
    fake_llm: FakeLLM,
    fake_stt: FakeSTT,
) -> None:
    StatefulSite(fake_atlassian)
    fake_llm.plan = {
        "summary": "List",
        "operations": [
            {"id": "s1", "operation": "jira.list_projects", "description": "List", "params": {}}
        ],
    }
    connection_id = await tested_connection(client)
    response = await client.post(
        "/api/v1/voice/command",
        files={"audio": ("cmd.webm", b"\x1a\x45\xdf\xa3fake", "audio/webm")},
        data={"connection_id": connection_id},
    )
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["input_mode"] == "voice" and run["input_text"] == fake_stt.text
    await wait_for_run(app, run["id"])
    understanding_prompt = next(p for s, p in fake_llm.prompts if "Input Understanding" in s)
    assert "speech transcript" in understanding_prompt


async def test_voice_rejects_non_audio(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/voice/transcribe", files={"audio": ("x.txt", b"hello", "text/plain")}
    )
    assert response.status_code == 422


async def test_tts_not_configured_is_explained(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/v1/voice/speak", json={"text": "hello"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "configuration_error"


async def test_login_is_throttled_after_repeated_failures(client: httpx.AsyncClient) -> None:
    for _ in range(10):
        r = await client.post("/api/v1/auth/login", json={"email": "x@acme.com", "password": "bad"})
        assert r.status_code == 401
    blocked = await client.post(
        "/api/v1/auth/login", json={"email": "x@acme.com", "password": "bad"}
    )
    assert blocked.status_code == 429
