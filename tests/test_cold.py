from lake import (
    MountBusy, MountReadError, UnknownPartition, correct_row, load_batch, mount_read, open_warehouse,
)
from tests import InjectedFailure, ShiftCase, readings


class TestCold(ShiftCase):
    def test_read_error_releases_mount(self):
        w = self.warehouse
        load_batch(w, 'A', 'first', [('01', 20), ('02', 25)])
        accepted = load_batch(w, 'B', 'second', [('07', 33)])
        seen = []

        def fail_on_second(partition, row):
            seen.append((partition, row.row_id))
            if partition == 'A' and row.row_id == '02':
                raise InjectedFailure('cold read')

        self.on_row = fail_on_second
        with self.assertRaises(MountReadError) as raised:
            mount_read(w, 'A')
        self.assertIsInstance(raised.exception.__cause__, InjectedFailure)
        self.assertEqual(seen, [('A', '01'), ('A', '02')])
        view = mount_read(w, 'B')
        self.assertEqual(readings(view), (('07', 33),))
        self.assertEqual(view.covered_through, accepted.fact_id)
        self.on_row = None
        self.assertEqual(readings(mount_read(w, 'A')), (('01', 20), ('02', 25)))

    def test_busy_is_shared_and_keeps_owner(self):
        w = self.warehouse
        load_batch(w, 'A', 'first', [('x', 20), ('y', 25)])
        load_batch(w, 'B', 'second', [('q', 30)])
        rejected = []
        with open_warehouse(self.root) as other:
            def try_second_mount(partition, row):
                with self.assertRaises(UnknownPartition):
                    mount_read(other, 'unknown')
                with self.assertRaises(MountBusy):
                    mount_read(other, 'B')
                rejected.append((partition, row.row_id))

            self.on_row = try_second_mount
            self.assertEqual(readings(mount_read(w, 'A')), (('x', 20), ('y', 25)))
            self.assertEqual(rejected, [('A', 'x'), ('A', 'y')])
            self.assertEqual(readings(mount_read(other, 'B')), (('q', 30),))

    def test_mount_snapshot(self):
        w = self.warehouse
        loaded_a = load_batch(w, 'A', 'first', [('1', 19)])
        load_batch(w, 'B', 'second', [('1', 25)])
        early_view = mount_read(w, 'A')
        self.assertEqual((readings(early_view), early_view.covered_through), ((('1', 19),), loaded_a.fact_id))
        edit_a = correct_row(w, 'a-edit', 'A', '1', 19, 22)
        edit_b = correct_row(w, 'b-edit', 'B', '1', 25, 29)
        self.assertGreater(edit_b.fact_id, edit_a.fact_id)
        view_a = mount_read(w, 'A')
        view_b = mount_read(w, 'B')
        self.assertEqual((readings(view_a), view_a.covered_through), ((('1', 22),), edit_a.fact_id))
        self.assertEqual((readings(view_b), view_b.covered_through), ((('1', 29),), edit_b.fact_id))
        self.assertEqual(readings(early_view), (('1', 19),))

    def test_wrong_volume_binding_refuses_delivery(self):
        w = self.warehouse
        load_batch(w, 'A', 'first', [('x', 20)])
        load_batch(w, 'B', 'second', [('x', 30)])
        path_a = w.volumes.path_for(self.a.volume_ref)
        path_b = w.volumes.path_for(self.b.volume_ref)
        parked = path_a.with_suffix('.parked')
        w.close()
        path_a.rename(parked)
        path_b.rename(path_a)
        w = self.reopen()
        with self.assertRaises(MountReadError):
            mount_read(w, 'A')
        w.close()
        path_a.rename(path_b)
        parked.rename(path_a)
        w = self.reopen()
        self.assertEqual(readings(mount_read(w, 'A')), (('x', 20),))
        self.assertEqual(readings(mount_read(w, 'B')), (('x', 30),))
