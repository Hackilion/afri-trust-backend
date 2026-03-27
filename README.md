# AfriTrust — Identity Verification Platform

AfriTrust is a multi-tenant identity verification (KYC) platform. Organizations define custom verification workflows, and their client applications verify end-users through document OCR, biometric face matching, and liveness detection — via REST API or an embeddable Web SDK.

---

## Quick Start

```bash
cd afri-trust-backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
PYTHONPATH=. uvicorn app.main:app --reload --port 8000
```

- **Swagger Docs**: http://localhost:8000/docs
- **SDK Demo**: http://localhost:8000/verify

Requires Python 3.9+ and Tesseract OCR (`brew install tesseract` on macOS).

---

## Prerequisites (Admin Setup)

Before integrating, an organization admin must set up the verification workflow via the dashboard or admin APIs. This is a one-time setup.

**1. Register and get an API key**

```bash
# Register
curl -X POST http://localhost:8000/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourco.com","password":"SecurePass1!","org_name":"Your Company"}'

# Verify email (use the token from the register response)
curl -X POST http://localhost:8000/v1/auth/verify-email \
  -H "Content-Type: application/json" \
  -d '{"token":"TOKEN_FROM_REGISTER"}'

# Login (returns JWT)
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@yourco.com","password":"SecurePass1!"}'

# Create an API key (save the returned api_key — shown only once)
curl -X POST http://localhost:8000/v1/api-keys \
  -H "Authorization: Bearer JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"production-key","scopes":["read","write"]}'
```

**2. Create tier profiles** (what data to collect and what checks to run)

**3. Create a workflow** (chain tiers into steps), add steps, and **publish** it

Once you have an **API key** and a **published workflow ID**, you are ready to integrate.

> Full admin API details: see `/docs` (Swagger) at http://localhost:8000/docs

---

## Integration Option 1: REST API

Use this when your backend drives the verification flow (mobile app, server-to-server, custom UI).

All integration endpoints use the `X-API-Key` header for authentication.

### Complete Flow

```
Create Applicant → Start Session → Loop: Get Required Data → Submit Data → End
```

### Step 1: Create an Applicant

Register the end-user you want to verify. The `external_id` is your system's user ID (used for deduplication).

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

```json
// Response
{ "id": "applicant-uuid", "org_id": "...", "external_id": "your-user-id-123", ... }
```

### Step 2: Start a Verification Session

```bash
curl -X POST http://localhost:8000/v1/verifications \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "applicant_id": "APPLICANT_UUID",
    "workflow_id": "PUBLISHED_WORKFLOW_UUID"
  }'
```

```json
// Response
{ "id": "session-uuid", "status": "created", "current_step_order": 1, ... }
```

### Step 3: Get Required Data for the Current Step

This is the key endpoint. It tells you exactly what the current step needs — which attributes to collect, which checks are pending, and which document types are accepted.

```bash
curl http://localhost:8000/v1/verifications/SESSION_UUID/required-data \
  -H "X-API-Key: YOUR_API_KEY"
```

```json
{
  "current_step_order": 1,
  "tier_profile_name": "Basic KYC",
  "step_status": "pending",
  "checks": {
    "required": ["email", "phone", "selfie"],
    "passed": [],
    "failed": [],
    "pending": ["email", "phone", "selfie"]
  },
  "attributes": {
    "schema": [
      { "key": "full_name", "label": "Full Name", "data_type": "string", "required": true,
        "validation": { "min_length": 2, "max_length": 200 } },
      { "key": "email_address", "label": "Email", "data_type": "string", "required": true },
      { "key": "phone_number", "label": "Phone", "data_type": "string", "required": true }
    ],
    "missing_required": ["full_name", "email_address", "phone_number"],
    "collected": []
  },
  "accepted_document_types": []
}
```

Use `attributes.schema` to render a form. Use `checks.pending` to decide what else to submit (selfie, document). Use `accepted_document_types` to show the right upload options.

### Step 4: Submit Attributes

Submit the data collected from the user. Values are validated against the tier's dynamic schema (types, required flags, min/max, pattern, enum options).

