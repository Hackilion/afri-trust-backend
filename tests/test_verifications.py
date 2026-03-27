import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_verification_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/v1/verifications",
        json={
            "applicant_id": "00000000-0000-0000-0000-000000000000",
            "workflow_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert resp.status_code == 401
