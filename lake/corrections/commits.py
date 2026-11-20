from dataclasses import dataclass


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
            kind TEXT NOT NULL CHECK (kind IN ('batch', 'correction')),
            operation_id TEXT NOT NULL,
            partition_id TEXT NOT NULL REFERENCES partitions (partition_id),
            UNIQUE (kind, operation_id)
        )
    ''')


def confirm_fact(db, kind, operation_id, partition_id):
    result = db.execute('''
        INSERT INTO fact_commits (kind, operation_id, partition_id) VALUES (?, ?, ?)
    ''', (kind, operation_id, partition_id))
    return FactCommit(result.lastrowid, kind, operation_id, partition_id)


def current_fact_cut(db):
    return db.execute('SELECT COALESCE(MAX(fact_id), 0) FROM fact_commits').fetchone()[0]
