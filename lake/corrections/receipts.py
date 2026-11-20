import hashlib
import json
from dataclasses import dataclass

from lake.partitions.source_rows import encode_liters


@dataclass(frozen=True, slots=True)
class CorrectionReceipt:
    request_id: str
    partition_id: str
    row_id: str
    fact_id: int
    deleted: bool


def init_correction_receipts(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS correction_receipts (
            request_id TEXT PRIMARY KEY NOT NULL,
            partition_id TEXT NOT NULL,
            row_id TEXT NOT NULL,
            fact_id INTEGER NOT NULL UNIQUE REFERENCES fact_commits (fact_id),
            deleted INTEGER NOT NULL CHECK (deleted IN (0, 1)),
            fingerprint TEXT NOT NULL,
            before_digest TEXT NOT NULL,
            FOREIGN KEY (partition_id, row_id) REFERENCES current_rows (partition_id, row_id)
        ) WITHOUT ROWID
    ''')


def find_correction_receipt(db, request_id):
    record = db.execute('''
        SELECT request_id, partition_id, row_id, fact_id, deleted, fingerprint
        FROM correction_receipts WHERE request_id = ?
    ''', (request_id,)).fetchone()
    if record is None:
        return None
    return CorrectionReceipt(*record[:4], bool(record[4])), record[5]


def store_correction_receipt(db, receipt, fingerprint, before_digest):
    db.execute('''
        INSERT INTO correction_receipts
            (request_id, partition_id, row_id, fact_id, deleted, fingerprint, before_digest)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        receipt.request_id, receipt.partition_id, receipt.row_id, receipt.fact_id,
        int(receipt.deleted), fingerprint, before_digest,
    ))


def correction_fingerprint(partition_id, row_id, expected_liters, replacement_liters):
    replacement = None if replacement_liters is None else encode_liters(replacement_liters)
    payload = [partition_id, row_id, encode_liters(expected_liters), replacement]
    encoded = json.dumps(payload, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()
