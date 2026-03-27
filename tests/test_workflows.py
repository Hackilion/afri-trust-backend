import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_workflow_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/v1/workflows",
        json={"name": "Test Workflow"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_workflows_requires_auth(client: AsyncClient):
    resp = await client.get("/v1/workflows")
    assert resp.status_code == 401
