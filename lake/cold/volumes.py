import hashlib
from contextlib import closing, contextmanager
from pathlib import Path

from lake.cold.checks import check_volume_binding
from lake.cold.coverage import init_coverage
from lake.corrections.unit_of_work import configure_durable, open_connection, write_transaction
from lake.partitions.source_rows import SourceRow, decode_liters, encode_liters, init_source_rows, require_name


class VolumePort:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, volume_ref):
        require_name(volume_ref, 'volume_ref')
        token = hashlib.sha256(volume_ref.encode('utf-8')).hexdigest()
        return self.directory / f'{token}.sqlite3'

    @contextmanager
    def registration_lock(self):
        # Only competing registrations share this lock. Volume and main writes remain atomic.
        with closing(open_connection(self.directory / 'registry.sqlite3')) as lock_db:
            with write_transaction(lock_db):
                yield

    @contextmanager
    def attach_volume(self, db, volume_ref, *, create=False):
        mode = 'rwc' if create else 'rw'
        uri = self.path_for(volume_ref).resolve().as_uri() + f'?mode={mode}'
        db.execute('ATTACH DATABASE ? AS volume', (uri,))
        try:
            configure_durable(db, 'volume')
            yield
        finally:
            db.execute('DETACH DATABASE volume')

    def initialize_volume(self, db, partition_id, volume_ref):
        db.execute('''
            CREATE TABLE IF NOT EXISTS volume.volume_binding (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                partition_id TEXT NOT NULL,
                volume_ref TEXT NOT NULL
            )
        ''')
        db.execute('''
            INSERT OR IGNORE INTO volume.volume_binding (singleton, partition_id, volume_ref)
            VALUES (1, ?, ?)
        ''', (partition_id, volume_ref))
        check_volume_binding(db, partition_id, volume_ref, attached=True)
        init_source_rows(db)
        init_coverage(db)
        db.execute('''
            CREATE TABLE IF NOT EXISTS volume.row_edits (
                row_id TEXT PRIMARY KEY NOT NULL REFERENCES source_rows (row_id),
                liters TEXT
            ) WITHOUT ROWID
        ''')

    def open_for_read(self, volume_ref):
        return open_connection(self.path_for(volume_ref), read_only=True)

    def read_current_value(self, db, row_id):
        record = db.execute('''
            SELECT CASE WHEN edit.row_id IS NULL THEN original.liters ELSE edit.liters END
            FROM volume.source_rows AS original
            LEFT JOIN volume.row_edits AS edit USING (row_id)
            WHERE original.row_id = ?
        ''', (row_id,)).fetchone()
        if record is None or record[0] is None:
            return None
        return decode_liters(record[0])

    def _store_edit(self, db, row_id, encoded_liters):
        db.execute('''
            INSERT INTO volume.row_edits (row_id, liters) VALUES (?, ?)
            ON CONFLICT (row_id) DO UPDATE SET liters = excluded.liters
        ''', (row_id, encoded_liters))

    def replace_current_value(self, db, row_id, replacement_liters):
        self._store_edit(db, row_id, encode_liters(replacement_liters))

    def delete_current_row(self, db, row_id):
        self._store_edit(db, row_id, None)

    def iter_visible_rows(self, db):
        records = db.execute('''
            SELECT original.row_id,
                   CASE WHEN edit.row_id IS NULL THEN original.liters ELSE edit.liters END
            FROM main.source_rows AS original
            LEFT JOIN main.row_edits AS edit USING (row_id)
            WHERE edit.row_id IS NULL OR edit.liters IS NOT NULL
            ORDER BY original.row_id
        ''')
        try:
            for row_id, encoded in records:
                yield SourceRow(row_id, decode_liters(encoded))
        finally:
            records.close()
