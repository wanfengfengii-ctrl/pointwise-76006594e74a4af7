from lake.corrections.commits import current_fact_cut
from lake.corrections.unit_of_work import write_transaction
from lake.partitions.source_rows import require_name
from lake.reports.history import FrozenReport, find_frozen_report, insert_frozen_report
from lake.reports.rollup import read_totals


def freeze(warehouse, report_id):
    require_name(report_id, 'report_id')
    db = warehouse.db
    with write_transaction(db, 'freeze', warehouse.before_commit):
        previous = find_frozen_report(db, report_id)
        if previous is not None:
            return previous
        cut = current_fact_cut(db)
        totals = read_totals(db)
        report = FrozenReport(report_id, cut, totals.threshold, totals.count, totals.liters)
        insert_frozen_report(db, report)
        return report
