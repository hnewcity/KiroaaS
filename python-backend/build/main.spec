# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Kiro Gateway

This bundles the FastAPI server into a standalone executable that can be
distributed without requiring Python installation.

Usage:
    pyinstaller main.spec --clean --noconfirm
"""

import sys
from pathlib import Path

# Get the project root directory (parent of build/)
# Use SPECPATH which PyInstaller sets to the spec file's directory
project_root = Path(SPECPATH).parent.absolute()

a = Analysis(
    [str(project_root / 'main.py')],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        # Include the kiro module
        (str(project_root / 'kiro'), 'kiro'),
        # Include .env.example as reference
        (str(project_root.parent / '.env.example'), '.'),
    ],
    hiddenimports=[
        # tiktoken dependencies
        'tiktoken_ext.openai_public',
        'tiktoken_ext',
        # uvicorn dependencies
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        # FastAPI dependencies
        'fastapi',
        'starlette',
        'pydantic',
        'pydantic_core',
        # httpx dependencies
        'httpx',
        'h11',
        'h2',
        'hpack',
        'hyperframe',
        # loguru
        'loguru',
        # Other dependencies
        'anyio',
        'sniffio',
        'certifi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary packages to reduce size
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='kiro-gateway',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Keep console for logging output
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
