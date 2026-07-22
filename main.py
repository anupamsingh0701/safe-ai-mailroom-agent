import json
import os
import hmac
import hashlib
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse

from schemas import (
    get_canonical_hash,
    get_canonical_dossier_hash,
    compute_call_id,
    compute_proposal_digest,
    ALLOWED_ACTIONS
)
from database import (
    init_db,
    get_cached_decision,
    set_cached_decision,
    get_evaluation,
    save_propose_evaluation,
    save_commit_evaluation,
    save_proposals,
    get_proposals_for_eval
)
from ai_engine import batch_classify_dossiers

app = FastAPI(title="Safe AI Mailroom Agent", version="1.0.0")


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/")
@app.get("/{path:path}")
def health_check(path: str = ""):
    return {"status": "ok", "service": "Safe AI Mailroom Agent"}


@app.post("/")
@app.post("/{path:path}")
async def mailroom_endpoint(request: Request, path: str = ""):
    # Enforce maximum body size of 512 KiB (524,288 bytes)
    body_bytes = await request.body()
    if len(body_bytes) > 524288:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Payload exceeds maximum limit of 512 KiB"
        )

    try:
        data = json.loads(body_bytes.decode("utf-8"))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON body"
        )

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body must be a JSON object"
        )

    operation = data.get("operation")
    if not operation or operation not in {"propose", "commit"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or missing operation. Must be 'propose' or 'commit'."
        )

    if operation == "propose":
        return await handle_propose(data, body_bytes)
    elif operation == "commit":
        return await handle_commit(data, body_bytes)


async def handle_propose(data: Dict[str, Any], raw_body: bytes) -> JSONResponse:
    evaluation_id = data.get("evaluationId")
    if not evaluation_id or not isinstance(evaluation_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid evaluationId"
        )

    dossiers = data.get("dossiers")
    if dossiers is None or not isinstance(dossiers, list) or len(dossiers) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid dossiers array"
        )

    # Validate dossier format & check for duplicate dossier IDs
    dossier_ids = set()
    incoming_dossier_ids = []
    for d in dossiers:
        if not isinstance(d, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each dossier must be an object"
            )
        did = d.get("dossierId") or d.get("id")
        if not did or not isinstance(did, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Dossier missing valid dossierId"
            )
        if did in dossier_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate dossierId '{did}' in propose request"
            )
        dossier_ids.add(did)
        incoming_dossier_ids.append(did)

    propose_hash = get_canonical_hash(data)

    # Replay & Conflict check
    existing_eval = get_evaluation(evaluation_id)
    if existing_eval:
        if existing_eval["propose_hash"] == propose_hash:
            # Exact propose replay -> return exact cached response
            cached_resp = json.loads(existing_eval["propose_response_json"])
            return JSONResponse(content=cached_resp, status_code=200)
        else:
            # Changed content for same evaluationId -> HTTP 409 Conflict
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evaluation ID already exists with different propose content"
            )

    proposals = []
    uncached_dossiers = []
    uncached_indices = []

    for idx, d in enumerate(dossiers):
        did = d.get("dossierId") or d.get("id")
        input_digest = d.get("inputDigest") or get_canonical_dossier_hash(d)
        call_id = compute_call_id(did, input_digest)

        content_hash = get_canonical_dossier_hash(d)
        cached_dec = get_cached_decision(content_hash)

        if cached_dec:
            action = cached_dec["action"]
            target = cached_dec["target"]
            payload = cached_dec["payload"]
            evidence = cached_dec["evidence"]
            digest = compute_proposal_digest(did, call_id, input_digest, action, target, payload, evidence)
            proposals.append({
                "dossierId": did,
                "callId": call_id,
                "inputDigest": input_digest,
                "action": action,
                "target": target,
                "payload": payload,
                "evidence": evidence,
                "proposalDigest": digest
            })
        else:
            uncached_indices.append((idx, did, input_digest, call_id, content_hash))
            uncached_dossiers.append(d)

    # Classify uncached dossiers
    if uncached_dossiers:
        ai_results = batch_classify_dossiers(uncached_dossiers)
        for (idx, did, input_digest, call_id, content_hash), res in zip(uncached_indices, ai_results):
            action = res["action"]
            target = res["target"]
            payload = res["payload"]
            evidence = res["evidence"]

            # Cache by canonical content hash
            set_cached_decision(content_hash, action, target, payload, evidence)

            digest = compute_proposal_digest(did, call_id, input_digest, action, target, payload, evidence)
            proposals.append({
                "dossierId": did,
                "callId": call_id,
                "inputDigest": input_digest,
                "action": action,
                "target": target,
                "payload": payload,
                "evidence": evidence,
                "proposalDigest": digest
            })

    # Preserve original dossiers order
    proposal_map = {p["dossierId"]: p for p in proposals}
    ordered_proposals = [proposal_map[d.get("dossierId") or d.get("id")] for d in dossiers]

    response_body = {
        "status": "awaiting_receipts",
        "proposals": ordered_proposals
    }

    receipt_key = data.get("receiptKey") or data.get("verificationKey") or data.get("receipt_key")
    save_propose_evaluation(evaluation_id, propose_hash, response_body, receipt_key)
    save_proposals(evaluation_id, ordered_proposals)

    return JSONResponse(content=response_body, status_code=200)


