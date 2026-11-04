"""Check packaged Python code against current source, including hidden workers."""
import argparse
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader


def verify(executable, source):
    archive = CArchiveReader(str(executable)).open_embedded_archive('PYZ.pyz')
    count = 0
    for module in archive.toc:
        if not (module == 'sight_core' or module.startswith('sight_core.')):
            continue
        relative = Path(*module.split('.'))
        path = source / relative.with_suffix('.py')
        if not path.is_file():
            path = source / relative / '__init__.py'
        actual = archive.extract(module)
        expected = compile(path.read_bytes(), actual.co_filename, 'exec', optimize=0)
        if actual != expected:
            raise ValueError(f'{executable.name} contains stale or different code for {module}')
        count += 1
    if count == 0:
        raise ValueError('No application code in bundle')
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    for filename in ('BEL.exe', 'BEL-worker.exe'):
        print(filename, verify(args.release / filename, source), 'modules matched source')
