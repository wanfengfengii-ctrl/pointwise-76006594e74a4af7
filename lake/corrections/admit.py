from lake.cold.checks import check_volume_binding
from lake.cold.coverage import advance_coverage
from lake.corrections.commits import confirm_fact
from lake.corrections.current_rows import find_current_row, matches_before_image, update_current_row
from lake.corrections.receipts import (
    CorrectionReceipt, correction_fingerprint, find_correction_receipt, store_correction_receipt,
)
from lake.corrections.unit_of_work import write_transaction
from lake.feed.append import append_delta
from lake.partitions.catalog import lookup_partition
from lake.partitions.source_rows import require_liters, require_name
from lake.reports.deltas import correction_delta
from lake.reports.qualification import read_threshold
from lake.reports.rollup import apply_delta


class CorrectionConflict(ValueError):
    pass


class StaleBeforeImage(ValueError):
    pass


class MissingRow(LookupError):
    pass


def _replay(db, request_id, fingerprint):
    existing = find_correction_receipt(db, request_id)
    if existing is None:
        return None
    receipt, stored_fingerprint = existing
    if stored_fingerprint != fingerprint:
        raise CorrectionConflict(f'correction request differs: {request_id}')
    return receipt


def correct_row(warehouse, request_id, partition_id, row_id, expected_liters, replacement_liters):
    require_name(request_id, 'request_id')
    require_name(partition_id, 'partition_id')
    require_name(row_id, 'row_id')
    require_liters(expected_liters)
    if replacement_liters is not None:
        require_liters(replacement_liters)
    fingerprint = correction_fingerprint(partition_id, row_id, expected_liters, replacement_liters)
    db = warehouse.db
    previous = _replay(db, request_id, fingerprint)
    if previous is not None:
        return previous

    binding = lookup_partition(db, partition_id)
    with warehouse.volumes.attach_volume(db, binding.volume_ref):
        with write_transaction(db, 'correct_row', warehouse.before_commit):
            previous = _replay(db, request_id, fingerprint)
            if previous is not None:
                return previous
            current = find_current_row(db, partition_id, row_id)
            if current is None or not current.present:
                raise MissingRow(f'{partition_id}/{row_id}')
            if not matches_before_image(current, expected_liters):
                raise StaleBeforeImage(f'{partition_id}/{row_id}')
            check_volume_binding(db, partition_id, binding.volume_ref, attached=True)
            before = warehouse.volumes.read_current_value(db, row_id)
            if before != expected_liters:
                raise RuntimeError('current row digest and volume value disagree')

            fact = confirm_fact(db, 'correction', request_id, partition_id)
            deleted = replacement_liters is None
            if deleted:
                warehouse.volumes.delete_current_row(db, row_id)
            else:
                warehouse.volumes.replace_current_value(db, row_id, replacement_liters)
            update_current_row(db, current, replacement_liters, fact.fact_id)
            advance_coverage(db, fact.fact_id)
            delta = correction_delta(before, replacement_liters, read_threshold(db))
            apply_delta(db, partition_id, delta)
            append_delta(db, fact.fact_id, delta)
            receipt = CorrectionReceipt(request_id, partition_id, row_id, fact.fact_id, deleted)
            store_correction_receipt(db, receipt, fingerprint, current.digest)
            return receipt
