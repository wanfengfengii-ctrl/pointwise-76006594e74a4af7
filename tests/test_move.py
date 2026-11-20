from lake import (
    FeedCursor, FeedEntry, MissingRow, MoveConflict, MoveFeedEntry, RowConflict,
    StaleBeforeImage, UnknownPartition, correct_row, freeze, load_batch, mount_read,
    move_row, open_warehouse, read_feed, read_frozen, read_live, register_partition,
)
from tests import InjectedFailure, ShiftCase, readings, totals


class TestMove(ShiftCase):
    def register_c(self):
        return register_partition(self.warehouse, 'C', 'volume-C')

    def test_move_handoff(self):
        w = self.warehouse
        self.register_c()
        load_batch(w, 'A', 'batch-A', [('x', 25)])
        load_batch(w, 'B', 'batch-B', [('x', 31)])
        opening = read_feed(w)
        signed = freeze(w, 'before-moves')
        first = move_row(w, 'move-1', 'A', 'x', 'B', 'y', 25)
        self.assertEqual(
            (first.move_id, first.from_partition, first.from_row, first.to_partition, first.to_row),
            ('move-1', 'A', 'x', 'B', 'y'),
        )
        self.assertEqual(first.origin, ('A', 'batch-A', 0, 'x'))
        view_a, view_b = mount_read(w, 'A'), mount_read(w, 'B')
        self.assertEqual((readings(view_a), readings(view_b)), ((), (('x', 31), ('y', 25))))
        self.assertEqual((view_a.covered_through, view_b.covered_through), (first.fact_id, first.fact_id))
        self.assertEqual(totals(read_live(w, 'A')), (0, 0))
        self.assertEqual(totals(read_live(w, 'B')), (2, 56))
        self.assertEqual(totals(read_live(w)), (2, 56))
        self.assertEqual(read_frozen(w, 'before-moves'), signed)
        page = read_feed(w, opening.cursor)
        entry, = page.entries
        self.assertIsInstance(entry, MoveFeedEntry)
        self.assertEqual((entry.fact_id, entry.position), (first.fact_id, page.cursor.position))
        self.assertEqual((entry.from_partition, entry.to_partition), ('A', 'B'))
        self.assertEqual(totals(entry.out_delta), (-1, -25))
        self.assertEqual(totals(entry.in_delta), (1, 25))
        second = move_row(w, 'move-2', 'B', 'y', 'C', 'z', 25)
        self.assertEqual(second.origin, first.origin)
        second_page = read_feed(w, page.cursor)
        second_entry, = second_page.entries
        self.assertIsInstance(second_entry, MoveFeedEntry)
        self.assertEqual(second_entry.fact_id, second.fact_id)
        self.assertEqual(totals(second_entry.out_delta), (-1, -25))
        self.assertEqual(totals(second_entry.in_delta), (1, 25))
        edit = correct_row(w, 'late-edit', 'A', 'x', 25, 28)
        self.assertEqual((edit.partition_id, edit.row_id), ('A', 'x'))
        view_c = mount_read(w, 'C')
        self.assertEqual(readings(view_c), (('z', 28),))
        self.assertEqual(view_c.covered_through, edit.fact_id)
        self.assertEqual(readings(mount_read(w, 'B')), (('x', 31),))
        followup = read_feed(w, second_page.cursor)
        change, = followup.entries
        self.assertIsInstance(change, FeedEntry)
        self.assertEqual((change.fact_id, change.partition_id, totals(change.delta)),
                         (edit.fact_id, 'C', (0, 3)))
        self.assertEqual(totals(read_live(w)), (2, 59))
        self.assertEqual(read_frozen(w, 'before-moves'), signed)
        self.assertEqual(read_feed(w, followup.cursor).entries, ())

    def test_zero_delta_move_still_posted(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 8)])
        opening = read_feed(w)
        self.assertEqual(opening.entries, ())
        receipt = move_row(w, 'move-zero', 'A', 'x', 'B', 'y', 8)
        page = read_feed(w, opening.cursor)
        entry, = page.entries
        self.assertIsInstance(entry, MoveFeedEntry)
        self.assertEqual((entry.fact_id, entry.from_partition, entry.to_partition),
                         (receipt.fact_id, 'A', 'B'))
        self.assertEqual(totals(entry.out_delta), (0, 0))
        self.assertEqual(totals(entry.in_delta), (0, 0))
        self.assertGreater(page.cursor.position, opening.cursor.position)
        self.assertEqual(totals(read_live(w)), (0, 0))
        self.assertEqual(readings(mount_read(w, 'A')), ())
        self.assertEqual(readings(mount_read(w, 'B')), (('y', 8),))
        self.assertEqual(mount_read(w, 'A').covered_through, receipt.fact_id)
        self.assertEqual(mount_read(w, 'B').covered_through, receipt.fact_id)

    def test_move_validation(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 25)])
        load_batch(w, 'B', 'doomed', [('z', 30)])
        correct_row(w, 'delete', 'B', 'z', 30, None)
        opening = read_feed(w)
        with self.assertRaises(ValueError):
            move_row(w, 'm', 'A', 'x', 'A', 'y', 25)
        with self.assertRaises(UnknownPartition):
            move_row(w, 'm', 'A', 'x', 'Q', 'y', 25)
        with self.assertRaises(UnknownPartition):
            move_row(w, 'm', 'Q', 'x', 'B', 'y', 25)
        with self.assertRaises(MissingRow):
            move_row(w, 'm', 'A', 'absent', 'B', 'y', 25)
        with self.assertRaises(MissingRow):
            move_row(w, 'm', 'B', 'z', 'A', 'y', 30)
        with self.assertRaises(StaleBeforeImage):
            move_row(w, 'm', 'A', 'x', 'B', 'y', 24)
        with self.assertRaises(RowConflict):
            move_row(w, 'm', 'A', 'x', 'B', 'z', 25)
        for bad_liters in (-1, True, 1.5, None, '25'):
            with self.subTest(bad_liters=bad_liters):
                with self.assertRaises(ValueError):
                    move_row(w, 'm', 'A', 'x', 'B', 'y', bad_liters)
        for bad_name in ('', ' padded ', None, 25):
            with self.subTest(bad_name=bad_name):
                with self.assertRaises(ValueError):
                    move_row(w, bad_name, 'A', 'x', 'B', 'y', 25)
                with self.assertRaises(ValueError):
                    move_row(w, 'm', bad_name, 'x', 'B', 'y', 25)
                with self.assertRaises(ValueError):
                    move_row(w, 'm', 'A', bad_name, 'B', 'y', 25)
        self.assertEqual(read_feed(w), opening)
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 25),))
        self.assertEqual(totals(read_live(w)), (1, 25))
        receipt = move_row(w, 'm', 'A', 'x', 'B', 'y', 25)
        self.assertEqual(receipt.origin, ('A', 'batch', 0, 'x'))

    def test_move_replay_and_conflict(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 25)])
        first = move_row(w, 'move', 'A', 'x', 'B', 'y', 25)
        edit = correct_row(w, 'edit', 'B', 'y', 25, 27)
        second = move_row(w, 'move-again', 'B', 'y', 'A', 'z', 27)
        self.assertEqual(second.origin, first.origin)
        w = self.reopen()
        self.assertEqual(move_row(w, 'move', 'A', 'x', 'B', 'y', 25), first)
        self.assertEqual(move_row(w, 'move-again', 'B', 'y', 'A', 'z', 27), second)
        self.assertEqual(correct_row(w, 'edit', 'B', 'y', 25, 27), edit)
        with self.assertRaises(MoveConflict):
            move_row(w, 'move', 'A', 'x', 'B', 'z', 25)
        with self.assertRaises(MoveConflict):
            move_row(w, 'move', 'A', 'x', 'B', 'y', 26)
        with self.assertRaises(MoveConflict):
            move_row(w, 'move', 'B', 'y', 'A', 'z', 25)
        self.assertIsInstance(MoveConflict('m'), ValueError)
        self.assertEqual(readings(mount_read(w, 'A')), (('z', 27),))
        self.assertEqual(totals(read_live(w)), (1, 27))

    def test_move_commit_rollback(self):
        w = self.warehouse
        seed = load_batch(w, 'A', 'batch', [('x', 25)])
        opening = read_feed(w)
        self.fail_operation = 'move_row'
        with self.assertRaises(InjectedFailure):
            move_row(w, 'move', 'A', 'x', 'B', 'y', 25)
        self.fail_operation = None
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 25),))
        self.assertEqual(mount_read(w, 'A').covered_through, seed.fact_id)
        self.assertEqual(mount_read(w, 'B').covered_through, 0)
        self.assertEqual(read_feed(w), opening)
        self.assertEqual(totals(read_live(w, 'A')), (1, 25))
        self.assertEqual(totals(read_live(w, 'B')), (0, 0))
        w = self.reopen()
        self.assertEqual(read_feed(w), opening)
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 25),))
        receipt = move_row(w, 'move', 'A', 'x', 'B', 'y', 25)
        self.assertEqual(receipt.fact_id, seed.fact_id + 1)
        self.assertEqual(move_row(w, 'move', 'A', 'x', 'B', 'y', 25), receipt)
        self.assertEqual(readings(mount_read(w, 'A')), ())
        self.assertEqual(readings(mount_read(w, 'B')), (('y', 25),))
        self.assertEqual(mount_read(w, 'A').covered_through, receipt.fact_id)
        self.assertEqual(mount_read(w, 'B').covered_through, receipt.fact_id)
        page = read_feed(w, opening.cursor)
        entry, = page.entries
        self.assertIsInstance(entry, MoveFeedEntry)
        self.assertEqual(totals(read_live(w)), (1, 25))

    def test_corrections_follow_moves(self):
        w = self.warehouse
        self.register_c()
        load_batch(w, 'A', 'batch-a', [('x', 25)])
        load_batch(w, 'B', 'batch-b', [('x', 31)])
        opening = read_feed(w)
        move_row(w, 'move-1', 'A', 'x', 'B', 'y', 25)
        move_row(w, 'move-2', 'B', 'y', 'C', 'z', 25)
        edit = correct_row(w, 'edit', 'A', 'x', 25, 28)
        self.assertEqual(readings(mount_read(w, 'C')), (('z', 28),))
        self.assertEqual(correct_row(w, 'edit', 'A', 'x', 25, 28), edit)
        with self.assertRaises(StaleBeforeImage):
            correct_row(w, 'stale', 'B', 'y', 25, 29)
        removed = correct_row(w, 'remove', 'B', 'y', 28, None)
        self.assertTrue(removed.deleted)
        self.assertEqual(readings(mount_read(w, 'C')), ())
        self.assertEqual(totals(read_live(w)), (1, 31))
        for partition, row in (('A', 'x'), ('B', 'y'), ('C', 'z')):
            with self.subTest(partition=partition, row=row):
                with self.assertRaises(MissingRow):
                    correct_row(w, f'late-{partition}', partition, row, 28, 30)
        with self.assertRaises(MissingRow):
            move_row(w, 'move-3', 'C', 'z', 'A', 'w', 28)
        page = read_feed(w, opening.cursor)
        kinds = tuple(type(entry).__name__ for entry in page.entries)
        self.assertEqual(kinds, ('MoveFeedEntry', 'MoveFeedEntry', 'FeedEntry', 'FeedEntry'))
        self.assertEqual(page.entries[2].partition_id, 'C')
        self.assertEqual(totals(page.entries[2].delta), (0, 3))
        self.assertEqual(page.entries[3].partition_id, 'C')
        self.assertEqual(totals(page.entries[3].delta), (-1, -28))

    def test_addresses_stay_reserved(self):
        w = self.warehouse
        self.register_c()
        load_batch(w, 'A', 'batch', [('x', 25)])
        move_row(w, 'move', 'A', 'x', 'B', 'y', 25)
        load_batch(w, 'C', 'donor', [('w', 22)])
        with self.assertRaises(RowConflict):
            load_batch(w, 'A', 'reuse-old', [('x', 40)])
        with self.assertRaises(RowConflict):
            load_batch(w, 'B', 'reuse-new', [('y', 40)])
        with self.assertRaises(RowConflict):
            move_row(w, 'm2', 'C', 'w', 'A', 'x', 22)
        with self.assertRaises(RowConflict):
            move_row(w, 'm3', 'C', 'w', 'B', 'y', 22)
        correct_row(w, 'del', 'C', 'w', 22, None)
        with self.assertRaises(RowConflict):
            move_row(w, 'm4', 'B', 'y', 'C', 'w', 25)
        with self.assertRaises(RowConflict):
            load_batch(w, 'C', 'reuse-deleted', [('w', 40)])
        self.assertEqual(readings(mount_read(w, 'B')), (('y', 25),))
        self.assertEqual(totals(read_live(w)), (1, 25))

    def test_sessions_apply_in_commit_order(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 25)])
        with open_warehouse(self.root) as other:
            moved = move_row(w, 'move', 'A', 'x', 'B', 'y', 25)
            edit = correct_row(other, 'edit', 'A', 'x', 25, 30)
            self.assertGreater(edit.fact_id, moved.fact_id)
            self.assertEqual(readings(mount_read(other, 'B')), (('y', 30),))
            self.assertEqual(totals(read_live(w, 'B')), (1, 30))
            page = read_feed(other, FeedCursor(1))
            move_entry, edit_entry = page.entries
            self.assertIsInstance(move_entry, MoveFeedEntry)
            self.assertEqual((edit_entry.partition_id, totals(edit_entry.delta)), ('B', (0, 5)))
        self.assertEqual(readings(mount_read(w, 'B')), (('y', 30),))
        self.assertEqual(totals(read_live(w)), (1, 30))

    def test_feed_cursor_across_move_entries(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 25)])
        opening = read_feed(w)
        move_row(w, 'move', 'A', 'x', 'B', 'y', 25)
        correct_row(w, 'edit', 'B', 'y', 25, 28)
        page = read_feed(w, opening.cursor)
        move_entry, edit_entry = page.entries
        self.assertIsInstance(move_entry, MoveFeedEntry)
        self.assertIsInstance(edit_entry, FeedEntry)
        self.assertEqual(edit_entry.partition_id, 'B')
        self.assertEqual(read_feed(w, opening.cursor), page)
        tail = read_feed(w, page.cursor)
        self.assertEqual((tail.entries, tail.cursor), ((), page.cursor))
        with self.assertRaises(ValueError):
            read_feed(w, FeedCursor(page.cursor.position + 1))
        full = read_feed(w)
        self.assertEqual(tuple(type(entry).__name__ for entry in full.entries),
                         ('FeedEntry', 'MoveFeedEntry', 'FeedEntry'))
        plain = tuple((entry.delta.count, entry.delta.liters)
                      for entry in full.entries if isinstance(entry, FeedEntry))
        self.assertEqual(plain, ((1, 25), (0, 3)))

    def test_v1_warehouse_reopens_with_moves(self):
        w = self.warehouse
        batch = load_batch(w, 'A', 'batch', [('x', 25), ('keep', 19)])
        edit = correct_row(w, 'edit', 'A', 'keep', 19, 22)
        signed = freeze(w, 'shift')
        opening = read_feed(w)
        self._downgrade_to_v1(w.db)
        w = self.reopen()
        self.assertEqual(load_batch(w, 'A', 'batch', [('x', 25), ('keep', 19)]), batch)
        self.assertEqual(correct_row(w, 'edit', 'A', 'keep', 19, 22), edit)
        self.assertEqual(read_frozen(w, 'shift'), signed)
        self.assertEqual(read_feed(w), opening)
        receipt = move_row(w, 'move', 'A', 'x', 'B', 'y', 25)
        self.assertEqual(receipt.origin, ('A', 'batch', 0, 'x'))
        self.assertEqual(readings(mount_read(w, 'A')), (('keep', 22),))
        self.assertEqual(readings(mount_read(w, 'B')), (('y', 25),))
        self.assertEqual(totals(read_live(w)), (2, 47))
        followup = read_feed(w, opening.cursor)
        entry, = followup.entries
        self.assertIsInstance(entry, MoveFeedEntry)
        moved = correct_row(w, 'moved-edit', 'A', 'x', 25, 26)
        self.assertEqual(moved.fact_id, receipt.fact_id + 1)
        self.assertEqual(readings(mount_read(w, 'B')), (('y', 26),))
        second = move_row(w, 'move-2', 'A', 'keep', 'B', 'k', 22)
        self.assertEqual(second.origin, ('A', 'batch', 1, 'keep'))
        self.assertEqual(readings(mount_read(w, 'A')), ())
        self.assertEqual(readings(mount_read(w, 'B')), (('k', 22), ('y', 26)))
        self.assertEqual(totals(read_live(w)), (2, 48))

    @staticmethod
    def _downgrade_to_v1(db):
        db.execute('PRAGMA foreign_keys = OFF')
        try:
            db.execute('BEGIN IMMEDIATE')
            db.execute('''
                CREATE TABLE fact_commits_v1 (
                    fact_id INTEGER PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('batch', 'correction')),
                    operation_id TEXT NOT NULL,
                    partition_id TEXT NOT NULL REFERENCES partitions (partition_id),
                    UNIQUE (kind, operation_id)
                )
            ''')
            db.execute('''
                INSERT INTO fact_commits_v1 (fact_id, kind, operation_id, partition_id)
                SELECT fact_id, kind, operation_id, partition_id FROM fact_commits
            ''')
            db.execute('DROP TABLE fact_commits')
            db.execute('ALTER TABLE fact_commits_v1 RENAME TO fact_commits')
            db.execute('DROP TABLE row_origins')
            db.execute('DROP TABLE move_receipts')
            db.execute('DROP TABLE move_feed_parts')
            db.execute('COMMIT')
        except BaseException:
            db.execute('ROLLBACK')
            raise
        finally:
            db.execute('PRAGMA foreign_keys = ON')
