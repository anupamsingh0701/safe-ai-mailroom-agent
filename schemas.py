import json
import hashlib
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


def get_canonical_json(obj: Any) -> str:
    """Returns RFC 8785 style canonical JSON string (sorted keys, compact format)."""
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def get_canonical_hash(obj: Any) -> str:
    """Returns SHA-256 hex digest of canonical JSON representation."""
    canonical_str = get_canonical_json(obj)
    return hashlib.sha256(canonical_str.encode('utf-8')).hexdigest()


def get_canonical_dossier_hash(dossier: Dict[str, Any]) -> str:
    """Returns SHA-256 hex digest of canonical dossier content, excluding volatile dossier ID fields."""
    if isinstance(dossier, dict):
        content = {k: v for k, v in dossier.items() if k not in {"dossierId", "id"}}
    else:
        content = dossier
    return get_canonical_hash(content)


def compute_call_id(dossier_id: str, input_digest: str) -> str:
    """Computes a stable, unique callId based on dossierId and inputDigest."""
    raw = f"{dossier_id}:{input_digest}"
    h = hashlib.sha256(raw.encode('utf-8')).hexdigest()
    return f"call_{h[:16]}"


def compute_proposal_digest(dossier_id: str, call_id: str, input_digest: str, action: str, target: dict, payload: dict, evidence: list) -> str:
    """Computes SHA-256 digest of canonical proposal structure."""
    data = {
        "action": action,
        "callId": call_id,
        "dossierId": dossier_id,
        "evidence": evidence,
        "inputDigest": input_digest,
        "payload": payload,
        "target": target
    }
    return get_canonical_hash(data)


ALLOWED_ACTIONS = {
    "create_draft",
    "update_internal_record",
    "send_approved_notice",
    "request_confirmation",
    "quarantine_item",
    "no_action"
}


class ProposalItem(BaseModel):
    dossierId: str
    callId: str
    inputDigest: str
    action: str
    target: Dict[str, Any] = Field(default_factory=dict)
    payload: Dict[str, Any] = Field(default_factory=dict)
    evidence: List[str] = Field(default_factory=list)
    proposalDigest: str


class ReceiptItem(BaseModel):
    evaluationId: Optional[str] = None
    dossierId: Optional[str] = None
    callId: Optional[str] = None
    action: Optional[str] = None
    inputDigest: Optional[str] = None
    proposalDigest: Optional[str] = None
    digest: Optional[str] = None
    status: Optional[str] = "approved"
    signature: Optional[str] = None
    receiptId: Optional[str] = None

    def get_digest(self) -> Optional[str]:
        return self.proposalDigest or self.digest


class OutcomeItem(BaseModel):
    dossierId: str
    callId: str
    inputDigest: str
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
