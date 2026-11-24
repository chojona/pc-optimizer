import hashlib
import importlib.util
from pathlib import Path
import zipfile

import pytest


spec = importlib.util.spec_from_file_location('verify_release', Path(__file__).resolve().parents[1] / 'scripts/verify_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def make_bundle(tmp_path, extra=None, omit=None):
    files = {'main.py', 'optimizer/__init__.py', 'optimizer/ui.py',
             'optimizer/readable.py', 'optimizer/readable_ui.py',
             'optimizer/assets/check.svg', 'optimizer/assets/chevron-down.svg',
             'README.md', 'requirements.txt', 'setup.ps1', 'Launch-PC-Optimizer.cmd'}
    if omit:
        files.remove(omit)
    archive = tmp_path / 'PC-Optimizer-v1.0.0-windows-source.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        for name in sorted(files):
            bundle.writestr('PC-Optimizer/' + name, '# test fixture\n')
        if extra:
            bundle.writestr(extra, 'unexpected content')
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix('.zip.sha256').write_text(digest + '  ' + archive.name, encoding='ascii')
    return archive


def test_release_verifies_required_assets_and_checksum(tmp_path):
    archive = make_bundle(tmp_path)
    release.verify_release(tmp_path)
    archive.write_bytes(archive.read_bytes() + b'corrupted')
    with pytest.raises(ValueError, match='checksum'):
        release.verify_release(tmp_path)


@pytest.mark.parametrize('extra', ['PC-Optimizer/data/optimizer.sqlite3',
    'PC-Optimizer/../outside.txt', 'PC-Optimizer/.venv/pyvenv.cfg',
    'PC-Optimizer/.env', 'elsewhere/main.py'])
def test_release_rejects_private_or_unexpected_files(tmp_path, extra):
    make_bundle(tmp_path, extra=extra)
    with pytest.raises(ValueError):
        release.verify_release(tmp_path)


def test_release_requires_launcher(tmp_path):
    make_bundle(tmp_path, omit='Launch-PC-Optimizer.cmd')
    with pytest.raises(ValueError, match='Required release files missing'):
        release.verify_release(tmp_path)
