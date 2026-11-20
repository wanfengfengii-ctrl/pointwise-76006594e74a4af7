from lake.cold.checks import check_volume_binding
from lake.cold.coverage import advance_coverage
from lake.corrections.admit import MissingRow, StaleBeforeImage
from lake.corrections.commits import confirm_fact
from lake.corrections.current_rows import (
    find_current_row, insert_current_row, matches_before_image, vacate_current_row,
)
from lake.corrections.origins import find_present_by_origin, find_row_origin, store_row_origin
from lake.corrections.unit_of_work import write_transaction
from lake.feed.append import append_move
from lake.moves.receipts import (
    MoveReceipt, find_move_receipt, move_fingerprint, store_move_receipt,
)
from lake.partitions.catalog import lookup_partition
from lake.partitions.import_batch import RowConflict
from lake.partitions.source_rows import (
    insert_moved_row, moved_row_batch, read_source_placement, require_liters, require_name,
)
from lake.reports.deltas import move_deltas
from lake.reports.qualification import read_threshold
from lake.reports.rollup import apply_delta


class MoveConflict(ValueError):
    pass


def _replay(db, move_id, fingerprint):
    existing = find_move_receipt(db, move_id)
    if existing is None:
        return None
    receipt, stored_fingerprint = existing
    if stored_fingerprint != fingerprint:
        raise MoveConflict(f'move request differs: {move_id}')
    return receipt


def _require_current_row(db, from_partition, from_row):
    current = find_current_row(db, from_partition, from_row)
    if current is None:
        raise MissingRow(f'{from_partition}/{from_row}')
    if current.present:
        return current
    origin = find_row_origin(db, from_partition, from_row)
    if origin is not None and find_present_by_origin(db, origin) is not None:
        raise StaleBeforeImage(f'{from_partition}/{from_row}')
    raise MissingRow(f'{from_partition}/{from_row}')


def move_row(warehouse, move_id, from_partition, from_row, to_partition, to_row, expected_liters):
    require_name(move_id, 'move_id')
    require_name(from_partition, 'from_partition')
    require_name(from_row, 'from_row')
    require_name(to_partition, 'to_partition')
    require_name(to_row, 'to_row')
    require_liters(expected_liters)
    if from_partition == to_partition:
        raise ValueError('move requires two different partitions')
    fingerprint = move_fingerprint(from_partition, from_row, to_partition, to_row, expected_liters)
    db = warehouse.db
    previous = _replay(db, move_id, fingerprint)
    if previous is not None:
        return previous
    from_binding = lookup_partition(db, from_partition)
    to_binding = lookup_partition(db, to_partition)
    with warehouse.volumes.attach_volume(db, from_binding.volume_ref):
        with warehouse.volumes.attach_volume(db, to_binding.volume_ref, alias='volume_to'):
            with write_transaction(db, 'move_row', warehouse.before_commit):
                previous = _replay(db, move_id, fingerprint)
                if previous is not None:
                    return previous
                current = _require_current_row(db, from_partition, from_row)
                if not matches_before_image(current, expected_liters):
                    raise StaleBeforeImage(f'{from_partition}/{from_row}')
                if find_current_row(db, to_partition, to_row) is not None:
                    raise RowConflict(f'occupied row: {to_partition}/{to_row}')
                check_volume_binding(db, from_partition, from_binding.volume_ref, attached=True)
                check_volume_binding(
                    db, to_partition, to_binding.volume_ref, attached=True, schema='volume_to',
                )
                before = warehouse.volumes.read_current_value(db, from_row)
                if before != expected_liters:
                    raise RuntimeError('current row digest and volume value disagree')
                origin = find_row_origin(db, from_partition, from_row)
                if origin is None:
                    # Rows admitted before the origin ledger existed derive it
                    # from their original placement in the source volume.
                    placement = read_source_placement(db, from_row)
                    if placement is None:
                        raise RuntimeError('current row digest and volume placement disagree')
                    origin = (from_partition, placement.batch_id, placement.ordinal, from_row)
                    store_row_origin(db, from_partition, from_row, origin)
                fact = confirm_fact(db, 'move', move_id, from_partition)
                warehouse.volumes.delete_current_row(db, from_row)
                advance_coverage(db, fact.fact_id)
                insert_moved_row(
                    db, to_row, moved_row_batch(fact.fact_id), 0, expected_liters, schema='volume_to',
                )
                advance_coverage(db, fact.fact_id, schema='volume_to')
                vacate_current_row(db, current, fact.fact_id)
                insert_current_row(db, to_partition, to_row, expected_liters, fact.fact_id)
                store_row_origin(db, to_partition, to_row, origin)
                out_delta, in_delta = move_deltas(expected_liters, read_threshold(db))
                apply_delta(db, from_partition, out_delta)
                apply_delta(db, to_partition, in_delta)
                append_move(db, fact.fact_id, out_delta, to_partition, in_delta)
                receipt = MoveReceipt(
                    move_id, from_partition, from_row, to_partition, to_row, fact.fact_id, origin,
                )
                store_move_receipt(db, receipt, fingerprint)
                return receipt
