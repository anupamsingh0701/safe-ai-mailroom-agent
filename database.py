import json
import sqlite3
import os
from typing import Optional, Dict, Any, List

DB_PATH = os.environ.get("DATABASE_PATH", "mailroom.db")


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS canonical_cache (
        content_hash TEXT PRIMARY KEY,
        action TEXT NOT NULL,
        target_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS evaluations (
        evaluation_id TEXT PRIMARY KEY,
        propose_hash TEXT NOT NULL,
        propose_response_json TEXT NOT NULL,
        commit_hash TEXT,
        commit_response_json TEXT,
        receipt_key TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS proposals (
        evaluation_id TEXT NOT NULL,
        dossier_id TEXT NOT NULL,
        call_id TEXT NOT NULL,
        input_digest TEXT NOT NULL,
        action TEXT NOT NULL,
        target_json TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        proposal_digest TEXT NOT NULL,
        PRIMARY KEY (evaluation_id, dossier_id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS receipts (
        evaluation_id TEXT NOT NULL,
        dossier_id TEXT,
        call_id TEXT NOT NULL,
        action TEXT NOT NULL,
        proposal_digest TEXT,
        status TEXT,
        receipt_id TEXT,
        PRIMARY KEY (evaluation_id, call_id)
    )
    """)

    conn.commit()
    conn.close()


# Canonical cache operations

def get_cached_decision(content_hash: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT action, target_json, payload_json, evidence_json FROM canonical_cache WHERE content_hash = ?", (content_hash,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "action": row["action"],
            "target": json.loads(row["target_json"]),
            "payload": json.loads(row["payload_json"]),
            "evidence": json.loads(row["evidence_json"])
        }
    return None


def set_cached_decision(content_hash: str, action: str, target: dict, payload: dict, evidence: list):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO canonical_cache (content_hash, action, target_json, payload_json, evidence_json)
    VALUES (?, ?, ?, ?, ?)
    """, (content_hash, action, json.dumps(target), json.dumps(payload), json.dumps(evidence)))
    conn.commit()
    conn.close()


# Evaluation operations

def get_evaluation(evaluation_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM evaluations WHERE evaluation_id = ?", (evaluation_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def save_propose_evaluation(evaluation_id: str, propose_hash: str, propose_response: dict, receipt_key: Optional[str] = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO evaluations (evaluation_id, propose_hash, propose_response_json, receipt_key)
    VALUES (?, ?, ?, ?)
    """, (evaluation_id, propose_hash, json.dumps(propose_response), receipt_key))
    conn.commit()
    conn.close()


def save_commit_evaluation(evaluation_id: str, commit_hash: str, commit_response: dict):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE evaluations
    SET commit_hash = ?, commit_response_json = ?
    WHERE evaluation_id = ?
    """, (commit_hash, json.dumps(commit_response), evaluation_id))
    conn.commit()
    conn.close()


# Proposal persistence

def save_proposals(evaluation_id: str, proposals: List[dict]):
    conn = get_db_connection()
    cursor = conn.cursor()
    for p in proposals:
        cursor.execute("""
        INSERT OR REPLACE INTO proposals (evaluation_id, dossier_id, call_id, input_digest, action, target_json, payload_json, evidence_json, proposal_digest)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            evaluation_id,
            p["dossierId"],
            p["callId"],
            p["inputDigest"],
            p["action"],
            json.dumps(p["target"]),
            json.dumps(p["payload"]),
            json.dumps(p["evidence"]),
            p["proposalDigest"]
        ))
    conn.commit()
    conn.close()


def get_proposals_for_eval(evaluation_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM proposals WHERE evaluation_id = ?", (evaluation_id,))
    rows = cursor.fetchall()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "dossierId": r["dossier_id"],
            "callId": r["call_id"],
            "inputDigest": r["input_digest"],
            "action": r["action"],
            "target": json.loads(r["target_json"]),
            "payload": json.loads(r["payload_json"]),
            "evidence": json.loads(r["evidence_json"]),
            "proposalDigest": r["proposal_digest"]
        })
    return result
