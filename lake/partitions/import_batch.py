from lake.cold.checks import check_volume_binding
from lake.cold.coverage import advance_coverage
from lake.corrections.commits import confirm_fact
from lake.corrections.current_rows import find_current_row, reserve_row_identity
from lake.corrections.unit_of_work import write_transaction
from lake.feed.append import append_delta
from lake.partitions.batch_identity import batch_fingerprint, matches_batch
from lake.partitions.catalog import lookup_partition
from lake.partitions.intake_receipts import IntakeReceipt, find_intake_receipt, store_intake_receipt
from lake.partitions.source_rows import insert_source_rows, normalize_source_rows, require_name
from lake.reports.deltas import batch_delta
from lake.reports.qualification import read_threshold
from lake.reports.rollup import apply_delta


class BatchConflict(ValueError):
    pass


class RowConflict(ValueError):
    pass


def load_batch(warehouse, partition_id, batch_id, rows):
    require_name(batch_id, 'batch_id')
    db = warehouse.db
    binding = lookup_partition(db, partition_id)
    rows = normalize_source_rows(rows)
    candidate = batch_fingerprint(partition_id, rows)
    with warehouse.volumes.attach_volume(db, binding.volume_ref):
        with write_transaction(db, 'load_batch', warehouse.before_commit):
            existing = find_intake_receipt(db, batch_id)
            if existing is not None and existing[0].partition_id != partition_id:
                raise BatchConflict(f'batch already bound: {batch_id}')
            check_volume_binding(db, partition_id, binding.volume_ref, attached=True)
            if existing is not None:
                receipt, fingerprint = existing
                if not matches_batch(db, batch_id, fingerprint, candidate, rows):
                    raise BatchConflict(f'batch content differs: {batch_id}')
                return receipt

            row_ids = set()
            for row in rows:
                if row.row_id in row_ids or find_current_row(db, partition_id, row.row_id) is not None:
                    raise RowConflict(f'occupied row: {partition_id}/{row.row_id}')
                row_ids.add(row.row_id)

            fact = confirm_fact(db, 'batch', batch_id, partition_id)
            receipt = IntakeReceipt(batch_id, partition_id, f'intake-{fact.fact_id}', fact.fact_id)
            store_intake_receipt(db, receipt, candidate)
            insert_source_rows(db, batch_id, rows)
            for row in rows:
                reserve_row_identity(db, partition_id, row, fact.fact_id)
            advance_coverage(db, fact.fact_id)
            delta = batch_delta(rows, read_threshold(db))
            apply_delta(db, partition_id, delta)
            append_delta(db, fact.fact_id, delta)
            return receipt
