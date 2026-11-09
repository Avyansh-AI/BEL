from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile
import sys

import pytest

from sight_core import asr_assets


@pytest.fixture
def installer(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / 'scripts/provision_asr.py'
    spec = importlib.util.spec_from_file_location('provision_asr_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = {'whisper-cli.exe': [3, hashlib.sha256(b'exe').hexdigest()]}
    weights = {'base-q5_1': [5, hashlib.sha256(b'model').hexdigest()]}
    source = tmp_path / 'cache'
    source.mkdir()
    with zipfile.ZipFile(source / 'whisper-bin-x64.zip', 'x') as archive:
        archive.writestr('Release/whisper-cli.exe', b'exe')
        archive.writestr('../unselected-file', b'ignored')
    raw = (source / 'whisper-bin-x64.zip').read_bytes()
    (source / 'ggml-base-q5_1.bin').write_bytes(b'model')
    for target in (module, asr_assets):
        monkeypatch.setattr(target, 'RUNTIME_FILES', runtime)
        monkeypatch.setattr(target, 'MODELS', weights)
    monkeypatch.setattr(module, 'RUNTIME_ARCHIVE', (len(raw), hashlib.sha256(raw).hexdigest()))
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    notices = tmp_path / 'third_party/asr'
    notices.mkdir(parents=True)
    for name in ('whisper.cpp-LICENSE.txt', 'Whisper-LICENSE.txt'):
        (notices / name).write_text('License test fixture')
    return module, source, tmp_path / 'installed'


def test_offline_install_publishes_only_verified_members_and_complete_manifest(installer, monkeypatch):
    module, source, destination = installer
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Offline install used network'))
    expected = module.install(source, destination, ['base-q5_1'])
    assert json.loads((destination / 'manifest.json').read_text()) == expected
    assert sorted(p.name for p in (destination / 'runtime').iterdir()) == ['whisper-cli.exe']
    assert not (destination.parent / 'unselected-file').exists()
    assert (destination / 'models/ggml-base-q5_1.bin').read_bytes() == b'model'


def test_installer_refuses_to_replace_existing_installation(installer):
    module, source, destination = installer
    destination.mkdir()
    (destination / 'owner-file').write_bytes(b'preserved')
    with pytest.raises(ValueError, match='already exists'):
        module.install(source, destination, ['base-q5_1'])
    assert (destination / 'owner-file').read_bytes() == b'preserved'


@pytest.mark.parametrize('name', ['whisper-bin-x64.zip', 'ggml-base-q5_1.bin'])
def test_damaged_input_never_publishes_an_installation(installer, name):
    module, source, destination = installer
    (source / name).write_bytes(b'bad')
    with pytest.raises(ValueError, match='integrity'):
        module.install(source, destination, ['base-q5_1'])
    assert not destination.exists()


def test_download_size_cap_leaves_no_valid_cache_entry(installer, monkeypatch):
    module, source, _ = installer
    @contextmanager
    def response(*args, **kwargs):
        yield io.BytesIO(b'oversized')
    monkeypatch.setattr(module.urllib.request, 'urlopen', response)
    target = source / 'new.bin'
    with pytest.raises(ValueError, match='exceeded'):
        module.fetch('https://example.invalid/fixture', target, (3, '0' * 64))
    assert not target.exists()


def test_verified_cached_artifact_requires_no_network(installer, monkeypatch):
    module, source, _ = installer
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Verified cache downloaded again'))
    module.fetch('https://example.invalid/fixture', source / 'ggml-base-q5_1.bin', module.MODELS['base-q5_1'])


def test_existing_source_and_parent_permission_policies_are_preserved(installer, monkeypatch):
    module, source, destination = installer
    protected = {source.resolve(), destination.parent.resolve()}
    secured = []
    def private(path):
        assert Path(path).resolve() not in protected, 'Installer changed an existing directory ACL'
        assert Path(path).name.startswith('.asr-install-')
        secured.append(Path(path))
    monkeypatch.setattr(module, 'private_directory', private)
    monkeypatch.setattr(sys, 'argv', ['provision_asr.py', '--source-directory', str(source),
                                    '--destination', str(destination), '--model', 'base-q5_1'])
    module.main()
    assert len(secured) == 1
    assert (destination / 'manifest.json').is_file()
