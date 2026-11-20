from lake import (
    CorrectionConflict, MissingRow, StaleBeforeImage, correct_row, freeze, load_batch,
    mount_read, read_feed, read_live,
)
from tests import InjectedFailure, ShiftCase, deltas, readings, totals


class TestCorrect(ShiftCase):
    def test_cross_threshold(self):
        w = self.warehouse
        batch = load_batch(w, 'A', 'batch', [('x', 19)])
        opening = read_feed(w)
        self.assertEqual(deltas(opening), ())
        accepted = correct_row(w, 'correction', 'A', 'x', 19, 22)
        self.assertGreater(accepted.fact_id, batch.fact_id)
        view = mount_read(w, 'A')
        self.assertEqual(readings(view), (('x', 22),))
        self.assertEqual(view.covered_through, accepted.fact_id)
        self.assertEqual(totals(read_live(w)), (1, 22))
        page = read_feed(w, opening.cursor)
        self.assertEqual(deltas(page), ((1, 22),))
        self.assertEqual(page.entries[0].fact_id, accepted.fact_id)

    def test_stale_before_image(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 19)])
        accepted = correct_row(w, 'first', 'A', 'x', 19, 22)
        opening = read_feed(w)
        with self.assertRaises(StaleBeforeImage):
            correct_row(w, 'stale', 'A', 'x', 19, 30)
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 22),))
        self.assertEqual(mount_read(w, 'A').covered_through, accepted.fact_id)
        self.assertEqual(totals(read_live(w)), (1, 22))
        self.assertEqual(read_feed(w), opening)
        self.assertEqual(read_feed(w, opening.cursor).entries, ())
        self.assertEqual(freeze(w, 'latest-cut').fact_cut, accepted.fact_id)

    def test_zero_effect_edit(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 8)])
        view = mount_read(w, 'A')
        opening = read_feed(w)
        accepted = correct_row(w, 'below', 'A', 'x', 8, 12)
        self.assertGreater(accepted.fact_id, view.covered_through)
        self.assertEqual(readings(view), (('x', 8),))
        current = mount_read(w, 'A')
        self.assertEqual(readings(current), (('x', 12),))
        self.assertEqual(current.covered_through, accepted.fact_id)
        self.assertEqual(totals(read_live(w)), (0, 0))
        self.assertEqual(read_feed(w, opening.cursor), opening)
        self.assertEqual(correct_row(w, 'below', 'A', 'x', 8, 12), accepted)
        self.assertEqual(freeze(w, 'below-cut').fact_cut, accepted.fact_id)

    def test_request_replay(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 19)])
        accepted = correct_row(w, 'change', 'A', 'x', 19, 22)
        deletion = correct_row(w, 'remove', 'A', 'x', 22, None)
        self.assertTrue(deletion.deleted)
        w = self.reopen()
        self.assertEqual(correct_row(w, 'change', 'A', 'x', 19, 22), accepted)
        self.assertEqual(correct_row(w, 'remove', 'A', 'x', 22, None), deletion)
        with self.assertRaises(CorrectionConflict):
            correct_row(w, 'change', 'A', 'x', 19, 24)
        with self.assertRaises(MissingRow):
            correct_row(w, 'new', 'A', 'x', 22, 24)
        with self.assertRaises(MissingRow):
            correct_row(w, 'missing', 'A', 'absent', 0, None)
        self.assertEqual(deltas(read_feed(w)), ((1, 22), (-1, -22)))
        self.assertEqual(readings(mount_read(w, 'A')), ())

    def test_signed_delta(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 25)])
        opening = read_feed(w)
        increase = correct_row(w, 'increase', 'A', 'x', 25, 30)
        current = read_feed(w, opening.cursor)
        self.assertEqual(totals(read_live(w)), (1, 30))
        self.assertEqual(deltas(current), ((0, 5),))
        self.assertEqual(current.entries[0].fact_id, increase.fact_id)
        deleted = correct_row(w, 'delete', 'A', 'x', 30, None)
        tail = read_feed(w, current.cursor)
        self.assertEqual(deltas(tail), ((-1, -30),))
        self.assertEqual(tail.entries[0].fact_id, deleted.fact_id)
        self.assertEqual(totals(read_live(w)), (0, 0))
        view = mount_read(w, 'A')
        self.assertEqual(view.rows, ())
        self.assertEqual(view.covered_through, deleted.fact_id)

    def test_commit_rollback(self):
        w = self.warehouse
        seed = load_batch(w, 'A', 'batch', [('x', 25)])
        opening = read_feed(w)
        self.fail_operation = 'correct_row'
        with self.assertRaises(InjectedFailure):
            correct_row(w, 'retry', 'A', 'x', 25, 31)
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 25),))
        self.assertEqual(mount_read(w, 'A').covered_through, seed.fact_id)
        self.assertEqual(totals(read_live(w)), (1, 25))
        self.assertEqual(read_feed(w, opening.cursor).entries, ())
        self.fail_operation = None
        w = self.reopen()
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 25),))
        self.assertEqual(read_feed(w), opening)
        self.assertEqual(freeze(w, 'rollback-cut').fact_cut, seed.fact_id)
        accepted = correct_row(w, 'retry', 'A', 'x', 25, 31)
        self.assertEqual(accepted.fact_id, seed.fact_id + 1)
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 31),))
        self.assertEqual(totals(read_live(w)), (1, 31))
        self.assertEqual(deltas(read_feed(w, opening.cursor)), ((0, 6),))
