from lake.partitions.source_rows import decode_liters, encode_liters, require_liters


def init_threshold(db, threshold):
    if threshold is not None:
        require_liters(threshold)
    db.execute('''
        CREATE TABLE IF NOT EXISTS warehouse_threshold (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            liters TEXT NOT NULL
        )
    ''')
    existing = db.execute('SELECT liters FROM warehouse_threshold WHERE singleton = 1').fetchone()
    if existing is None:
        if threshold is None:
            raise ValueError('threshold is required when initializing a warehouse')
        db.execute('INSERT INTO warehouse_threshold VALUES (1, ?)', (encode_liters(threshold),))
    elif threshold is not None and decode_liters(existing[0]) != threshold:
        raise ValueError('threshold differs from the existing warehouse')


def read_threshold(db):
    record = db.execute('SELECT liters FROM warehouse_threshold WHERE singleton = 1').fetchone()
    if record is None:
        raise RuntimeError('warehouse threshold is missing')
    return decode_liters(record[0])


def contribution(liters, threshold):
    if liters is not None and liters >= threshold:
        return 1, liters
    return 0, 0