```bash
curl -X POST http://localhost:8000/v1/verifications/SESSION_UUID/attributes \
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

Validation errors return `400` with descriptive messages:
```json
{ "detail": "Missing required attribute: full_name; Attribute 'email_address' must be a string" }
```

### Step 5: Upload a Selfie

Submits the image for liveness detection and (if the tier requires it) face matching.

```bash
curl -X POST http://localhost:8000/v1/verifications/SESSION_UUID/selfie \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@selfie.jpg"
```

```json
{
  "liveness_passed": true,
  "liveness_score": 0.85,
  "face_match_passed": true,
  "face_match_score": 0.91
}
```

### Step 6: Upload a Document

Submits an identity document for OCR text extraction, classification, and fraud signal analysis.

```bash
curl -X POST http://localhost:8000/v1/verifications/SESSION_UUID/documents \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "document_type=passport" \
  -F "file=@passport.jpg"
```

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
    "tamper_detected": false,
    "resolution": "800x500"
  }
}
```

The `document_type` must be one of the tier's `accepted_document_types`. Submitting an unsupported type returns `400`.

### Step 7: Check Status and Repeat

After each submission, call `required-data` again. If the step advanced (all checks passed, all required attributes collected), `current_step_order` will increment. Continue submitting data for each step until the session resolves.

```bash
curl http://localhost:8000/v1/verifications/SESSION_UUID \
  -H "X-API-Key: YOUR_API_KEY"
```

```json
{
  "id": "session-uuid",
  "status": "approved",
  "result": "approved",
  "current_step_order": 2,
  "steps": [ ... ]
}
```

**Session outcomes**: `approved` (all checks passed in all steps), `rejected` (a check failed), `in_progress` (waiting for data).

### Step 8: Retrieve Verified Data (Optional)

After approval, retrieve the applicant's verified attributes using a consent-scoped token:

```bash
# Grant consent
curl -X POST http://localhost:8000/v1/verifications/SESSION_UUID/consent \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"granted_attributes":["full_name","id_number"],"expires_in_days":30}'

# Retrieve data
curl "http://localhost:8000/v1/identities/APPLICANT_UUID?attributes=full_name,id_number&verification_token=TOKEN" \
  -H "X-API-Key: YOUR_API_KEY"
```

### Listening for Results (Webhooks)

Instead of polling, subscribe to webhook events to be notified when verifications complete:

```bash
curl -X POST http://localhost:8000/v1/webhooks \
  -H "Authorization: Bearer JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-app.com/webhooks/kyc",
    "event_types": ["verification.approved","verification.rejected","verification.step_completed"]
  }'
```

Events are signed with HMAC-SHA256 via the `X-AfriTrust-Signature` header using the `signing_secret` returned at creation.

---

## Integration Option 2: Web SDK

Use this when you want a drop-in verification UI with zero frontend work. The SDK is a single JavaScript file (27KB, no dependencies) that renders the entire flow: forms, document upload, camera selfie capture, step progress, and result screen.

### Embed in 3 Lines

```html
<script src="http://localhost:8000/sdk/afritrust.js"></script>
<div id="kyc-container"></div>
<script>
  AfriTrust.start({
    apiKey: "YOUR_API_KEY",
    containerId: "kyc-container",
    workflowId: "PUBLISHED_WORKFLOW_UUID",
    applicant: {
      external_id: "your-user-id",
      email: "user@example.com",
      full_name: "Abebe Kebede"
    },
    onComplete: function(result) {
      if (result.result === "approved") {
        // User is verified — proceed in your app
        window.location.href = "/dashboard";
      } else {
        alert("Verification " + result.result);
      }
    },
    onError: function(err) {
      console.error("KYC error:", err.detail);
    }
  });
</script>
```

### What the SDK Does

1. Creates the applicant and starts a verification session
2. Calls `required-data` to learn what each step needs
3. Renders dynamic forms from the tier's `attribute_schema` (text, date, number, enum, boolean — all with labels and validation from your tier config)
4. Shows a document type selector (only the types your tier accepts) with drag-and-drop upload
5. Opens the device camera for selfie capture (with file upload fallback)
6. Displays a step progress bar
7. Shows the final result (approved / rejected / pending)

All inside an isolated Shadow DOM so your site's CSS doesn't interfere.

### Configuration

