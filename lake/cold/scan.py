from contextlib import closing
from dataclasses import dataclass

from lake.cold.checks import check_scanned_rows, check_volume_binding
from lake.cold.coverage import read_coverage
from lake.corrections.unit_of_work import read_transaction
from lake.partitions.source_rows import SourceRow


@dataclass(frozen=True, slots=True)
class MountView:
    partition_id: str
    volume_ref: str
    rows: tuple[SourceRow, ...]
    covered_through: int


def scan_volume(port, binding, after_row=None):
    with closing(port.open_for_read(binding.volume_ref)) as db:
        with read_transaction(db):
            check_volume_binding(db, binding.partition_id, binding.volume_ref)
            covered_through = read_coverage(db)
            rows = []
            with closing(port.iter_visible_rows(db)) as visible:
                for row in visible:
                    rows.append(row)
                    if after_row is not None:
                        after_row(binding.partition_id, row)
            check_scanned_rows(rows)
    return MountView(binding.partition_id, binding.volume_ref, tuple(rows), covered_through)
