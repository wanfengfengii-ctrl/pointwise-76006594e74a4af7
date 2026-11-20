"""Run the published move handoff scenario after implementing the new API."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from lake import (
    FeedEntry, MoveConflict, MoveFeedEntry, RowConflict, StaleBeforeImage,
    correct_row, freeze, load_batch, mount_read, move_row, open_warehouse,
    read_feed, read_frozen, read_live, register_partition,
)


class Interrupted(RuntimeError):
    pass


def stop_move(operation):
    if operation == 'move_row':
        raise Interrupted(operation)


def expect_error(error, function, *args):
    try:
        function(*args)
    except error:
        return
    raise AssertionError(f'{function.__name__} did not raise {error.__name__}')


def totals(report):
    return report.count, report.liters


def rows(view):
    return tuple((row.row_id, row.liters) for row in view.rows)


def run(root):
    first_move = ('move-1', 'A', 'x', 'B', 'y', 25)
    second_move = ('move-2', 'B', 'y', 'C', 'z', 25)
    with open_warehouse(root, 20) as w:
        source = register_partition(w, 'A', 'volume-A')
        register_partition(w, 'B', 'volume-B')
        register_partition(w, 'C', 'volume-C')
        original = load_batch(w, 'A', 'batch-A', [('x', 25)])
        load_batch(w, 'B', 'batch-B', [('x', 31)])
        opening = read_feed(w)
        signed = freeze(w, 'before-moves')
        initial_views = (mount_read(w, 'A'), mount_read(w, 'B'))
        assert totals(signed) == (2, 56)
        expect_error(RowConflict, move_row, w, 'occupied', 'A', 'x', 'B', 'x', 25)

    with open_warehouse(root, before_commit=stop_move) as w:
        expect_error(Interrupted, move_row, w, *first_move)

    with open_warehouse(root) as w:
        assert (mount_read(w, 'A'), mount_read(w, 'B')) == initial_views
        assert totals(read_live(w, 'A')) == (1, 25)
        assert totals(read_live(w, 'B')) == (1, 31)
        assert read_feed(w) == opening
        first = move_row(w, *first_move)
        assert first.origin == ('A', 'batch-A', 0, 'x')
        a, b = mount_read(w, 'A'), mount_read(w, 'B')
        assert rows(a) == () and rows(b) == (('x', 31), ('y', 25))
        assert a.covered_through == b.covered_through == first.fact_id
        assert totals(read_live(w, 'A')) == (0, 0)
        assert totals(read_live(w, 'B')) == (2, 56)
        first_page = read_feed(w, opening.cursor)
        entry, = first_page.entries
        assert isinstance(entry, MoveFeedEntry)
        assert (entry.fact_id, entry.position) == (first.fact_id, first_page.cursor.position)
        sides = [(entry.from_partition, *totals(entry.out_delta)), (entry.to_partition, *totals(entry.in_delta))]
        assert sides == [('A', -1, -25), ('B', 1, 25)]
        expect_error(StaleBeforeImage, move_row, w, 'stale', 'A', 'x', 'C', 'z', 25)
        second = move_row(w, *second_move)
        assert second.origin == first.origin
        second_page = read_feed(w, first_page.cursor)
        second_entry, = second_page.entries
        assert isinstance(second_entry, MoveFeedEntry) and second_entry.fact_id == second.fact_id
        edit = correct_row(w, 'late-edit', 'A', 'x', 25, 28)
        expect_error(StaleBeforeImage, correct_row, w, 'stale-edit', 'B', 'y', 25, 29)
        expect_error(RowConflict, load_batch, w, 'A', 'reuse-old', [('x', 40)])
        assert rows(mount_read(w, 'B')) == (('x', 31),)
        edit_page = read_feed(w, second_page.cursor)
        change, = edit_page.entries
        assert isinstance(change, FeedEntry)
        assert (change.fact_id, change.partition_id, totals(change.delta)) == (edit.fact_id, 'C', (0, 3))
        assert load_batch(w, 'A', 'batch-A', [('x', 25)]) == original

        source_path = w.volumes.path_for(source.volume_ref)
        parked = source_path.with_suffix('.parked')
        source_path.rename(parked)
        try:
            c = mount_read(w, 'C')
            assert rows(c) == (('z', 28),) and c.covered_through == edit.fact_id
        finally:
            parked.rename(source_path)

    with open_warehouse(root) as w:
        assert move_row(w, *first_move) == first
        assert move_row(w, *second_move) == second
        expect_error(MoveConflict, move_row, w, 'move-1', 'A', 'x', 'B', 'other', 25)
        reopened = read_frozen(w, signed.report_id)
        assert reopened == signed
        assert totals(read_live(w)) == (2, 59)
        assert read_feed(w, opening.cursor).entries == (entry, second_entry, change)
        assert read_feed(w, edit_page.cursor).entries == ()
        return {
            'first_move': sides, 'move_facts': [first.fact_id, second.fact_id],
            'origin': first.origin, 'cold_C': rows(c), 'signed': totals(reopened),
            'live': totals(read_live(w)),
        }


def main():
    with TemporaryDirectory(prefix='linti-move-') as directory:
        print(json.dumps(run(Path(directory) / 'warehouse'), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
