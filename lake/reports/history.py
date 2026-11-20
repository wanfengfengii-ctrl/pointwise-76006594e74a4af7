from dataclasses import dataclass

from lake.corrections.unit_of_work import read_transaction
from lake.partitions.source_rows import decode_liters, encode_liters, require_name


@dataclass(frozen=True, slots=True)
class FrozenReport:
    report_id: str
    fact_cut: int
    threshold: int
    count: int
    liters: int


def init_frozen_history(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS frozen_reports (
            report_id TEXT PRIMARY KEY NOT NULL,
            fact_cut INTEGER NOT NULL CHECK (fact_cut >= 0),
            threshold TEXT NOT NULL,
            qualified_count TEXT NOT NULL,
            liters TEXT NOT NULL
        ) WITHOUT ROWID
    ''')


def find_frozen_report(db, report_id):
    record = db.execute('''
        SELECT report_id, fact_cut, threshold, qualified_count, liters
        FROM frozen_reports WHERE report_id = ?
    ''', (report_id,)).fetchone()
    if record is None:
        return None
    key, cut, threshold, count, liters = record
    return FrozenReport(key, cut, decode_liters(threshold), decode_liters(count), decode_liters(liters))


def insert_frozen_report(db, report):
    db.execute('''
        INSERT INTO frozen_reports (report_id, fact_cut, threshold, qualified_count, liters)
        VALUES (?, ?, ?, ?, ?)
    ''', (
        report.report_id, report.fact_cut, encode_liters(report.threshold),
        encode_liters(report.count), encode_liters(report.liters),
    ))


def read_frozen(warehouse, report_id):
    require_name(report_id, 'report_id')
    with read_transaction(warehouse.db):
        return find_frozen_report(warehouse.db, report_id)
