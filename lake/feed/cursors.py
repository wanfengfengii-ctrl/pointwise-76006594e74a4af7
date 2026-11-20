from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FeedCursor:
    position: int


START_CURSOR = FeedCursor(0)


def resolve_cursor(cursor, last_position):
    if cursor is None:
        return START_CURSOR
    if not isinstance(cursor, FeedCursor) or type(cursor.position) is not int:
        raise ValueError('invalid feed cursor')
    if not 0 <= cursor.position <= last_position:
        raise ValueError('feed cursor is outside the confirmed range')
    return cursor
