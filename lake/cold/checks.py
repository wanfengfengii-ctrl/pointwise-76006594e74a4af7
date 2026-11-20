from lake.partitions.source_rows import require_liters, require_name


def check_volume_binding(db, partition_id, volume_ref, *, attached=False):
    schema = 'volume' if attached else 'main'
    identity = db.execute(
        f'SELECT partition_id, volume_ref FROM {schema}.volume_binding WHERE singleton = 1'
    ).fetchone()
    if identity != (partition_id, volume_ref):
        raise ValueError(f'volume binding mismatch: {partition_id}/{volume_ref}')


def check_scanned_rows(rows):
    previous = None
    for row in rows:
        require_name(row.row_id, 'row_id')
        require_liters(row.liters)
        if previous is not None and row.row_id <= previous:
            raise ValueError('scanned rows must have distinct, ordered row identifiers')
        previous = row.row_id
