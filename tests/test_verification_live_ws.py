"""WebSocket /v1/verifications/{id}/live."""

import uuid

# Note: avoid extra WebSocket reject tests with TestClient + shared :memory: SQLite —
# abrupt WS teardown can corrupt StaticPool for session teardown.

def test_verification_ws_streams_snapshot(test_app_client):
    email = f"ws_{uuid.uuid4().hex[:12]}@example.com"
    password = "TestPass123!"

    r = test_app_client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": password,
            "org_name": "WS Test Org",
            "legal_name": "WS Test Ltd",
            "country": "ET",
            "industry": "fintech",
        },
    )
    assert r.status_code == 201, r.text
    reg = r.json()
    otp = reg["email_verify_otp"]

    v = test_app_client.post(
        "/v1/auth/verify-email",
        json={"email": email, "otp": otp},
    )
    assert v.status_code == 200, v.text

    login = test_app_client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    tier = test_app_client.post(
        "/v1/tier-profiles",
        headers=headers,
        json={
            "name": "WS Tier",
            "description": "",
            "required_checks": [],
            "attribute_schema": [],
            "accepted_document_types": [],
            "settings": {},
        },
    )
    assert tier.status_code == 201, tier.text
    tier_id = tier.json()["id"]

    wf = test_app_client.post(
        "/v1/workflows",
        headers=headers,
        json={"name": "WS Workflow", "description": ""},
    )
    assert wf.status_code == 201, wf.text
    wf_id = wf.json()["id"]

    step = test_app_client.post(
        f"/v1/workflows/{wf_id}/steps",
        headers=headers,
        json={"tier_profile_id": tier_id, "step_order": 1, "is_optional": False},
    )
    assert step.status_code == 201, step.text

    pub = test_app_client.post(f"/v1/workflows/{wf_id}/publish", headers=headers)
    assert pub.status_code == 200, pub.text

    key = test_app_client.post(
        "/v1/api-keys",
        headers=headers,
        json={"name": "ws-test", "scopes": []},
    )
    assert key.status_code == 201, key.text
    raw_api_key = key.json()["api_key"]
    api_headers = {"X-API-Key": raw_api_key}

    app_resp = test_app_client.post(
        "/v1/applicants",
        headers=api_headers,
        json={"external_id": "ws-1", "email": "a@b.com", "full_name": "WS Applicant"},
    )
    assert app_resp.status_code == 201, app_resp.text
    applicant_id = app_resp.json()["id"]

    sess = test_app_client.post(
        "/v1/verifications",
        headers=api_headers,
        json={"applicant_id": applicant_id, "workflow_id": wf_id},
    )
    assert sess.status_code == 201, sess.text
    session_id = sess.json()["id"]

    from urllib.parse import quote

    q = quote(raw_api_key, safe="")
    with test_app_client.websocket_connect(
        f"/v1/verifications/{session_id}/live?api_key={q}"
    ) as ws:
        data = ws.receive_json()
        assert data["type"] == "verification_snapshot"
        assert data["session_id"] == session_id
        assert "status" in data
