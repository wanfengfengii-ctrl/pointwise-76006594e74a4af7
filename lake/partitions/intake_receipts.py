from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntakeReceipt:
    batch_id: str
    partition_id: str
    intake_id: str
    fact_id: int


def init_intake_receipts(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS intake_receipts (
            batch_id TEXT PRIMARY KEY NOT NULL,
            partition_id TEXT NOT NULL REFERENCES partitions (partition_id),
            intake_id TEXT NOT NULL UNIQUE,
            fact_id INTEGER NOT NULL UNIQUE REFERENCES fact_commits (fact_id),
            fingerprint TEXT NOT NULL
        ) WITHOUT ROWID
    ''')


def find_intake_receipt(db, batch_id):
    record = db.execute('''
        SELECT batch_id, partition_id, intake_id, fact_id, fingerprint
        FROM intake_receipts WHERE batch_id = ?
    ''', (batch_id,)).fetchone()
    if record is None:
        return None
    return IntakeReceipt(*record[:4]), record[4]


def store_intake_receipt(db, receipt, fingerprint):
    db.execute('''
        INSERT INTO intake_receipts (batch_id, partition_id, intake_id, fact_id, fingerprint)
        VALUES (?, ?, ?, ?, ?)
    ''', (receipt.batch_id, receipt.partition_id, receipt.intake_id, receipt.fact_id, fingerprint))
