import pytest
from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str = "tp@test.com") -> str:
    await client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "Pass123!",
            "org_name": "TP Org",
        },
    )
    from sqlalchemy import text
    return ""


@pytest.mark.asyncio
async def test_check_catalogue_requires_auth(client: AsyncClient):
    resp = await client.get("/v1/tier-profiles/check-catalogue")
    assert resp.status_code == 401
