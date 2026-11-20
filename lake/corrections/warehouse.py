from pathlib import Path

from lake.cold.mounts import MountGate
from lake.cold.volumes import VolumePort
from lake.corrections.commits import init_commit_log
from lake.corrections.current_rows import init_current_rows
from lake.corrections.receipts import init_correction_receipts
from lake.corrections.unit_of_work import open_connection, write_transaction
from lake.feed.append import init_feed
from lake.partitions.catalog import init_catalog
from lake.partitions.intake_receipts import init_intake_receipts
from lake.partitions.source_rows import require_liters
from lake.reports.history import init_frozen_history
from lake.reports.qualification import init_threshold
from lake.reports.rollup import init_rollups


class Warehouse:
    def __init__(self, root, *, before_commit=None, after_scan_row=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.volumes = VolumePort(self.root / 'volumes')
        self.mount_gate = MountGate(self.root / 'mount.sqlite3')
        self.before_commit = before_commit
        self.after_scan_row = after_scan_row
        self.db = open_connection(self.root / 'warehouse.sqlite3')

    def initialize(self, threshold=None):
        with write_transaction(self.db):
            init_threshold(self.db, threshold)
            init_catalog(self.db)
            init_commit_log(self.db)
            init_current_rows(self.db)
            init_intake_receipts(self.db)
            init_correction_receipts(self.db)
            init_rollups(self.db)
            init_frozen_history(self.db)
            init_feed(self.db)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


def open_warehouse(root, threshold=None, *, before_commit=None, after_scan_row=None):
    if threshold is not None:
        require_liters(threshold)
    warehouse = Warehouse(root, before_commit=before_commit, after_scan_row=after_scan_row)
    try:
        warehouse.initialize(threshold)
    except BaseException:
        warehouse.close()
        raise
    return warehouse
