from dataclasses import dataclass

from lake.corrections.unit_of_work import write_transaction

FACT_KINDS = ('batch', 'correction', 'move')


@dataclass(frozen=True, slots=True)
class FactCommit:
    fact_id: int
    kind: str
    operation_id: str
    partition_id: str


def init_commit_log(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS fact_commits (
            fact_id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL CHECK (kind IN ('batch', 'correction', 'move')),
            operation_id TEXT NOT NULL,
            partition_id TEXT NOT NULL REFERENCES partitions (partition_id),
            UNIQUE (kind, operation_id)
        )
    ''')


def migrate_commit_log(db):
    # V1 warehouses reject the 'move' fact kind. Rebuild their commit log once.
    record = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'fact_commits'"
    ).fetchone()
    if record is None or "'move'" in record[0]:
        return
    db.execute('PRAGMA foreign_keys = OFF')
    try:
        with write_transaction(db):
            db.execute('''
                CREATE TABLE fact_commits_with_moves (
                    fact_id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('batch', 'correction', 'move')),
                    operation_id TEXT NOT NULL,
                    partition_id TEXT NOT NULL REFERENCES partitions (partition_id),
                    UNIQUE (kind, operation_id)
                )
            ''')
            db.execute('''
                INSERT INTO fact_commits_with_moves (fact_id, kind, operation_id, partition_id)
                SELECT fact_id, kind, operation_id, partition_id FROM fact_commits
            ''')
            db.execute('DROP TABLE fact_commits')
            db.execute('ALTER TABLE fact_commits_with_moves RENAME TO fact_commits')
    finally:
        db.execute('PRAGMA foreign_keys = ON')


def confirm_fact(db, kind, operation_id, partition_id):
    result = db.execute('''
        INSERT INTO fact_commits (kind, operation_id, partition_id) VALUES (?, ?, ?)
    ''', (kind, operation_id, partition_id))
    return FactCommit(result.lastrowid, kind, operation_id, partition_id)


def current_fact_cut(db):
    return db.execute('SELECT COALESCE(MAX(fact_id), 0) FROM fact_commits').fetchone()[0]
