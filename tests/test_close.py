import json

from lake import FeedCursor, correct_row, freeze, load_batch, read_feed, read_frozen, read_live
from tests import InjectedFailure, ShiftCase, deltas, totals


class TestClose(ShiftCase):
    def test_frozen_and_feed_after_reopen(self):
        w = self.warehouse
        batch = load_batch(w, 'A', 'batch', [('x', 25)])
        opening = read_feed(w)
        signed = freeze(w, 'shift')
        self.assertEqual((signed.report_id, signed.fact_cut, signed.threshold, signed.count, signed.liters),
                         ('shift', batch.fact_id, 20, 1, 25))
        self.assertEqual(read_feed(w), opening)
        removed = correct_row(w, 'delete', 'A', 'x', 25, None)
        w = self.reopen()
        original = read_frozen(w, 'shift')
        live = read_live(w)
        page = read_feed(w, opening.cursor)
        self.assertEqual(original, signed)
        self.assertEqual(freeze(w, 'shift'), signed)
        self.assertEqual(totals(live), (0, 0))
        self.assertEqual(deltas(page), ((-1, -25),))
        self.assertEqual(page.entries[0].fact_id, removed.fact_id)
        self.assertIsNone(read_frozen(w, 'unissued'))
        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'close_history',
            'input': {'threshold': 20, 'loaded': [25], 'signed_before_delete': True, 'deleted': [25]},
            'expected': {'frozen': [1, 25], 'live': [0, 0]},
            'actual': {'frozen': totals(original), 'live': totals(live)},
            'downstream_expected': [[-1, -25]],
            'downstream_actual': deltas(page),
            'code_paths': ['lake/reports/freeze.py', 'lake/reports/history.py', 'lake/corrections/admit.py', 'lake/feed/read.py'],
            'oracle': 'The sole qualifying row contributes 1 and 25 when signed. Its later deletion subtracts those values only from the live ledger.',
        }, sort_keys=True))

    def test_failed_freeze_can_retry(self):
        w = self.warehouse
        batch = load_batch(w, 'A', 'batch', [('x', 25)])
        opening = read_feed(w)
        self.fail_operation = 'freeze'
        with self.assertRaises(InjectedFailure):
            freeze(w, 'retry')
        self.assertIsNone(read_frozen(w, 'retry'))
        self.assertEqual(read_feed(w), opening)
        w = self.reopen()
        self.assertIsNone(read_frozen(w, 'retry'))
        self.fail_operation = None
        edit = correct_row(w, 'change-before-retry', 'A', 'x', 25, 32)
        signed = freeze(w, 'retry')
        self.assertGreater(edit.fact_id, batch.fact_id)
        self.assertEqual((signed.fact_cut, signed.threshold, signed.count, signed.liters), (edit.fact_id, 20, 1, 32))
        w = self.reopen()
        self.assertEqual(read_frozen(w, 'retry'), signed)
        self.assertEqual(freeze(w, 'retry'), signed)
        self.assertEqual(deltas(read_feed(w, opening.cursor)), ((0, 7),))

    def test_cursor_resume(self):
        w = self.warehouse
        batch = load_batch(w, 'A', 'batch', [('below', 8), ('above', 25)])
        opening = read_feed(w)
        signed = freeze(w, 'handoff')
        no_delta = correct_row(w, 'below', 'A', 'below', 8, 12)
        self.assertEqual(read_feed(w, opening.cursor).cursor, opening.cursor)
        removed = correct_row(w, 'above', 'A', 'above', 25, None)
        self.assertEqual((batch.fact_id, no_delta.fact_id, removed.fact_id), (1, 2, 3))
        w = self.reopen()
        resumed = read_feed(w, opening.cursor)
        self.assertEqual(deltas(resumed), ((-1, -25),))
        self.assertEqual((resumed.entries[0].fact_id, resumed.cursor.position), (3, 2))
        self.assertEqual(read_feed(w, opening.cursor), resumed)
        tail = read_feed(w, resumed.cursor)
        self.assertEqual((tail.entries, tail.cursor), ((), resumed.cursor))
        self.assertEqual(read_frozen(w, 'handoff'), signed)
        self.assertEqual(totals(read_live(w)), (0, 0))

    def test_invalid_cursor(self):
        w = self.warehouse
        load_batch(w, 'A', 'batch', [('x', 25)])
        opening = read_feed(w)
        correct_row(w, 'increase', 'A', 'x', 25, 27)
        for invalid in ('1', 1, True, FeedCursor(False), FeedCursor(1.0), FeedCursor(-1), FeedCursor(3)):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    read_feed(w, invalid)
        self.assertEqual(deltas(read_feed(w, opening.cursor)), ((0, 2),))
        self.assertEqual(deltas(read_feed(w, FeedCursor(0))), ((1, 25), (0, 2)))

    def test_empty_issue_and_invalid_report_id(self):
        w = self.warehouse
        self.assertIsNone(read_frozen(w, 'empty-shift'))
        for invalid in ('', ' padded ', None):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    freeze(w, invalid)
        report = freeze(w, 'empty-shift')
        self.assertEqual((report.fact_cut, report.threshold, report.count, report.liters), (0, 20, 0, 0))
        self.assertEqual(read_feed(w).cursor, FeedCursor(0))
