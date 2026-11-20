from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceRow:
    row_id: str
    liters: int


def require_name(value, field):
    if not isinstance(value, str) or not value or value.strip() != value or '\0' in value:
        raise ValueError(f'{field} must be a nonempty identifier without surrounding whitespace or NUL')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError(f'{field} must be UTF-8 encodable') from exc
    return value


def require_liters(value):
    if type(value) is not int or value < 0:
        raise ValueError('liters must be a nonnegative integer')
    return value


def encode_liters(value):
    if type(value) is not int:
        raise ValueError('only integers can be stored')
    return format(value, 'x')


def decode_liters(value):
    return int(value, 16)


def init_source_rows(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS volume.source_rows (
            row_id TEXT PRIMARY KEY NOT NULL,
            batch_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            liters TEXT NOT NULL,
            UNIQUE (batch_id, ordinal)
        ) WITHOUT ROWID
    ''')


def normalize_source_rows(rows):
    if isinstance(rows, (str, bytes, dict)):
        raise ValueError('rows must be an ordered iterable of source rows')
    try:
        entries = iter(rows)
    except TypeError as exc:
        raise ValueError('rows must be an ordered iterable of source rows') from exc
    normalized = []
    for entry in entries:
        if isinstance(entry, SourceRow):
            row_id, liters = entry.row_id, entry.liters
        elif isinstance(entry, (list, tuple)) and len(entry) == 2:
            row_id, liters = entry
        else:
            raise ValueError('each row must have a row_id and liters')
        normalized.append(SourceRow(require_name(row_id, 'row_id'), require_liters(liters)))
    return tuple(normalized)


def insert_source_rows(db, batch_id, rows):
    db.executemany(
        'INSERT INTO volume.source_rows (row_id, batch_id, ordinal, liters) VALUES (?, ?, ?, ?)',
        ((row.row_id, batch_id, position, encode_liters(row.liters)) for position, row in enumerate(rows)),
    )


def read_batch_source_rows(db, batch_id):
    records = db.execute(
        'SELECT row_id, liters FROM volume.source_rows WHERE batch_id = ? ORDER BY ordinal',
        (batch_id,),
    )
    return tuple(SourceRow(row_id, decode_liters(liters)) for row_id, liters in records)
