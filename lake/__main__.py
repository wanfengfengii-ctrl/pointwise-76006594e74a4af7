import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from lake import (
    correct_row, freeze, load_batch, mount_read, open_warehouse,
    read_feed, read_frozen, read_live, register_partition,
)


def _totals(report):
    return [report.count, report.liters]


def _deltas(page):
    return [[entry.delta.count, entry.delta.liters] for entry in page.entries]


def _check(stage, actual, expected):
    if actual != expected:
        raise ValueError(f'{stage}: expected {expected!r}, got {actual!r}')


def run_shift(sample, root):
    threshold = sample['threshold']
    operation = sample['batch']
    expected = sample['expected']
    with open_warehouse(root, threshold) as warehouse:
        for partition_id, volume_ref in sample['volumes']:
            register_partition(warehouse, partition_id, volume_ref)
        batch = load_batch(warehouse, operation['partition'], operation['id'], operation['rows'])
        initial = read_feed(warehouse)
        partition = _totals(read_live(warehouse, operation['partition']))
        empty = _totals(read_live(warehouse, sample['empty_partition']))
        _check('opening totals', partition, expected['opening'])
        _check('opening downstream', _deltas(initial), [expected['opening']])
        _check('empty partition', empty, [0, 0])
        _check('receipt replay', load_batch(warehouse, operation['partition'], operation['id'], operation['rows']), batch)
        marker = {
            'case_id': 'load_rollup',
            'input': {'threshold': threshold, 'rows': operation['rows'], 'empty': sample['empty_partition']},
            'expected': {'loaded': expected['opening'], 'empty': [0, 0]},
            'actual': {'loaded': partition, 'empty': empty},
            'downstream_expected': [expected['opening']],
            'downstream_actual': _deltas(initial),
            'code_paths': ['lake/partitions/import_batch.py', 'lake/reports/rollup.py', 'lake/feed/read.py'],
            'oracle': '20 L and 25 L meet the inclusive 20 L threshold. The other two rows and the empty partition contribute zero.',
        }

        edit = correct_row(warehouse, *sample['edit'])
        edited = read_feed(warehouse, initial.cursor)
        _check('edit downstream', _deltas(edited), [expected['edit_delta']])
        mounted = mount_read(warehouse, operation['partition'])
        _check('mounted rows', [[row.row_id, row.liters] for row in mounted.rows], expected['mounted'])
        _check('mounted coverage', mounted.covered_through, edit.fact_id)
        empty_mount = mount_read(warehouse, sample['empty_partition'])
        _check('empty mount', (empty_mount.rows, empty_mount.covered_through), ((), 0))
        signed = freeze(warehouse, sample['report'])
        _check('signed totals', _totals(signed), expected['signed'])
        _check('signed cut', signed.fact_cut, edit.fact_id)
        deletion = correct_row(warehouse, *sample['delete'])
        after_delete = mount_read(warehouse, operation['partition'])
        _check('deletion coverage', after_delete.covered_through, deletion.fact_id)
        _check('remaining rows', [[row.row_id, row.liters] for row in after_delete.rows], expected['remaining'])

    with open_warehouse(root) as warehouse:
        original = read_frozen(warehouse, signed.report_id)
        live = read_live(warehouse)
        resumed = read_feed(warehouse, edited.cursor)
        tail = read_feed(warehouse, resumed.cursor)
        _check('fixed report after reopening', original, signed)
        _check('live totals after reopening', _totals(live), expected['live'])
        _check('resumed downstream', _deltas(resumed), [expected['delete_delta']])
        _check('tail', (tail.entries, tail.cursor), ((), resumed.cursor))
        delivered = _deltas(initial) + _deltas(edited) + _deltas(resumed)
        downstream = [sum(pair[0] for pair in delivered), sum(pair[1] for pair in delivered)]
        _check('downstream day ledger', downstream, expected['live'])

    print('POINTWISE_SCENARIO ' + json.dumps(marker, ensure_ascii=False, sort_keys=True))
    print(json.dumps({
        'report': {'id': original.report_id, 'threshold': original.threshold,
                   'fact_cut': original.fact_cut, 'totals': _totals(original)},
        'current_totals': _totals(live), 'resumed_delta': _deltas(resumed),
        'downstream_totals': downstream, 'cursor': resumed.cursor.position,
    }, ensure_ascii=False, sort_keys=True))


def main():
    parser = argparse.ArgumentParser(description='Run the fixed-threshold warehouse shift sample')
    parser.add_argument('sample', type=Path)
    args = parser.parse_args()
    with args.sample.open(encoding='utf-8') as material:
        sample = json.load(material)
    with TemporaryDirectory(prefix='linti-shift-') as directory:
        run_shift(sample, Path(directory) / 'warehouse')


if __name__ == '__main__':
    main()
