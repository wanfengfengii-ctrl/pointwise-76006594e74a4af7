START_COVERAGE = 0


def init_coverage(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS volume.coverage (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            fact_id INTEGER NOT NULL CHECK (fact_id >= 0)
        )
    ''')
    db.execute('INSERT OR IGNORE INTO volume.coverage VALUES (1, ?)', (START_COVERAGE,))


def read_coverage(db):
    record = db.execute('SELECT fact_id FROM main.coverage WHERE singleton = 1').fetchone()
    if record is None or type(record[0]) is not int or record[0] < START_COVERAGE:
        raise ValueError('invalid volume coverage')
    return record[0]


def advance_coverage(db, fact_id):
    result = db.execute('''
        UPDATE volume.coverage SET fact_id = ? WHERE singleton = 1 AND fact_id < ?
    ''', (fact_id, fact_id))
    if result.rowcount != 1:
        raise RuntimeError('volume coverage must advance from an existing earlier point')
