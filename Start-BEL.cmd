@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-BEL.ps1" -LocalTTS -LocalDictation %*
