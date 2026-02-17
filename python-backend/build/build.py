#!/usr/bin/env python3
"""
Build script for creating standalone Kiro Gateway executable using PyInstaller.

This script builds the Python FastAPI server into a single executable that can
be bundled with the Tauri desktop app.

Usage:
    python build.py

Output:
    dist/kiro-gateway (or kiro-gateway.exe on Windows)
"""

import sys
import platform
import subprocess
from pathlib import Path


def check_pyinstaller():
    """Check if PyInstaller is installed."""
    try:
        import PyInstaller
        print(f"[OK] PyInstaller {PyInstaller.__version__} found")
        return True
    except ImportError:
        print("[ERROR] PyInstaller not found")
        print("\nPlease install PyInstaller:")
        print("  pip install pyinstaller")
        return False


def build():
    """Build the executable using PyInstaller."""
    if not check_pyinstaller():
        sys.exit(1)

    # Get the build directory
    build_dir = Path(__file__).parent
    spec_file = build_dir / "main.spec"

    if not spec_file.exists():
        print(f"[ERROR] Spec file not found: {spec_file}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Building Kiro Gateway executable")
    print(f"Platform: {platform.system()} {platform.machine()}")
    print(f"Spec file: {spec_file}")
    print(f"{'='*60}\n")

    # Run PyInstaller
    try:
        import PyInstaller.__main__

        PyInstaller.__main__.run([
            str(spec_file),
            '--clean',
            '--noconfirm',
        ])

        print(f"\n{'='*60}")
        print("[OK] Build completed successfully!")
        print(f"{'='*60}\n")

        # Show output location (onedir mode: dist/kiro-gateway/ directory)
        dist_dir = build_dir / "dist" / "kiro-gateway"
        exe_name = "kiro-gateway.exe" if platform.system() == "Windows" else "kiro-gateway"
        exe_path = dist_dir / exe_name

        if exe_path.exists():
            # Calculate total directory size
            total_size = sum(f.stat().st_size for f in dist_dir.rglob('*') if f.is_file())
            print(f"Output directory: {dist_dir}")
            print(f"Executable: {exe_path}")
            print(f"Total size: {total_size / (1024*1024):.1f} MB")
        else:
            print(f"Warning: Expected executable not found at {exe_path}")

    except Exception as e:
        print(f"\n[ERROR] Build failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    build()
