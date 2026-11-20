import hashlib
from dataclasses import dataclass

from lake.partitions.source_rows import encode_liters


@dataclass(frozen=True, slots=True)
class CurrentRow:
    partition_id: str
    row_id: str
    digest: str | None
    fact_id: int

    @property
    def present(self):
        return self.digest is not None


def image_digest(liters):
    return hashlib.sha256(encode_liters(liters).encode('ascii')).hexdigest()


def init_current_rows(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS current_rows (
            partition_id TEXT NOT NULL REFERENCES partitions (partition_id),
            row_id TEXT NOT NULL,
            digest TEXT,
            fact_id INTEGER NOT NULL REFERENCES fact_commits (fact_id),
            PRIMARY KEY (partition_id, row_id)
        ) WITHOUT ROWID
    ''')


def find_current_row(db, partition_id, row_id):
    record = db.execute('''
        SELECT partition_id, row_id, digest, fact_id FROM current_rows
        WHERE partition_id = ? AND row_id = ?
    ''', (partition_id, row_id)).fetchone()
    return CurrentRow(*record) if record is not None else None


def reserve_row_identity(db, partition_id, row, fact_id):
    db.execute('''
        INSERT INTO current_rows (partition_id, row_id, digest, fact_id) VALUES (?, ?, ?, ?)
    ''', (partition_id, row.row_id, image_digest(row.liters), fact_id))


def update_current_row(db, current, replacement_liters, fact_id):
    digest = image_digest(replacement_liters) if replacement_liters is not None else None
    result = db.execute('''
        UPDATE current_rows SET digest = ?, fact_id = ?
        WHERE partition_id = ? AND row_id = ? AND fact_id = ?
    ''', (digest, fact_id, current.partition_id, current.row_id, current.fact_id))
    if result.rowcount != 1:
        raise RuntimeError('current row changed inside its admission transaction')


def matches_before_image(current, expected_liters):
    return current.present and current.digest == image_digest(expected_liters)
