from dataclasses import dataclass

from lake.corrections.unit_of_work import write_transaction
from lake.partitions.source_rows import require_name


class UnknownPartition(LookupError):
    pass


class BindingConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PartitionBinding:
    partition_id: str
    volume_ref: str


def init_catalog(db):
    db.execute('''
        CREATE TABLE IF NOT EXISTS partitions (
            partition_id TEXT PRIMARY KEY NOT NULL,
            volume_ref TEXT NOT NULL UNIQUE
        ) WITHOUT ROWID
    ''')


def _find_partition(db, partition_id):
    record = db.execute(
        'SELECT partition_id, volume_ref FROM partitions WHERE partition_id = ?',
        (partition_id,),
    ).fetchone()
    return PartitionBinding(*record) if record is not None else None


def lookup_partition(db, partition_id):
    require_name(partition_id, 'partition_id')
    binding = _find_partition(db, partition_id)
    if binding is None:
        raise UnknownPartition(partition_id)
    return binding


def _check_registration(db, binding):
    existing = _find_partition(db, binding.partition_id)
    if existing is not None:
        if existing != binding:
            raise BindingConflict(f'partition already bound: {binding.partition_id}')
        return existing
    owner = db.execute(
        'SELECT partition_id FROM partitions WHERE volume_ref = ?',
        (binding.volume_ref,),
    ).fetchone()
    if owner is not None:
        raise BindingConflict(f'volume already bound to partition: {owner[0]}')
    return None


def register_partition(warehouse, partition_id, volume_ref):
    require_name(partition_id, 'partition_id')
    require_name(volume_ref, 'volume_ref')
    binding = PartitionBinding(partition_id, volume_ref)
    db = warehouse.db
    # Use one snapshot for the two preflight queries. Recheck after taking the write lock.
    with warehouse.volumes.registration_lock():
        existing = _check_registration(db, binding)
        if existing is not None:
            return existing
        with warehouse.volumes.attach_volume(db, volume_ref, create=True):
            with write_transaction(db, 'register_partition', warehouse.before_commit):
                existing = _check_registration(db, binding)
                if existing is not None:
                    return existing
                warehouse.volumes.initialize_volume(db, partition_id, volume_ref)
                db.execute(
                    'INSERT INTO partitions (partition_id, volume_ref) VALUES (?, ?)',
                    (partition_id, volume_ref),
                )
    return binding
