# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('keyring.backends')
if sys.platform == 'win32':
    # win32timezone is only importable (and only needed) on Windows -- collecting it
    # unconditionally breaks a Linux/macOS PyInstaller build.
    hiddenimports += ['win32timezone']

main_script = str(Path('agent') / 'main.py')

a = Analysis(
    [main_script],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Console build: for debugging -- shows a console window with live log output.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='health-agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Windowed build: no console window, for the tray-based day-to-day distribution.
exe_windowed = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='health-agent-windowed',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