| Option | Type | Required | Description |
|--------|------|----------|-------------|
| `apiKey` | string | Yes | Your organization's API key |
| `containerId` | string | Yes | ID of the HTML element to render into |
| `workflowId` | string | Yes | UUID of a published workflow |
| `applicant` | object | No | `{ external_id, email, phone, full_name }` |
| `baseUrl` | string | No | API base URL (defaults to current origin) |
| `onComplete` | function | No | `(result) => {}` — called when verification finishes |
| `onError` | function | No | `(error) => {}` — called on any error |
| `onStepChange` | function | No | `(step) => {}` — called when step advances |

### Callback Payloads

```javascript
// onComplete
{ result: "approved", sessionId: "uuid", details: { ... } }

// onError
{ status: 400, detail: "Missing required attribute: full_name" }

// onStepChange
{ step: 2, tier: "Document + Biometric" }
```

### React Example

```jsx
import { useEffect, useRef } from 'react';

function KycWidget({ apiKey, workflowId, applicant, onDone }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!ref.current || !window.AfriTrust) return;
    window.AfriTrust.start({
      apiKey,
      containerId: ref.current.id,
      workflowId,
      applicant,
      onComplete: onDone,
    });
  }, [apiKey, workflowId]);

  return <div id="afritrust-kyc" ref={ref} />;
}
```

### Try It Live

Open http://localhost:8000/verify — paste your API key and workflow ID to see the SDK in action.

---

## Attribute Schema Reference

Each tier profile defines a dynamic `attribute_schema`. These are the data types you can use when creating tiers:

| Type | Rendered as | Validation options |
|------|------------|-------------------|
| `string` | Text input | `min_length`, `max_length`, `pattern` (regex) |
| `number` | Number input | `min`, `max` |
| `date` | Date picker | Format must be `YYYY-MM-DD` |
| `boolean` | Checkbox | — |
| `enum` | Dropdown | `options` array required |
| `file` | File upload | — |

**Example schema:**
```json
[
  { "key": "full_name", "label": "Full Name", "data_type": "string", "required": true,
    "validation": { "min_length": 2 } },
  { "key": "date_of_birth", "label": "Date of Birth", "data_type": "date", "required": true },
  { "key": "gender", "label": "Gender", "data_type": "enum", "required": false,
    "options": ["male", "female", "other"] },
  { "key": "annual_income", "label": "Annual Income", "data_type": "number", "required": false,
    "validation": { "min": 0 } }
]
```

The SDK renders these into the correct form inputs automatically. The API validates submitted values against these rules and returns descriptive `400` errors on mismatch.

---

## Available Check Types

| Check | What happens |
|-------|-------------|
| `email` | Auto-completed when `email_address` attribute is submitted |
| `phone` | Auto-completed when `phone_number` attribute is submitted |
| `selfie` | Liveness detection on uploaded selfie (OpenCV heuristics) |
| `government_id` | Document OCR via Tesseract + fraud signal analysis |
| `face_match` | Face comparison between selfie and document photo (DeepFace) |
| `liveness` | Image-quality liveness analysis |
| `address_proof` | Address document uploaded and processed |

---

## Project Structure

```
afri-trust-backend/
├── app/
│   ├── main.py                    # FastAPI app + route mounting
│   ├── core/                      # Config, security, exceptions
│   ├── db/                        # SQLAlchemy engine + cross-DB types
│   ├── models/                    # 10 database models
│   ├── schemas/                   # Pydantic request/response DTOs
│   ├── api/v1/                    # 11 route modules (64 endpoints)
│   ├── services/
│   │   ├── orchestrator.py        # Verification state machine
│   │   ├── document_processor.py  # Tesseract OCR + fraud signals
│   │   ├── biometric_service.py   # DeepFace + OpenCV biometrics
│   │   ├── consent_service.py     # Token-scoped data access
│   │   └── webhook_dispatcher.py  # HMAC-signed delivery
│   ├── storage/                   # File storage abstraction
│   └── sdk/
│       ├── afritrust.js           # Embeddable Web SDK
│       └── demo.html              # SDK demo page
├── postman/                       # Postman collection
├── requirements.txt
└── .env.example
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./afritrust.db` | Database connection |
| `JWT_SECRET_KEY` | — | JWT signing secret |
| `API_KEY_PEPPER` | — | API key hash salt |
| `STORAGE_BACKEND` | `local` | `local` or `s3` |
| `UPLOAD_DIR` | `uploads` | Local file upload path |

Full admin API reference is available at http://localhost:8000/docs when running.
