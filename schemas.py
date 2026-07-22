import json
import hashlib
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, root_validator


def get_canonical_json(obj: Any) -> str:
    """Returns RFC 8785 style canonical JSON string (sorted keys, compact format)."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def get_canonical_hash(obj: Any) -> str:
    """Returns SHA-256 hex digest of canonical JSON representation."""
    canonical_str = get_canonical_json(obj)
    return hashlib.sha256(canonical_str.encode('utf-8')).hexdigest()


def get_canonical_dossier_hash(dossier: Dict[str, Any]) -> str:
    """Returns SHA-256 hex digest of canonical dossier content, excluding ID fields."""
    if isinstance(dossier, dict):
        content = {k: v for k, v in dossier.items() if k not in {"dossierId", "id"}}
    else:
        content = dossier
    return get_canonical_hash(content)


def compute_call_id(dossier_content: Any) -> str:
    """Computes a stable, deterministic callId based on canonical dossier content hash."""
    h = get_canonical_dossier_hash(dossier_content)
    return f"call_{h[:16]}"


def compute_proposal_digest(dossier_id: str, call_id: str, action: str, target: dict, payload: dict, evidence: list) -> str:
    """Computes SHA-256 digest of canonical proposal structure."""
    data = {
        "action": action,
        "callId": call_id,
        "dossierId": dossier_id,
        "evidence": evidence,
        "payload": payload,
        "target": target
    }
    return get_canonical_hash(data)


# Action Schemas

ALLOWED_ACTIONS = {
    "create_draft",
    "update_internal_record",
    "send_approved_notice",
    "request_confirmation",
    "quarantine_item",
    "no_action"
}


class TargetPayloadSchema:
    @staticmethod
    def validate_action_target_payload(action: str, target: dict, payload: dict) -> bool:
        if action not in ALLOWED_ACTIONS:
            return False
        if not isinstance(target, dict) or not isinstance(payload, dict):
            return False
        return True


class ProposalItem(BaseModel):
    dossierId: str
    callId: str
    action: str
    target: Dict[str, Any] = Field(default_factory=dict)
    payload: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[str] = Field(default_factory=list)
    proposalDigest: str


class ReceiptItem(BaseModel):
    evaluationId: Optional[str] = None
    dossierId: Optional[str] = None
    callId: str
    action: str
    proposalDigest: Optional[str] = None
    digest: Optional[str] = None
    status: Optional[str] = "approved"

    def get_digest(self) -> Optional[str]:
        return self.proposalDigest or self.digest


class OutcomeItem(BaseModel):
    dossierId: str
    callId: str
    action: str
    status: str
    receiptId: Optional[str] = None


class ProposeRequest(BaseModel):
    operation: str
    evaluationId: str
    dossiers: List[Dict[str, Any]]
    receiptKey: Optional[str] = None
    verificationKey: Optional[str] = None


class ProposeResponse(BaseModel):
    status: str = "awaiting_receipts"
    proposals: List[ProposalItem]


class CommitRequest(BaseModel):
    operation: str
    evaluationId: Optional[str] = None
    receipts: List[Dict[str, Any]]


class CommitResponse(BaseModel):
    status: str = "completed"
    outcomes: List[OutcomeItem]
