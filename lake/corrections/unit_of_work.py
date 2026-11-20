import sqlite3
from contextlib import contextmanager
from pathlib import Path


def configure_durable(db, schema):
    if schema not in ('main', 'volume'):
        raise ValueError('unsupported database schema')
    mode = db.execute(f'PRAGMA {schema}.journal_mode').fetchone()[0]
    if mode.lower() != 'delete':
        mode = db.execute(f'PRAGMA {schema}.journal_mode = DELETE').fetchone()[0]
        if mode.lower() != 'delete':
            raise sqlite3.OperationalError(f'cannot configure rollback journal for {schema}')
    db.execute(f'PRAGMA {schema}.synchronous = FULL')


def open_connection(path, *, read_only=False):
    mode = 'ro' if read_only else 'rwc'
    uri = Path(path).resolve().as_uri() + f'?mode={mode}'
    db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=5)
    try:
        db.execute('PRAGMA foreign_keys = ON')
        if not read_only:
            configure_durable(db, 'main')
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def read_transaction(db):
    db.execute('BEGIN')
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


@contextmanager
def write_transaction(db, operation=None, before_commit=None):
    db.execute('BEGIN IMMEDIATE')
    try:
        before_changes = db.total_changes
        yield
        if before_commit is not None and db.total_changes != before_changes:
            before_commit(operation)
        db.commit()
    except BaseException:
        db.rollback()
        raise
