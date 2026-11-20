from lake import (
    StaleBeforeImage, correct_row, freeze, load_batch, mount_read, read_feed, read_frozen, read_live,
)
from tests import ShiftCase, deltas, readings, totals


class TestShift(ShiftCase):
    def test_load_audit_close_and_resume_shift(self):
        w = self.warehouse
        rows = [('01', 0), ('02', 19), ('03', 20), ('04', 25)]
        load_batch(w, 'A', 'original', rows)
        opening = read_feed(w)
        self.assertEqual(deltas(opening), ((2, 45),))
        self.assertEqual(totals(read_live(w)), (2, 45))
        changed = correct_row(w, 'change', 'A', '02', 19, 22)
        after_edit = read_feed(w, opening.cursor)
        self.assertEqual(deltas(after_edit), ((1, 22),))
        with self.assertRaises(StaleBeforeImage):
            correct_row(w, 'stale', 'A', '02', 19, 30)
        view = mount_read(w, 'A')
        self.assertEqual(readings(view), (('01', 0), ('02', 22), ('03', 20), ('04', 25)))
        self.assertEqual(view.covered_through, changed.fact_id)
        untouched = mount_read(w, 'B')
        self.assertEqual((untouched.rows, untouched.covered_through), ((), 0))
        signed = freeze(w, 'wharf-shift')
        self.assertEqual((signed.fact_cut, signed.threshold, signed.count, signed.liters), (changed.fact_id, 20, 3, 67))
        deleted = correct_row(w, 'delete', 'A', '04', 25, None)
        self.assertEqual(mount_read(w, 'A').covered_through, deleted.fact_id)
        w = self.reopen()
        self.assertEqual(read_frozen(w, 'wharf-shift'), signed)
        self.assertEqual(totals(read_live(w)), (2, 42))
        resumed = read_feed(w, after_edit.cursor)
        self.assertEqual(deltas(resumed), ((-1, -25),))
        tail = read_feed(w, resumed.cursor)
        self.assertEqual((tail.entries, tail.cursor), ((), resumed.cursor))
        delivered = deltas(opening) + deltas(after_edit) + deltas(resumed)
        downstream = (sum(count for count, _ in delivered), sum(liters for _, liters in delivered))
        self.assertEqual(downstream, (2, 42))
