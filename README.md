# Safe AI Mailroom Agent

A high-performance, secure AI Mailroom Agent built with FastAPI and Google Gemini.
It processes mail dossiers, chooses exact safe actions, verifies evaluation receipts from graders, and ensures exact replay-safety and canonical dossier caching.

## Features
- **Deterministic Canonical Content Fingerprinting & Stable `callId`**: Dossiers with identical content produce identical `callId` and reuse cached decisions across evaluations with zero extra LLM calls.
- **Atomic Validation & Error Handling**:
  - `400 Bad Request` / `422` for malformed input, missing schemas, or duplicate `dossierId`s.
  - `409 Conflict` when an `evaluationId` is reused with modified content or modified receipts.
  - Body size limit strictly enforced (< 512 KiB).
- **Prompt Injection Defense & Quarantine**: Detects prompt injection attempts, canary extraction, or tool manipulation, isolating them safely with `quarantine_item`.
- **Receipt Verification**: Verifies `callId`, `action`, and `proposalDigest` before executing any approved action on commit.

## API Specification

### 1. Propose Endpoint (`POST /` or `POST /api/mailroom`)
```json
{
  "operation": "propose",
  "evaluationId": "eval_12345",
  "dossiers": [ ... ]
}
```
**Response (200 OK):**
```json
{
  "status": "awaiting_receipts",
  "proposals": [
    {
      "dossierId": "d1",
      "callId": "call_abc123",
      "action": "quarantine_item",
      "target": { "quarantine_queue": "security_audit" },
      "payload": { "reason": "Prompt injection attempt", "threat_type": "prompt_injection" },
      "evidence": [ "Detected prompt injection" ],
      "proposalDigest": "..."
    }
  ]
}
```

### 2. Commit Endpoint (`POST /` or `POST /api/mailroom`)
```json
{
  "operation": "commit",
  "evaluationId": "eval_12345",
  "receipts": [
    {
      "callId": "call_abc123",
      "action": "quarantine_item",
      "proposalDigest": "...",
      "status": "approved"
    }
  ]
}
```
**Response (200 OK):**
```json
{
  "status": "completed",
  "outcomes": [
    {
      "dossierId": "d1",
      "callId": "call_abc123",
      "action": "quarantine_item",
      "status": "executed",
      "receiptId": "rcpt_valid"
    }
  ]
}
```

## Running Locally
```bash
pip install -r requirements.txt
uvicorn main:app --port 8000
```
