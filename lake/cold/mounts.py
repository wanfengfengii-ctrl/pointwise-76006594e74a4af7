import sqlite3

from lake.cold.scan import scan_volume
from lake.partitions.catalog import lookup_partition


class MountBusy(RuntimeError):
    pass


class MountReadError(RuntimeError):
    pass


class MountGate:
    def __init__(self, path):
        self.path = path

    def acquire(self):
        # The dedicated SQLite lock is shared by separate same-warehouse sessions.
        lease = sqlite3.connect(self.path, timeout=0, isolation_level=None)
        try:
            lease.execute('BEGIN EXCLUSIVE')
        except BaseException as exc:
            lease.close()
            code = getattr(exc, 'sqlite_errorcode', 0) & 0xFF
            if code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                raise MountBusy('another cold volume is mounted') from exc
            raise
        return lease

    def release(self, lease):
        lease.close()


def mount_read(warehouse, partition_id):
    binding = lookup_partition(warehouse.db, partition_id)
    lease = warehouse.mount_gate.acquire()
    try:
        return scan_volume(warehouse.volumes, binding, warehouse.after_scan_row)
    except Exception as exc:
        raise MountReadError(f'cold read failed: {partition_id}') from exc
    finally:
        warehouse.mount_gate.release(lease)
