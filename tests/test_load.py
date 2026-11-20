from lake import (
    BatchConflict, BindingConflict, RowConflict, UnknownPartition, correct_row, freeze,
    load_batch, mount_read, open_warehouse, read_feed, read_frozen, read_live, register_partition,
)
from tests import InjectedFailure, ShiftCase, deltas, readings, totals


class TestLoad(ShiftCase):
    def test_threshold_and_empty(self):
        w = self.warehouse
        rows = [('a', 0), ('b', 19), ('c', 20), ('d', 25)]
        accepted = load_batch(w, 'A', 'batch', rows)
        self.assertEqual(read_live(w).threshold, 20)
        self.assertEqual(totals(read_live(w, 'A')), (2, 45))
        self.assertEqual(totals(read_live(w)), (2, 45))
        self.assertEqual(totals(read_live(w, 'B')), (0, 0))
        self.assertEqual(readings(mount_read(w, 'A')), tuple(rows))
        self.assertEqual((mount_read(w, 'B').rows, mount_read(w, 'B').covered_through), ((), 0))
        initial = read_feed(w)
        self.assertEqual(deltas(initial), ((2, 45),))
        self.assertEqual(initial.entries[0].fact_id, accepted.fact_id)
        with self.assertRaises(UnknownPartition):
            read_live(w, 'unknown')
        with self.assertRaises(UnknownPartition):
            load_batch(w, 'unknown', 'unknown-batch', [('x', 20)])

    def test_zero_value_at_zero_threshold(self):
        with open_warehouse(self.root / 'zero', 0) as w:
            register_partition(w, 'Z', 'zeros')
            load_batch(w, 'Z', 'batch', [('zero', 0)])
            self.assertEqual(totals(read_live(w)), (1, 0))
            self.assertEqual(deltas(read_feed(w)), ((1, 0),))
            correct_row(w, 'delete', 'Z', 'zero', 0, None)
            self.assertEqual(totals(read_live(w)), (0, 0))
            self.assertEqual(deltas(read_feed(w)), ((1, 0), (-1, 0)))

    def test_partition_scoped_rows(self):
        w = self.warehouse
        west = load_batch(w, 'A', 'west', [('1', 25)])
        east = load_batch(w, 'B', 'east', [('1', 20)])
        self.assertNotEqual(west.intake_id, east.intake_id)
        self.assertEqual(totals(read_live(w, 'A')), (1, 25))
        self.assertEqual(totals(read_live(w, 'B')), (1, 20))
        self.assertEqual(totals(read_live(w)), (2, 45))
        page = read_feed(w)
        self.assertEqual(tuple(entry.partition_id for entry in page.entries), ('A', 'B'))
        self.assertEqual(deltas(page), ((1, 25), (1, 20)))
        self.assertEqual(load_batch(w, 'A', 'west', [('1', 25)]), west)
        self.assertEqual(load_batch(w, 'B', 'east', [('1', 20)]), east)

    def test_retry_and_conflict(self):
        w = self.warehouse
        w.initialize(20)
        self.assertEqual(register_partition(w, 'A', 'volume-A'), self.a)
        with self.assertRaises(BindingConflict):
            register_partition(w, 'A', 'other-volume')
        with self.assertRaises(BindingConflict):
            register_partition(w, 'C', 'volume-A')
        original = load_batch(w, 'A', 'batch', [('x', 25)])
        opening = read_feed(w)
        self.assertEqual(load_batch(w, 'A', 'batch', [('x', 25)]), original)
        with self.assertRaises(BatchConflict):
            load_batch(w, 'A', 'batch', [('x', 26)])
        with self.assertRaises(BatchConflict):
            load_batch(w, 'B', 'batch', [('x', 25)])
        self.assertEqual(read_feed(w), opening)
        self.assertEqual(freeze(w, 'retry-cut').fact_cut, original.fact_id)
        self.assertEqual(totals(read_live(w)), (1, 25))
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 25),))

    def test_ordered_replay(self):
        w = self.warehouse
        rows = [('z', 20), ('a', 25)]
        accepted = load_batch(w, 'A', 'ordered', rows)
        self.assertEqual(load_batch(w, 'A', 'ordered', iter(rows)), accepted)
        opening = read_feed(w)
        with self.assertRaises(BatchConflict):
            load_batch(w, 'A', 'ordered', list(reversed(rows)))
        self.assertEqual(self.source(self.a, 'ordered'), tuple(rows))
        self.assertEqual(readings(mount_read(w, 'A')), (('a', 25), ('z', 20)))
        self.assertEqual(read_feed(w), opening)

    def test_atomic_batch(self):
        w = self.warehouse
        seed = load_batch(w, 'A', 'seed', [('used', 20)])
        opening = read_feed(w)
        candidates = [
            ([('new', 25), ('used', 26)], RowConflict),
            ([('new', 25), ('new', 26)], RowConflict),
            ([('new', 25), ('', 26)], ValueError),
        ]
        candidates.extend(([('new', 25), ('invalid', value)], ValueError) for value in (-1, True, 1.5, None, '20'))
        for rows, error in candidates:
            with self.subTest(rows=rows):
                with self.assertRaises(error):
                    load_batch(w, 'A', 'candidate', rows)
                view = mount_read(w, 'A')
                self.assertEqual(readings(view), (('used', 20),))
                self.assertEqual(view.covered_through, seed.fact_id)
                self.assertEqual(totals(read_live(w)), (1, 20))
                self.assertEqual(read_feed(w), opening)
        accepted = load_batch(w, 'A', 'candidate', [('new', 25)])
        self.assertEqual(accepted.fact_id, seed.fact_id + 1)
        self.assertEqual(totals(read_live(w)), (2, 45))
        self.assertEqual(deltas(read_feed(w, opening.cursor)), ((1, 25),))

    def test_failed_batch_can_retry_after_reopen(self):
        w = self.warehouse
        self.fail_operation = 'load_batch'
        with self.assertRaises(InjectedFailure):
            load_batch(w, 'A', 'retry', [('x', 25)])
        self.fail_operation = None
        w = self.reopen()
        self.assertEqual(readings(mount_read(w, 'A')), ())
        self.assertEqual(mount_read(w, 'A').covered_through, 0)
        self.assertEqual(totals(read_live(w)), (0, 0))
        self.assertEqual(read_feed(w).entries, ())
        self.assertEqual(load_batch(w, 'A', 'retry', [('x', 30)]).fact_id, 1)
        self.assertEqual(deltas(read_feed(w)), ((1, 30),))

    def test_reopen_replay(self):
        w = self.warehouse
        rows = [('changed', 19), ('deleted', 25)]
        receipt = load_batch(w, 'A', 'batch', rows)
        correct_row(w, 'edit', 'A', 'changed', 19, 22)
        removed = correct_row(w, 'remove', 'A', 'deleted', 25, None)
        opening = read_feed(w)
        w = self.reopen(20)
        w.initialize()
        self.assertEqual(register_partition(w, 'A', 'volume-A'), self.a)
        self.assertEqual(load_batch(w, 'A', 'batch', rows), receipt)
        self.assertEqual(self.source(self.a, 'batch'), tuple(rows))
        with self.assertRaises(RowConflict):
            load_batch(w, 'A', 'occupy-deleted', [('deleted', 40)])
        with self.assertRaises(ValueError):
            open_warehouse(self.root, 21)
        self.assertEqual(readings(mount_read(w, 'A')), (('changed', 22),))
        self.assertEqual(mount_read(w, 'A').covered_through, removed.fact_id)
        self.assertEqual(totals(read_live(w)), (1, 22))
        self.assertEqual(read_feed(w), opening)

    def test_exact_integer(self):
        w = self.warehouse
        huge = 1 << 15000
        load_batch(w, 'A', 'large', [('x', huge), ('y', huge + 3)])
        self.assertTrue(totals(read_live(w)) == (2, 2 * huge + 3))
        opening = read_feed(w)
        self.assertTrue(deltas(opening) == ((2, 2 * huge + 3),))
        signed = freeze(w, 'large-report')
        correct_row(w, 'remove-large', 'A', 'y', huge + 3, None)
        w = self.reopen()
        self.assertTrue(totals(read_live(w)) == (1, huge))
        self.assertTrue(readings(mount_read(w, 'A')) == (('x', huge),))
        self.assertTrue(deltas(read_feed(w, opening.cursor)) == ((-1, -huge - 3),))
        self.assertTrue(read_frozen(w, 'large-report') == signed)
