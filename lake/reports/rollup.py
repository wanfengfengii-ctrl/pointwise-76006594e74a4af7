from dataclasses import dataclass

from lake.corrections.unit_of_work import read_transaction
from lake.partitions.catalog import lookup_partition
from lake.partitions.source_rows import decode_liters, encode_liters
from lake.reports.qualification import read_threshold


@dataclass(frozen=True, slots=True)
class LiveTotals:
    threshold: int
    count: int
    liters: int


def init_rollups(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS partition_rollups (
            partition_id TEXT PRIMARY KEY NOT NULL REFERENCES partitions (partition_id),
            qualified_count TEXT NOT NULL,
            liters TEXT NOT NULL
        ) WITHOUT ROWID
    ''')


def _partition_totals(db, partition_id):
    record = db.execute('''
        SELECT qualified_count, liters FROM partition_rollups WHERE partition_id = ?
    ''', (partition_id,)).fetchone()
    if record is None:
        return 0, 0
    return decode_liters(record[0]), decode_liters(record[1])


def apply_delta(db, partition_id, delta):
    if delta.is_zero():
        return
    count, liters = _partition_totals(db, partition_id)
    count += delta.count
    liters += delta.liters
    if count < 0 or liters < 0 or (count == 0 and liters != 0):
        raise RuntimeError('invalid partition totals after applying delta')
    db.execute('''
        INSERT INTO partition_rollups (partition_id, qualified_count, liters) VALUES (?, ?, ?)
        ON CONFLICT (partition_id) DO UPDATE SET
            qualified_count = excluded.qualified_count, liters = excluded.liters
    ''', (partition_id, encode_liters(count), encode_liters(liters)))


def read_totals(db, partition_id=None):
    threshold = read_threshold(db)
    if partition_id is not None:
        lookup_partition(db, partition_id)
        count, liters = _partition_totals(db, partition_id)
    else:
        count = 0
        liters = 0
        for part_count, part_liters in db.execute('SELECT qualified_count, liters FROM partition_rollups'):
            count += decode_liters(part_count)
            liters += decode_liters(part_liters)
    return LiveTotals(threshold, count, liters)


def read_live(warehouse, partition_id=None):
    with read_transaction(warehouse.db):
        return read_totals(warehouse.db, partition_id)
