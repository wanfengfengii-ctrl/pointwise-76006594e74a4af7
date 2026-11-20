"""Run the original full-shift sample, then the published move handoff scenario."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from demo_move import run as run_moves
from lake.__main__ import run_shift


def main():
    with Path('samples/shift.json').open(encoding='utf-8') as material:
        sample = json.load(material)
    with TemporaryDirectory(prefix='linti-shift-') as directory:
        run_shift(sample, Path(directory) / 'warehouse')
    with TemporaryDirectory(prefix='linti-move-') as directory:
        print(json.dumps(run_moves(Path(directory) / 'warehouse'), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
