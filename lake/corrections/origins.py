from lake.corrections.current_rows import CurrentRow, find_current_row


def init_row_origins(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS row_origins (
            partition_id TEXT NOT NULL,
            row_id TEXT NOT NULL,
            origin_partition TEXT NOT NULL,
            origin_batch TEXT NOT NULL,
            origin_ordinal INTEGER NOT NULL CHECK (origin_ordinal >= 0),
            origin_row TEXT NOT NULL,
            PRIMARY KEY (partition_id, row_id)
        ) WITHOUT ROWID
    ''')


def store_row_origin(db, partition_id, row_id, origin):
    origin_partition, origin_batch, origin_ordinal, origin_row = origin
    db.execute('''
        INSERT INTO row_origins
            (partition_id, row_id, origin_partition, origin_batch, origin_ordinal, origin_row)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (partition_id, row_id, origin_partition, origin_batch, origin_ordinal, origin_row))


def find_row_origin(db, partition_id, row_id):
    record = db.execute('''
        SELECT origin_partition, origin_batch, origin_ordinal, origin_row
        FROM row_origins WHERE partition_id = ? AND row_id = ?
    ''', (partition_id, row_id)).fetchone()
    return tuple(record) if record is not None else None


def find_present_by_origin(db, origin):
    record = db.execute('''
        SELECT c.partition_id, c.row_id, c.digest, c.fact_id
        FROM row_origins AS o
        JOIN current_rows AS c ON c.partition_id = o.partition_id AND c.row_id = o.row_id
        WHERE o.origin_partition = ? AND o.origin_batch = ?
          AND o.origin_ordinal = ? AND o.origin_row = ? AND c.digest IS NOT NULL
    ''', origin).fetchone()
    return CurrentRow(*record) if record is not None else None


def find_present_row(db, partition_id, row_id):
    # An address stays reserved after its observation leaves. Follow the origin
    # ledger to the observation's unique live address, if it is still present.
    record = find_current_row(db, partition_id, row_id)
    if record is None or record.present:
        return record
    origin = find_row_origin(db, partition_id, row_id)
    if origin is None:
        return None
    return find_present_by_origin(db, origin)
