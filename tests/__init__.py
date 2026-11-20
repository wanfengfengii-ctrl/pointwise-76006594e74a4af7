from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from lake import open_warehouse, register_partition
from lake.partitions.source_rows import read_batch_source_rows


class InjectedFailure(OSError):
    pass


def totals(report):
    return report.count, report.liters


def deltas(page):
    return tuple((entry.delta.count, entry.delta.liters) for entry in page.entries)


def readings(view):
    return tuple((row.row_id, row.liters) for row in view.rows)


class ShiftCase(TestCase):
    threshold = 20

    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='linti-test-'))
        self.root = Path(directory) / 'warehouse'
        self.fail_operation = None
        self.on_row = None
        self.warehouse = self.enterContext(open_warehouse(
            self.root, self.threshold, before_commit=self.before_commit, after_scan_row=self.after_scan_row,
        ))
        self.a = register_partition(self.warehouse, 'A', 'volume-A')
        self.b = register_partition(self.warehouse, 'B', 'volume-B')

    def before_commit(self, operation):
        if operation == self.fail_operation:
            raise InjectedFailure(operation)

    def after_scan_row(self, partition_id, row):
        if self.on_row is not None:
            self.on_row(partition_id, row)

    def reopen(self, threshold=None):
        self.warehouse.close()
        self.warehouse = self.enterContext(open_warehouse(
            self.root, threshold, before_commit=self.before_commit, after_scan_row=self.after_scan_row,
        ))
        return self.warehouse

    def source(self, binding, batch_id):
        with self.warehouse.volumes.attach_volume(self.warehouse.db, binding.volume_ref):
            rows = read_batch_source_rows(self.warehouse.db, batch_id)
        return tuple((row.row_id, row.liters) for row in rows)
