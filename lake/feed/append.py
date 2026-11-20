from dataclasses import dataclass

from lake.partitions.source_rows import encode_liters
from lake.reports.deltas import ReportDelta


@dataclass(frozen=True, slots=True)
class FeedEntry:
    position: int
    fact_id: int
    partition_id: str
    delta: ReportDelta


@dataclass(frozen=True, slots=True)
class MoveFeedEntry:
    position: int
    fact_id: int
    from_partition: str
    to_partition: str
    out_delta: ReportDelta
    in_delta: ReportDelta


def init_feed(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS feed_entries (
            position INTEGER PRIMARY KEY,
            fact_id INTEGER NOT NULL UNIQUE REFERENCES fact_commits (fact_id),
            count_delta TEXT NOT NULL,
            liters_delta TEXT NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS move_feed_parts (
            position INTEGER PRIMARY KEY REFERENCES feed_entries (position),
            to_partition TEXT NOT NULL,
            in_count TEXT NOT NULL,
            in_liters TEXT NOT NULL
        ) WITHOUT ROWID
    ''')


def append_delta(db, fact_id, delta):
    if delta.is_zero():
        return
    db.execute('''
        INSERT INTO feed_entries (fact_id, count_delta, liters_delta) VALUES (?, ?, ?)
    ''', (fact_id, encode_liters(delta.count), encode_liters(delta.liters)))


def append_move(db, fact_id, out_delta, to_partition, in_delta):
    # Every move occupies one feed position, even when both contributions are zero.
    result = db.execute('''
        INSERT INTO feed_entries (fact_id, count_delta, liters_delta) VALUES (?, ?, ?)
    ''', (fact_id, encode_liters(out_delta.count), encode_liters(out_delta.liters)))
    db.execute('''
        INSERT INTO move_feed_parts (position, to_partition, in_count, in_liters)
        VALUES (?, ?, ?, ?)
    ''', (
        result.lastrowid, to_partition,
        encode_liters(in_delta.count), encode_liters(in_delta.liters),
    ))


def latest_feed_position(db):
    return db.execute('SELECT COALESCE(MAX(position), 0) FROM feed_entries').fetchone()[0]
