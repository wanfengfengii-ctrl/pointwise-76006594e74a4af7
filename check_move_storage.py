"""Check the platform's SQLite boundary with three small database files."""
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.corrections.unit_of_work import write_transaction


class ProbeInterrupted(RuntimeError):
    pass


def interrupt(operation):
    if operation == 'storage_probe':
        raise ProbeInterrupted(operation)


def apply(paths, before_commit=None):
    with closing(sqlite3.connect(paths[0], isolation_level=None)) as db:
        db.execute('ATTACH DATABASE ? AS left_probe', (str(paths[1]),))
        db.execute('ATTACH DATABASE ? AS right_probe', (str(paths[2]),))
        schemas = ('main', 'left_probe', 'right_probe')
        for schema in schemas:
            mode, = db.execute(f'PRAGMA {schema}.journal_mode = DELETE').fetchone()
            if mode != 'delete':
                raise RuntimeError(f'rollback journal unavailable for {schema}: {mode}')
            db.execute(f'PRAGMA {schema}.synchronous = FULL')
        with write_transaction(db, 'storage_probe', before_commit):
            for schema in schemas:
                db.execute(f'UPDATE {schema}.probe SET marker = 1')


def read_markers(paths):
    result = []
    for path in paths:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            marker, = db.execute('SELECT marker FROM probe').fetchone()
            result.append(marker)
    return result


def main():
    with TemporaryDirectory(prefix='linti-storage-') as directory:
        paths = tuple(Path(directory).resolve() / name for name in ('main.db', 'left.db', 'right.db'))
        for path in paths:
            with closing(sqlite3.connect(path, isolation_level=None)) as db:
                db.execute('CREATE TABLE probe (marker INTEGER NOT NULL)')
                db.execute('INSERT INTO probe VALUES (0)')
        try:
            apply(paths, interrupt)
        except ProbeInterrupted:
            rolled_back = read_markers(paths)
        else:
            raise AssertionError('pre-commit fault hook did not run')
        if rolled_back != [0, 0, 0]:
            raise AssertionError(f'partial rollback: {rolled_back}')
        apply(paths)
        committed = read_markers(paths)
        if committed != [1, 1, 1]:
            raise AssertionError(f'partial commit: {committed}')
        print(f'three SQLite files after reopen: rollback={rolled_back}, commit={committed}')


if __name__ == '__main__':
    main()
