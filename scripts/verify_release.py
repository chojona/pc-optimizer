"""Check the distributed source archive without running app or system commands."""
import hashlib
from pathlib import Path, PurePosixPath
import sys
import zipfile


def verify_release(directory):
    directory = Path(directory)
    archives = list(directory.glob('PC-Optimizer-v*-windows-source.zip'))
    if len(archives) != 1:
        raise ValueError('Expected exactly one Windows source archive.')
    archive = archives[0]
    expected = hashlib.sha256(archive.read_bytes()).hexdigest() + '  ' + archive.name
    if archive.with_suffix('.zip.sha256').read_text(encoding='ascii').strip() != expected:
        raise ValueError('Release checksum does not match the archive.')
    required = {'main.py', 'optimizer/__init__.py', 'optimizer/ui.py',
                'optimizer/readable.py', 'optimizer/readable_ui.py',
                'optimizer/assets/check.svg', 'optimizer/assets/chevron-down.svg',
                'README.md', 'requirements.txt', 'setup.ps1', 'Launch-PC-Optimizer.cmd'}
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError('Archive integrity check failed.')
        files = set()
        for entry in bundle.infolist():
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or path.parts[0] != 'PC-Optimizer':
                raise ValueError('Unexpected archive path: ' + entry.filename)
            relative = PurePosixPath(*path.parts[1:])
            if any(part in {'data', '.git', '.venv', '__pycache__'} for part in relative.parts):
                raise ValueError('Private or generated files found in the archive.')
            if not entry.is_dir():
                if relative.parts[0] not in {'optimizer', 'docs'} and str(relative) not in required:
                    raise ValueError('Unexpected release file: ' + str(relative))
                files.add(str(relative))
                if relative.suffix == '.py':
                    compile(bundle.read(entry), str(relative), 'exec')
        if missing := required - files:
            raise ValueError('Required release files missing: ' + ', '.join(sorted(missing)))
    print(f'Verified {archive.name}: checksum, runtime files, assets and Python syntax.')


if __name__ == '__main__':
    verify_release(sys.argv[1] if len(sys.argv) > 1 else 'dist')
