# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules


keyring_datas, keyring_binaries, keyring_hidden = collect_all("keyring")
hiddenimports = keyring_hidden + collect_submodules("uvicorn") + [
    "keyring.backends.Windows",
    "keyring.backends.fail",
    "PIL._tkinter_finder",
]

a = Analysis(
    ["run.py"],
    pathex=["."],
    binaries=keyring_binaries,
    datas=keyring_datas + [
        ("frontend/dist", "frontend/dist"),
        ("assets/app-icon.png", "assets"),
        ("claude-skills", "claude-skills"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NovelAI-LAN-Studio",
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
    icon=["assets/app-icon.ico"],
)
