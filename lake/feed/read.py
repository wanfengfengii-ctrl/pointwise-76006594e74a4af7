from lake.corrections.unit_of_work import read_transaction
from lake.feed.append import FeedEntry, latest_feed_position
from lake.feed.cursors import resolve_cursor
from lake.feed.format import format_feed_page
from lake.partitions.source_rows import decode_liters
from lake.reports.deltas import ReportDelta


def read_feed(warehouse, cursor=None):
    db = warehouse.db
    with read_transaction(db):
        cursor = resolve_cursor(cursor, latest_feed_position(db))
        records = db.execute('''
            SELECT e.position, e.fact_id, f.partition_id, e.count_delta, e.liters_delta
            FROM feed_entries AS e JOIN fact_commits AS f USING (fact_id)
            WHERE e.position > ? ORDER BY e.position
        ''', (cursor.position,))
        entries = (
            FeedEntry(position, fact_id, partition_id, ReportDelta(decode_liters(count), decode_liters(liters)))
            for position, fact_id, partition_id, count, liters in records
        )
        return format_feed_page(entries, cursor)
