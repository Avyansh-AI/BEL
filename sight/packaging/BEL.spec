# Windows one-folder release. Keep all files together beside BEL.exe.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

source = Path(SPECPATH).parent
repo = source.parent
frontend = repo / 'frontend' / 'dist'
if not (frontend / 'index.html').is_file():
    raise SystemExit('Build the official frontend with npm ci && npm run build before packaging')
data = [(str(frontend), 'frontend/dist'), (str(source / 'apps/ui'), 'apps/ui'),
        (str(source / 'reports/hermes_skill_inventory.json'), 'reports')]
import sys
sys.path.insert(0, str(source))
from sight_core.needle import verify_assets
needle_assets = repo / '.cache/needle3'
verify_assets(needle_assets)
data.append((str(needle_assets), 'models/needle3'))
for package in ('pywebview', 'pystray', 'pythonnet', 'clr_loader', 'Pillow', 'fastapi', 'uvicorn'):
    data += copy_metadata(package)
data += collect_data_files('pystray', include_py_files=True)
hidden = ['uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.protocols.http.h11_impl',
          'uvicorn.protocols.websockets.websockets_impl', 'uvicorn.lifespan.on',
          'keyring.backends.Windows', 'pystray._win32', 'sight_core.needle_worker',
          'sight_core.capability_worker', 'sight_core.skill_worker']
excluded = ['pytest', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'tkinter', 'IPython', 'numpy',
            'webview.platforms.qt', 'webview.platforms.gtk', 'webview.platforms.cocoa']
desktop = Analysis([str(source / 'scripts/bel_desktop.py')], pathex=[str(source)],
                   binaries=[], datas=data, hiddenimports=hidden, excludes=excluded,
                   module_collection_mode={'pystray': 'py'}, noarchive=False)
desktop_pyz = PYZ(desktop.pure)
app = EXE(desktop_pyz, desktop.scripts, [], exclude_binaries=True, name='BEL',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=True)
worker = Analysis([str(source / 'scripts/bel_worker.py')], pathex=[str(source)],
                  binaries=[], datas=[], hiddenimports=hidden, excludes=excluded, noarchive=False)
worker_pyz = PYZ(worker.pure)
worker_exe = EXE(worker_pyz, worker.scripts, [], exclude_binaries=True, name='BEL-worker',
                 debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=True)
release = COLLECT(app, worker_exe, desktop.binaries, desktop.datas, worker.binaries, worker.datas,
                  strip=False, upx=False, name='BEL')
