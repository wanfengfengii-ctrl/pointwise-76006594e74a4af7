from dataclasses import dataclass

from lake.feed.append import FeedEntry
from lake.feed.cursors import FeedCursor


@dataclass(frozen=True, slots=True)
class FeedPage:
    entries: tuple[FeedEntry, ...]
    cursor: FeedCursor


def format_feed_page(entries, cursor):
    entries = tuple(entries)
    continuation = FeedCursor(entries[-1].position) if entries else cursor
    return FeedPage(entries, continuation)
