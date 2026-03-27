import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    resp = await client.post(
        "/v1/auth/register",
        json={
            "email": "admin@testorg.com",
            "password": "SecurePass123!",
            "org_name": "Test Org",
            "legal_name": "Test Org Ltd",
            "country": "ET",
            "industry": "fintech",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "org_id" in data
    assert "user_id" in data

    login_resp = await client.post(
        "/v1/auth/login",
        json={"email": "admin@testorg.com", "password": "SecurePass123!"},
    )
    assert login_resp.status_code == 401

    verify_resp = await client.post(
        "/v1/auth/verify-email",
        json={"token": "wrong-token"},
    )
    assert verify_resp.status_code == 400


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
