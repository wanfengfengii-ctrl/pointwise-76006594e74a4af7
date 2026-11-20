import hashlib
import json
from dataclasses import dataclass

from lake.partitions.source_rows import encode_liters


@dataclass(frozen=True, slots=True)
class MoveReceipt:
    move_id: str
    from_partition: str
    from_row: str
    to_partition: str
    to_row: str
    fact_id: int
    origin: tuple


def init_move_receipts(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS move_receipts (
            move_id TEXT PRIMARY KEY NOT NULL,
            from_partition TEXT NOT NULL,
            from_row TEXT NOT NULL,
            to_partition TEXT NOT NULL,
            to_row TEXT NOT NULL,
            fact_id INTEGER NOT NULL UNIQUE REFERENCES fact_commits (fact_id),
            origin_partition TEXT NOT NULL,
            origin_batch TEXT NOT NULL,
            origin_ordinal INTEGER NOT NULL,
            origin_row TEXT NOT NULL,
            fingerprint TEXT NOT NULL
        ) WITHOUT ROWID
    ''')


def find_move_receipt(db, move_id):
    record = db.execute('''
        SELECT move_id, from_partition, from_row, to_partition, to_row, fact_id,
               origin_partition, origin_batch, origin_ordinal, origin_row, fingerprint
        FROM move_receipts WHERE move_id = ?
    ''', (move_id,)).fetchone()
    if record is None:
        return None
    return MoveReceipt(*record[:6], tuple(record[6:10])), record[10]


def store_move_receipt(db, receipt, fingerprint):
    db.execute('''
        INSERT INTO move_receipts
            (move_id, from_partition, from_row, to_partition, to_row, fact_id,
             origin_partition, origin_batch, origin_ordinal, origin_row, fingerprint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        receipt.move_id, receipt.from_partition, receipt.from_row,
        receipt.to_partition, receipt.to_row, receipt.fact_id,
        *receipt.origin, fingerprint,
    ))


def move_fingerprint(from_partition, from_row, to_partition, to_row, expected_liters):
    payload = [from_partition, from_row, to_partition, to_row, encode_liters(expected_liters)]
    encoded = json.dumps(payload, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()