async def handle_commit(data: Dict[str, Any], raw_body: bytes) -> JSONResponse:
    receipts = data.get("receipts")
    if receipts is None or not isinstance(receipts, list) or len(receipts) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid receipts array"
        )

    evaluation_id = data.get("evaluationId")
    if not evaluation_id and len(receipts) > 0:
        evaluation_id = receipts[0].get("evaluationId")

    if not evaluation_id or not isinstance(evaluation_id, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing evaluationId in commit request"
        )

    existing_eval = get_evaluation(evaluation_id)
    if not existing_eval:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown evaluationId '{evaluation_id}'"
        )

    commit_hash = get_canonical_hash(data)

    # Replay & Conflict check for commit
    if existing_eval.get("commit_response_json"):
        stored_commit_hash = existing_eval.get("commit_hash")
        cached_resp = json.loads(existing_eval["commit_response_json"])
        if stored_commit_hash == commit_hash:
            return JSONResponse(content=cached_resp, status_code=200)
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Evaluation already committed with different receipts"
            )

    stored_proposals = get_proposals_for_eval(evaluation_id)
    if not stored_proposals:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No stored proposals found for evaluation '{evaluation_id}'"
        )

    by_call_id = {p["callId"]: p for p in stored_proposals}
    by_dossier_id = {p["dossierId"]: p for p in stored_proposals}

    receipt_key = existing_eval.get("receipt_key")

    outcomes = []
    for r in receipts:
        if not isinstance(r, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Each receipt must be an object"
            )

        call_id = r.get("callId")
        dossier_id = r.get("dossierId")
        matched_proposal = None

        if call_id and call_id in by_call_id:
            matched_proposal = by_call_id[call_id]
        elif dossier_id and dossier_id in by_dossier_id:
            matched_proposal = by_dossier_id[dossier_id]

        if not matched_proposal:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Receipt contains unknown callId '{call_id}' or dossierId '{dossier_id}'"
            )

        # Strict validation of receipt fields
        if call_id and call_id != matched_proposal["callId"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Receipt callId '{call_id}' mismatch"
            )

        if dossier_id and dossier_id != matched_proposal["dossierId"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Receipt dossierId '{dossier_id}' mismatch"
            )

        rcpt_input_digest = r.get("inputDigest")
        if rcpt_input_digest and rcpt_input_digest != matched_proposal["inputDigest"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Receipt inputDigest '{rcpt_input_digest}' mismatch"
            )

        rcpt_action = r.get("action")
        if rcpt_action and rcpt_action != matched_proposal["action"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Receipt action '{rcpt_action}' mismatch"
            )

        rcpt_digest = r.get("proposalDigest") or r.get("digest")
        if rcpt_digest and rcpt_digest != matched_proposal["proposalDigest"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Receipt proposal digest mismatch for callId '{matched_proposal['callId']}'"
            )

        rcpt_sig = r.get("signature") or r.get("mac") or r.get("receiptSignature")
        if receipt_key and rcpt_sig:
            sig_payload = f"{matched_proposal['callId']}:{matched_proposal['action']}:{matched_proposal['proposalDigest']}"
            expected_sig = hmac.new(receipt_key.encode('utf-8'), sig_payload.encode('utf-8'), hashlib.sha256).hexdigest()
            if rcpt_sig != expected_sig:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Receipt signature verification failed"
                )

        raw_status = r.get("status")
        if not raw_status or not isinstance(raw_status, str):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Receipt missing status string"
            )

        rcpt_status = raw_status.lower()
        if rcpt_status in {"approved", "executed", "ok", "success", "completed"}:
            outcome_status = "executed"
        elif rcpt_status in {"rejected", "failed", "denied"}:
            outcome_status = "rejected"
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid receipt status '{rcpt_status}'"
            )

        outcomes.append({
            "dossierId": matched_proposal["dossierId"],
            "callId": matched_proposal["callId"],
            "inputDigest": matched_proposal["inputDigest"],
            "action": matched_proposal["action"],
            "status": outcome_status,
            "receiptId": r.get("receiptId") or r.get("receipt") or "rcpt_valid"
        })

    response_body = {
        "status": "completed",
        "outcomes": outcomes
    }

    save_commit_evaluation(evaluation_id, commit_hash, response_body)

    return JSONResponse(content=response_body, status_code=200)
