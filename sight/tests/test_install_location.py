"""Installer errors must not move the caller into the application directory."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.name != 'nt', reason='Windows installer')
@pytest.mark.parametrize('argument', ['Wheelhouse', 'BrowserCache'])
def test_install_error_restores_callers_location(tmp_path, argument):
    source = Path(__file__).resolve().parents[1] / 'scripts/install.ps1'
    installer = tmp_path / 'application/scripts/install.ps1'
    installer.parent.mkdir(parents=True)
    shutil.copyfile(source, installer)
    caller = tmp_path / 'caller'
    caller.mkdir()
    wrapper = tmp_path / 'check.ps1'
    wrapper.write_text('''param($Installer, $Caller, $Argument)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Caller
$sightBefore = (Get-Location).Path
$sightArgs = @{'Offline'=$true; $Argument='missing-test-directory'}
if ($Argument -eq 'BrowserCache') { $sightArgs['Wheelhouse'] = $Caller }
$sightCaught = $false
try { & $Installer @sightArgs } catch { $sightCaught = $true }
if (-not $sightCaught) { throw 'Expected invalid input to fail before installing' }
if ((Get-Location).Path -ne $sightBefore) { throw 'Installer changed the caller directory on failure' }
''', encoding='utf-8')
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-File', str(wrapper),
                             str(installer), str(caller), argument], capture_output=True, text=True,
                            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(os.name != 'nt', reason='Windows installer')
def test_relative_inputs_resolve_before_entering_install_directory(tmp_path):
    installer = tmp_path / 'application/scripts/install.ps1'
    installer.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / 'scripts/install.ps1', installer)
    caller = tmp_path / 'caller'
    (caller / 'wheels').mkdir(parents=True)
    (caller / 'browsers').mkdir()
    wrapper = tmp_path / 'relative.ps1'
    wrapper.write_text('''param($Installer, $Caller)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $Caller
function py { throw 'VENv_TEST_FAILURE' }
$sightFailure = ''
try { & $Installer -Offline -Wheelhouse 'wheels' -BrowserCache 'browsers' }
catch { $sightFailure = $_.Exception.Message }
if ($sightFailure -ne 'VENv_TEST_FAILURE') { throw "Relative input resolution failed: $sightFailure" }
if ((Get-Location).Path -ne $Caller) { throw 'Venv failure changed caller location' }
''', encoding='utf-8')
    shell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    result = subprocess.run([str(shell), '-NoProfile', '-NonInteractive', '-File', str(wrapper),
                             str(installer), str(caller)], capture_output=True, text=True,
                            timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode == 0, result.stdout + result.stderr
