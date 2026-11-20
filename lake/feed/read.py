from lake.corrections.unit_of_work import read_transaction
from lake.feed.append import FeedEntry, MoveFeedEntry, latest_feed_position
from lake.feed.cursors import resolve_cursor
from lake.feed.format import format_feed_page
from lake.partitions.source_rows import decode_liters
from lake.reports.deltas import ReportDelta


def read_feed(warehouse, cursor=None):
    db = warehouse.db
    with read_transaction(db):
        cursor = resolve_cursor(cursor, latest_feed_position(db))
        records = db.execute('''
            SELECT e.position, e.fact_id, f.partition_id, e.count_delta, e.liters_delta,
                   m.to_partition, m.in_count, m.in_liters
            FROM feed_entries AS e
            JOIN fact_commits AS f USING (fact_id)
            LEFT JOIN move_feed_parts AS m USING (position)
            WHERE e.position > ? ORDER BY e.position
        ''', (cursor.position,))
        entries = []
        for position, fact_id, partition_id, count, liters, to_partition, in_count, in_liters in records:
            delta = ReportDelta(decode_liters(count), decode_liters(liters))
            if to_partition is None:
                entries.append(FeedEntry(position, fact_id, partition_id, delta))
            else:
                in_delta = ReportDelta(decode_liters(in_count), decode_liters(in_liters))
                entries.append(MoveFeedEntry(
                    position, fact_id, partition_id, to_partition, delta, in_delta,
                ))
        return format_feed_page(entries, cursor)
