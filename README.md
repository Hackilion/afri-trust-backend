# AfriTrust — Identity Verification Platform

AfriTrust is a Sumsub-style, multi-tenant identity verification (KYC) platform built for the African market. Organizations register, define custom verification tiers with dynamic attribute schemas, compose multi-step workflows, and verify end-users through document OCR, biometric face matching, and liveness detection — all via REST APIs or an embeddable Web SDK.

---

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture Overview](#architecture-overview)
- [API Integration Guide](#api-integration-guide)
  - [1. Register Your Organization](#1-register-your-organization)
  - [2. Create an API Key](#2-create-an-api-key)
  - [3. Define Tier Profiles](#3-define-tier-profiles)
  - [4. Create and Publish a Workflow](#4-create-and-publish-a-workflow)
  - [5. Verify an Applicant](#5-verify-an-applicant)
  - [6. Retrieve Verified Identity Data](#6-retrieve-verified-identity-data)
  - [7. Webhooks](#7-webhooks)
  - [8. Dashboard and Reporting](#8-dashboard-and-reporting)
- [Web SDK Integration Guide](#web-sdk-integration-guide)
  - [Basic Integration](#basic-integration)
  - [SDK Configuration Options](#sdk-configuration-options)
  - [SDK Callbacks](#sdk-callbacks)
  - [SDK Demo Page](#sdk-demo-page)
- [API Reference](#api-reference)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Development](#development)

---

## Quick Start

```bash
# Clone and setup
cd afri-trust-backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env

# Run (tables auto-created on startup)
PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

Open:
- **API Docs**: http://localhost:8000/docs
- **SDK Demo**: http://localhost:8000/verify

No database setup needed — uses SQLite by default. For production, switch to PostgreSQL by updating `DATABASE_URL` in `.env`.

### System Requirements

- Python 3.9+
- Tesseract OCR (`brew install tesseract` on macOS)

---

## Architecture Overview

```
Client App / Web SDK
        │
        ▼
   ┌─────────────────────────────────────┐
   │         FastAPI Application         │
   │                                     │
   │  Auth ─── Tier Profiles ─── Workflows
   │   │                           │
   │   ▼                           ▼
   │  API Keys    Applicants ─── Verifications
   │                    │              │
   │                    │    ┌─────────┼──────────┐
   │                    │    ▼         ▼          ▼
   │                  Consent   Documents    Biometrics
   │                    │      (Tesseract)  (DeepFace)
   │                    ▼         │          │
   │              Identity        ▼          ▼
   │               Data     OCR Extract  Face Match
   │                              │      Liveness
   │                              ▼
   │                         Audit Logs
   │                         Webhooks
   └─────────────────────────────────────┘
        │
        ▼
   SQLite / PostgreSQL
```

---

## API Integration Guide

All endpoints are under `/v1`. Authentication is via JWT (dashboard) or API Key (server-to-server).

**Base URL**: `http://localhost:8000`

### 1. Register Your Organization

```bash
curl -X POST http://localhost:8000/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@yourcompany.com",
    "password": "SecurePass123!",
    "org_name": "Your Company",
    "legal_name": "Your Company Ltd",
    "country": "ET",
    "industry": "fintech"
  }'
```

**Response:**
```json
{
  "org_id": "uuid",
  "user_id": "uuid",
  "email_verify_token": "token-string",
  "message": "Registration successful. Use the email_verify_token to verify your email."
}
```

Verify your email, then log in:

```bash
# Verify email
curl -X POST http://localhost:8000/v1/auth/verify-email \
  -H "Content-Type: application/json" \
  -d '{"token": "token-string-from-register"}'

# Login
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@yourcompany.com", "password": "SecurePass123!"}'
```

**Login response** returns `access_token` (JWT) and `refresh_token`. Use the JWT for all dashboard endpoints.

### 2. Create an API Key

API keys are used by your backend or SDK to authenticate server-to-server calls.

```bash
curl -X POST http://localhost:8000/v1/api-keys \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "production-key", "scopes": ["read", "write"]}'
```

**Response** includes the `api_key` — **save it immediately**, it is shown only once.

Use the API key in subsequent calls via the `X-API-Key` header:

```bash
curl -H "X-API-Key: YOUR_API_KEY" http://localhost:8000/v1/applicants
```

### 3. Define Tier Profiles

Tier profiles define **what data you collect and what checks you run** at each stage of verification. Each tier has:

- **`required_checks`** — which verification checks to perform
- **`attribute_schema`** — dynamic attributes to collect from the applicant (fully customizable)
- **`accepted_document_types`** — which document types to accept
- **`settings`** — tier-specific configuration (thresholds, country restrictions)

#### Available Check Types

| Check | Description |
|-------|-------------|
| `email` | Email address collected |
| `phone` | Phone number collected |
| `selfie` | Selfie uploaded + liveness check |
| `government_id` | Government document uploaded + OCR |
| `face_match` | Selfie compared with document photo |
| `liveness` | Liveness detection on selfie |
| `address_proof` | Address document uploaded |
| `pep_screening` | PEP/sanctions screening (stub) |
| `aml_screening` | AML screening (stub) |

#### Available Document Types

`passport`, `national_id`, `drivers_license`, `voter_card`, `residence_permit`, `address_proof`, `other`

#### Attribute Data Types

| Type | Input | Validation |
|------|-------|------------|
| `string` | Text input | `min_length`, `max_length`, `pattern` (regex) |
| `number` | Number input | `min`, `max` |
| `date` | Date picker | Must be `YYYY-MM-DD` format |
| `boolean` | Checkbox | — |
| `enum` | Dropdown | Must provide `options` array |
| `file` | File input | — |

#### Example: Create a Basic KYC Tier

```bash
curl -X POST http://localhost:8000/v1/tier-profiles \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Basic KYC",
    "description": "Email, phone, and selfie verification",
    "required_checks": ["email", "phone", "selfie"],
    "attribute_schema": [
      {
        "key": "full_name",
        "label": "Full Name",
        "data_type": "string",
        "required": true,
        "validation": {"min_length": 2, "max_length": 200}
      },
      {
        "key": "email_address",
        "label": "Email Address",
        "data_type": "string",
        "required": true
      },
      {
        "key": "phone_number",
        "label": "Phone Number",
        "data_type": "string",
        "required": true
      }
    ],
    "accepted_document_types": [],
    "settings": {}
  }'
```

#### Example: Create a Document + Biometric Tier

```bash
curl -X POST http://localhost:8000/v1/tier-profiles \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Document + Biometric",
    "description": "Government ID with OCR and face matching",
    "required_checks": ["government_id", "face_match"],
    "attribute_schema": [
      {"key": "id_number", "label": "ID Number", "data_type": "string", "required": true},
      {"key": "date_of_birth", "label": "Date of Birth", "data_type": "date", "required": true},
      {"key": "nationality", "label": "Nationality", "data_type": "string", "required": true},
      {
        "key": "gender",
        "label": "Gender",
        "data_type": "enum",
        "required": false,
        "options": ["male", "female", "other"]
      }
    ],
    "accepted_document_types": ["passport", "national_id", "drivers_license"],
    "settings": {"face_match_threshold": 0.85}
  }'
```

### 4. Create and Publish a Workflow

Workflows chain tier profiles into a multi-step verification sequence.

```bash
# Create a draft workflow
curl -X POST http://localhost:8000/v1/workflows \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"name": "Fintech Onboarding", "description": "Two-step KYC"}'

# Add step 1 (Basic KYC)
curl -X POST http://localhost:8000/v1/workflows/WORKFLOW_ID/steps \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"tier_profile_id": "BASIC_TIER_ID", "step_order": 1}'

# Add step 2 (Document + Biometric)
curl -X POST http://localhost:8000/v1/workflows/WORKFLOW_ID/steps \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{"tier_profile_id": "DOC_TIER_ID", "step_order": 2}'

# Publish (locks the workflow — no further edits)
curl -X POST http://localhost:8000/v1/workflows/WORKFLOW_ID/publish \
  -H "Authorization: Bearer YOUR_JWT"
```

**Workflow lifecycle**: `draft` → `published` → `archived`. Only published workflows can be used for verifications. Use `clone` to create a new draft from an existing workflow.

### 5. Verify an Applicant

This is the core verification flow. Your backend (or the Web SDK) drives these calls.

#### Step 1: Create an applicant

```bash
curl -X POST http://localhost:8000/v1/applicants \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "external_id": "your-user-id-123",
    "email": "user@example.com",
    "phone": "+251911223344",
    "full_name": "Abebe Kebede"
  }'
```

#### Step 2: Start a verification session

```bash
curl -X POST http://localhost:8000/v1/verifications \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "applicant_id": "APPLICANT_ID",
    "workflow_id": "PUBLISHED_WORKFLOW_ID"
  }'
```

#### Step 3: Check what the current step requires

```bash
curl http://localhost:8000/v1/verifications/SESSION_ID/required-data \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response** tells you exactly what to collect:

```json
{
  "current_step_order": 1,
  "tier_profile_name": "Basic KYC",
  "checks": {
    "required": ["email", "phone", "selfie"],
    "passed": [],
    "failed": [],
    "pending": ["email", "phone", "selfie"]
  },
  "attributes": {
    "schema": [
      {"key": "full_name", "label": "Full Name", "data_type": "string", "required": true}
    ],
    "missing_required": ["full_name", "email_address", "phone_number"],
    "collected": []
  },
  "accepted_document_types": []
}
```

#### Step 4: Submit attributes

```bash
curl -X POST http://localhost:8000/v1/verifications/SESSION_ID/attributes \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "attributes": {
      "full_name": "Abebe Kebede",
      "email_address": "user@example.com",
      "phone_number": "+251911223344"
    }
  }'
```

Attributes are validated against the tier's dynamic schema — wrong types, missing required fields, failed validation rules, and unknown keys all return `400` with a descriptive error.

#### Step 5: Upload a selfie (liveness + face match)

```bash
curl -X POST http://localhost:8000/v1/verifications/SESSION_ID/selfie \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@selfie.jpg"
```

**Response** includes real biometric results:

```json
{
  "liveness_passed": true,
  "liveness_score": 0.85,
  "face_match_passed": true,
  "face_match_score": 0.91
}
```

#### Step 6: Upload a document (OCR extraction)

```bash
curl -X POST http://localhost:8000/v1/verifications/SESSION_ID/documents \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "document_type=passport" \
  -F "file=@passport.jpg"
```

**Response** includes real OCR results:

```json
{
  "document_id": "uuid",
  "document_type": "passport",
  "extracted_data": {
    "full_name": "KEBEDE",
    "date_of_birth": "1992-03-15",
    "id_number": "ETH12345678",
    "nationality": "ETHIOPIAN"
  },
  "confidence_score": 0.72,
  "fraud_signals": {
    "quality_score": 0.8,
    "likely_blurry": false,
    "tamper_detected": false
  }
}
```

#### Step 7: Check final status

```bash
curl http://localhost:8000/v1/verifications/SESSION_ID \
  -H "X-API-Key: YOUR_API_KEY"
```

The orchestrator automatically advances through steps. When all checks pass in all steps, the session is `approved`. If any check fails, it is `rejected`.

### 6. Retrieve Verified Identity Data

After verification, retrieve the applicant's data using a consent-scoped token:

```bash
# Grant consent (returns a verification_token)
curl -X POST http://localhost:8000/v1/verifications/SESSION_ID/consent \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "granted_attributes": ["full_name", "email_address", "id_number"],
    "expires_in_days": 30
  }'

# Retrieve identity data using the token
curl "http://localhost:8000/v1/identities/APPLICANT_ID?attributes=full_name,id_number&verification_token=TOKEN" \
  -H "X-API-Key: YOUR_API_KEY"
```

Only attributes covered by an active consent grant and from approved sessions are returned.

### 7. Webhooks

Subscribe to verification events:

```bash
curl -X POST http://localhost:8000/v1/webhooks \
  -H "Authorization: Bearer YOUR_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-app.com/webhooks/kyc",
    "event_types": [
      "verification.created",
      "verification.step_completed",
      "verification.approved",
      "verification.rejected"
    ]
  }'
```

The response includes a `signing_secret`. All deliveries include an `X-AfriTrust-Signature` header (HMAC-SHA256) for payload verification.

**Event types**: `verification.created`, `verification.step_completed`, `verification.approved`, `verification.rejected`, `verification.needs_review`, `applicant.created`

### 8. Dashboard and Reporting

```bash
# Overview stats
curl http://localhost:8000/v1/dashboard/stats -H "Authorization: Bearer YOUR_JWT"

# Daily time series (last 30 days)
curl "http://localhost:8000/v1/dashboard/stats/timeseries?days=30" -H "Authorization: Bearer YOUR_JWT"

# Verification funnel (drop-off analysis)
curl "http://localhost:8000/v1/dashboard/stats/funnel?days=30" -H "Authorization: Bearer YOUR_JWT"

# Document and biometric stats
curl http://localhost:8000/v1/dashboard/stats/documents -H "Authorization: Bearer YOUR_JWT"
```

---

## Web SDK Integration Guide

The Web SDK is a zero-dependency, framework-agnostic JavaScript file that renders the entire verification flow as an embeddable widget.

### Basic Integration

Add two elements to your HTML page:

```html
<!-- 1. Include the SDK -->
<script src="http://localhost:8000/sdk/afritrust.js"></script>

<!-- 2. Add a container div -->
<div id="kyc-container"></div>

<!-- 3. Launch the verification -->
<script>
  AfriTrust.start({
    apiKey: "YOUR_API_KEY",
    containerId: "kyc-container",
    workflowId: "YOUR_PUBLISHED_WORKFLOW_ID",
    applicant: {
      external_id: "your-user-id",
      email: "user@example.com",
      full_name: "Abebe Kebede"
    },
    onComplete: function(result) {
      console.log("Verification complete:", result);
      // result.result is "approved", "rejected", or "pending"
      // result.sessionId is the verification session UUID
    },
    onError: function(err) {
      console.error("Verification error:", err);
    },
    onStepChange: function(step) {
      console.log("Step changed:", step);
    }
  });
</script>
```

The SDK will:
1. Create (or find) the applicant via the API
2. Start a verification session for the given workflow
3. Render dynamic forms based on each tier's attribute schema
4. Handle document uploads with type selection
5. Open the camera for selfie capture (with file upload fallback)
6. Show step-by-step progress
7. Display the final result

### SDK Configuration Options

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `apiKey` | `string` | Yes | Your organization's API key |
| `containerId` | `string` | Yes | ID of the HTML element to render into |
| `workflowId` | `string` | Yes | UUID of a published workflow |
| `applicant` | `object` | No | Applicant info: `external_id`, `email`, `phone`, `full_name` |
| `baseUrl` | `string` | No | API base URL (defaults to current origin) |
| `onComplete` | `function` | No | Called when verification finishes |
| `onError` | `function` | No | Called on any error |
| `onStepChange` | `function` | No | Called when the step changes |

### SDK Callbacks

**`onComplete(result)`**
```javascript
{
  result: "approved",     // or "rejected" or "pending"
  sessionId: "uuid",
  details: { ... }        // result_details from the API
}
```

**`onError(error)`**
```javascript
{
  status: 400,
  detail: "Missing required attribute: full_name",
  data: { ... }
}
```

**`onStepChange(step)`**
```javascript
{
  step: 2,
  tier: "Document + Biometric",
  event: "session_created"   // on first call
}
```

### SDK Demo Page

A built-in demo page is available at:

```
http://localhost:8000/verify
```

It provides a configuration panel where you can paste your API key and workflow ID, then launches the SDK widget with a live event log.

### React Integration Example

```jsx
import { useEffect, useRef } from 'react';

function KycWidget({ apiKey, workflowId, applicant, onComplete }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current || !window.AfriTrust) return;

    window.AfriTrust.start({
      apiKey,
      containerId: ref.current.id,
      workflowId,
      applicant,
      onComplete,
      onError: (err) => console.error('KYC error:', err),
    });
  }, [apiKey, workflowId]);

  return <div id="afritrust-kyc" ref={ref} />;
}
```

Load the SDK script in your `index.html`:
```html
<script src="http://localhost:8000/sdk/afritrust.js"></script>
```

---

## API Reference

Full interactive API documentation is available at `/docs` (Swagger) and `/redoc` (ReDoc) when the server is running.

### Endpoints Summary

| Group | Endpoints | Auth |
|-------|-----------|------|
| **Authentication** | `POST /v1/auth/register`, `verify-email`, `login`, `refresh`, `GET /v1/auth/me` | Public / JWT |
| **API Keys** | `POST`, `GET`, `DELETE /v1/api-keys` | JWT (admin) |
| **Tier Profiles** | `CRUD /v1/tier-profiles`, `GET check-catalogue` | JWT |
| **Workflows** | `CRUD /v1/workflows`, step management, `publish`, `archive`, `clone` | JWT (admin) |
| **Applicants** | `CRUD /v1/applicants`, `DELETE` | API Key / JWT |
| **Verifications** | `POST`, `GET`, `required-data`, `attributes`, `documents`, `selfie`, `liveness`, `review` | API Key / JWT |
| **KYC Data** | `GET /v1/applicants` (filtered), `GET verifications`, `kyc-summary` | JWT |
| **Dashboard** | `stats`, `timeseries`, `funnel`, `documents` | JWT |
| **Consent** | `POST consent`, `GET identities`, `list consents`, `revoke` | API Key / JWT |
| **Webhooks** | `CRUD /v1/webhooks`, `deliveries`, `test` | JWT (admin) |
| **Audit Logs** | `GET /v1/audit-logs` (filtered, paginated) | JWT (admin) |
| **System** | `GET /health`, `GET /` | Public |

---

## Project Structure

```
afri-trust-backend/
├── app/
│   ├── main.py                    # FastAPI app, startup, route mounting
│   ├── core/
│   │   ├── config.py              # Settings (env-based)
│   │   ├── security.py            # JWT, password hashing, API keys
│   │   └── exceptions.py          # HTTP exceptions
│   ├── db/
│   │   ├── base.py                # SQLAlchemy Base
│   │   ├── session.py             # Engine, session factory (SQLite/PG)
│   │   └── types.py               # Cross-DB GUID + JSON types
│   ├── models/                    # 10 SQLAlchemy models
│   ├── schemas/                   # Pydantic request/response DTOs
│   ├── api/
│   │   ├── deps.py                # Auth dependencies (JWT, API key)
│   │   └── v1/                    # 11 route modules
│   ├── services/
│   │   ├── orchestrator.py        # Verification state machine
│   │   ├── document_processor.py  # Tesseract OCR + fraud signals
│   │   ├── biometric_service.py   # DeepFace + OpenCV biometrics
│   │   ├── consent_service.py     # Token-scoped data access
│   │   ├── webhook_dispatcher.py  # HMAC-signed delivery + retries
│   │   └── audit_service.py       # Append-only audit trail
│   ├── storage/                   # File storage abstraction
│   └── sdk/
│       ├── afritrust.js           # Embeddable Web SDK (27KB)
│       └── demo.html              # SDK demo page
├── migrations/                    # Alembic (for PostgreSQL)
├── tests/                         # pytest test suite
├── postman/                       # Postman collection (63 requests)
├── requirements.txt
├── docker-compose.yml             # PostgreSQL (optional)
└── .env.example
```

---

## Configuration

Copy `.env.example` to `.env` and configure:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./afritrust.db` | Database connection string |
| `DATABASE_SSL` | `false` | Enable SSL for PostgreSQL |
| `JWT_SECRET_KEY` | — | Secret for JWT signing (change in production) |
| `API_KEY_PEPPER` | — | Salt for API key hashing |
| `STORAGE_BACKEND` | `local` | File storage (`local` or `s3`) |
| `UPLOAD_DIR` | `uploads` | Local upload directory |

### Database Options

**SQLite** (default, zero config):
```
DATABASE_URL=sqlite+aiosqlite:///./afritrust.db
```

**PostgreSQL** (production):
```
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
DATABASE_SSL=true
```

---

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run with auto-reload
PYTHONPATH=. uvicorn app.main:app --reload --port 8000

# Run tests
PYTHONPATH=. pytest tests/ -v

# Import Postman collection
# File: postman/AfriTrust_API.postman_collection.json
```

### Tesseract OCR Setup

The document processor requires Tesseract:

```bash
# macOS
brew install tesseract

# Ubuntu/Debian
sudo apt-get install tesseract-ocr

# Verify
tesseract --version
```

### Document Processing

Real OCR via Tesseract extracts text from identity documents, classifies document types, and computes fraud signals (blur detection, resolution check, quality scoring).

### Biometric Verification

Real face detection and matching via DeepFace (Facenet model) and OpenCV. Liveness detection uses image-quality heuristics (blur score, face-area ratio, brightness, color variance).
