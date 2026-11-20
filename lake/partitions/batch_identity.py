import hashlib
import json

from lake.partitions.source_rows import encode_liters, read_batch_source_rows


def batch_fingerprint(partition_id, rows):
    payload = [partition_id, [[row.row_id, encode_liters(row.liters)] for row in rows]]
    encoded = json.dumps(payload, separators=(',', ':'), ensure_ascii=True).encode('ascii')
    return hashlib.sha256(encoded).hexdigest()


def matches_batch(db, batch_id, stored_fingerprint, candidate_fingerprint, rows):
    if stored_fingerprint != candidate_fingerprint:
        return False
    return rows == read_batch_source_rows(db, batch_id)
