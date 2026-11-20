from dataclasses import dataclass

from lake.partitions.source_rows import encode_liters
from lake.reports.deltas import ReportDelta


@dataclass(frozen=True, slots=True)
class FeedEntry:
    position: int
    fact_id: int
    partition_id: str
    delta: ReportDelta


def init_feed(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS feed_entries (
            position INTEGER PRIMARY KEY,
            fact_id INTEGER NOT NULL UNIQUE REFERENCES fact_commits (fact_id),
            count_delta TEXT NOT NULL,
            liters_delta TEXT NOT NULL
        )
    ''')


def append_delta(db, fact_id, delta):
    if delta.is_zero():
        return
    db.execute('''
        INSERT INTO feed_entries (fact_id, count_delta, liters_delta) VALUES (?, ?, ?)
    ''', (fact_id, encode_liters(delta.count), encode_liters(delta.liters)))


def latest_feed_position(db):
    return db.execute('SELECT COALESCE(MAX(position), 0) FROM feed_entries').fetchone()[0]
