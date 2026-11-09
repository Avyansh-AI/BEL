"""Pinned offline ASR inventory. No network access or editable execution paths."""
from contextlib import contextmanager, ExitStack
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sys

from .security import reject_links, safe_file

REVISION = 'd1be6fde11ac6e0407606b4e42fe72d34add8037'
MODEL_REVISION = '5359861c739e955e79d9a303bcbc70fb988958b1'
RUNTIME_URL = 'https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip'
RUNTIME_ARCHIVE = (8928640, '6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb')
MODELS = {
    'base-q5_1': (59707625, '422f1ae452ade6f30a004d7e5c6a43195e4433bc370bf23fac9cc591f01a8898'),
    'small-q5_1': (190085487, 'ae85e4a935d7a567bd102fe55afc16bb595bdb618e11b2fc7591bc08120411bb'),
}
RUNTIME_FILES = {
    "ggml-base.dll": [
        693248,
        "bede0d6b2d387236ecd2b5dd676d51c8984b5b6e0ae461a12174e9c01345c5f0"
    ],
    "ggml-cpu-alderlake.dll": [
        1009664,
        "d8f5c56ea490394eeae8b271650f2647aecd039a542d6df9e0140726e62a4603"
    ],
    "ggml-cpu-cannonlake.dll": [
        1049600,
        "74127b40abd4f595d9db6af0fa313a02e18ff42fc228bfa05281e7c788dd4507"
    ],
    "ggml-cpu-cascadelake.dll": [
        1061376,
        "4b11c427b844eeac87529af9a8d94b35aad2024666beb2a35e59fe3077e4b81e"
    ],
    "ggml-cpu-haswell.dll": [
        1010688,
        "1306b1014c8118d27234d8ddc0e66ced1f8c8476bf85071595fd182ea9b7263b"
    ],
    "ggml-cpu-icelake.dll": [
        1061376,
        "2b4dc4c66e7d8fe2807283816e9cf3b7f7d0556f59df34069871e37eab8aed40"
    ],
    "ggml-cpu-sandybridge.dll": [
        1026560,
        "04edbdebc01a1d421062a960881a4f34d520d99693999518243f332406444c6e"
    ],
    "ggml-cpu-skylakex.dll": [
        1049600,
        "1774714cf93621406ff35344b54715619a83242ae3e331e44d98a3b35ce801be"
    ],
    "ggml-cpu-sse42.dll": [
        862720,
        "f060318772c4c2dbac312bbfff6ea700b85dbc502bb38585a7186d06d549301a"
    ],
    "ggml-cpu-x64.dll": [
        866816,
        "4b4b05caba40d4309b5d710ef74c59ba190516b8489f27bdb1ba11ae33c6e9d3"
    ],
    "ggml.dll": [
        62464,
        "31fe18616d872af9b6134b47a6dff8072ae4ecbe5df0273f4f8dc36766c9db8e"
    ],
    "whisper-cli.exe": [
        479744,
        "331dba46d6427105d2b802cdbc7eae916ea1c5abf9b0d3b5cfe460d8db8e4366"
    ],
    "whisper.dll": [
        1370112,
        "034396d75bb5720c1851674ff64a96192b58f6927b68d334ebd254ce6cad9674"
    ]
}


def default_directory():
    if getattr(sys, 'frozen', False):
        return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'BEL/asr/whisper_cpp-b5454'
    return Path(__file__).resolve().parents[2] / '.cache/asr/whisper_cpp-b5454'


def manifest(models):
    if (not isinstance(models, (list, tuple)) or not models
            or any(not isinstance(model, str) or model not in MODELS for model in models)
            or len(models) != len(set(models))):
        raise ValueError('Unknown ASR model')
    return {'format': 1, 'engine': 'whisper.cpp', 'release': 'b5454', 'prerelease': True,
            'revision': REVISION, 'model_revision': MODEL_REVISION, 'license': 'MIT',
            'device': 'cpu', 'models': sorted(models),
            'runtime': RUNTIME_FILES, 'weights': {m: list(MODELS[m]) for m in sorted(models)}}


def verify_file(path, expected, cancelled=None):
    safe_file(path)
    size, expected_digest = expected
    with path.open('rb') as stream:
        info = os.fstat(stream.fileno())
        if info.st_size != size or info.st_nlink != 1:
            raise ValueError('ASR asset integrity mismatch')
        digest = hashlib.sha256()
        while chunk := stream.read(1024 * 1024):
            if cancelled is not None and cancelled.is_set():
                raise ValueError('ASR verification cancelled')
            digest.update(chunk)
    if digest.hexdigest() != expected_digest:
        raise ValueError('ASR asset integrity mismatch')


@contextmanager
def read_lock(path, directory=False):
    """Deny Windows writes/replacement while hashing and using an asset."""
    reject_links(path)
    if os.name != 'nt':
        raise ValueError('The pinned ASR runtime requires Windows x64')
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                   ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    flags = 0x00200000 | (0x02000000 if directory else 0)
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ValueError('ASR asset missing or in use')
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


@contextmanager
def verified_assets(directory, model, cancelled=None):
    root = reject_links(Path(directory).absolute())
    if model not in MODELS:
        raise ValueError('Unknown ASR model')
    with ExitStack() as locks:
        for path in (root, root / 'runtime', root / 'models'):
            locks.enter_context(read_lock(path, directory=True))
        locks.enter_context(read_lock(root / 'manifest.json'))
        if (root / 'manifest.json').stat().st_size > 16384:
            raise ValueError('Invalid ASR installation manifest')
        metadata = json.loads(safe_file(root / 'manifest.json').read_text(encoding='utf-8'))
        models = metadata.get('models') if isinstance(metadata, dict) else None
        if not isinstance(models, list) or model not in models or metadata != manifest(models):
            raise ValueError('ASR install is incomplete or unrecognized')
        if {x.name for x in (root / 'runtime').iterdir()} != set(RUNTIME_FILES):
            raise ValueError('Unexpected ASR runtime entry')
        if {x.name for x in (root / 'models').iterdir()} != {'ggml-' + m + '.bin' for m in models}:
            raise ValueError('Incomplete ASR model installation')
        for installed in models:
            # Each selected weight is fully hashed below, all installed weights
            # must at least be complete regular files before any worker starts.
            asset = safe_file(root / 'models' / ('ggml-' + installed + '.bin'))
            if asset.stat().st_size != MODELS[installed][0]:
                raise ValueError('Incomplete ASR model installation')
        for name, expected in RUNTIME_FILES.items():
            path = root / 'runtime' / name
            locks.enter_context(read_lock(path))
            verify_file(path, expected, cancelled)
        weights = root / 'models' / ('ggml-' + model + '.bin')
        locks.enter_context(read_lock(weights))
        verify_file(weights, MODELS[model], cancelled)
        yield root / 'runtime/whisper-cli.exe', weights
