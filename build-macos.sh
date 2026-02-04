#!/bin/bash
set -e

echo "=== KiroaaS macOS Build Script ==="

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v rustc &> /dev/null; then
    echo "Error: Rust not installed. Run:"
    echo "  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "Error: Node.js not installed"
    exit 1
fi

if ! command -v python3 &> /dev/null; then
    echo "Error: Python3 not installed"
    exit 1
fi

echo "Prerequisites OK"

# Install Node dependencies
echo "Installing Node dependencies..."
npm install

# Install Python dependencies
echo "Installing Python dependencies..."
cd python-backend
pip3 install -r requirements.txt
pip3 install pyinstaller
cd ..

# Build Python backend
echo "Building Python backend..."
cd python-backend/build
python3 build.py
cd ../..

# Copy to Tauri resources
echo "Copying Python executable to resources..."
mkdir -p src-tauri/resources
cp python-backend/build/dist/kiro-gateway src-tauri/resources/

# Build Tauri app
echo "Building macOS app..."
export TAURI_PRIVATE_KEY=$(cat ~/.tauri/kiroaas.key)
export TAURI_KEY_PASSWORD=""
npm run tauri:build

echo ""
echo "=== Build Complete ==="
echo "DMG: src-tauri/target/release/bundle/dmg/"
echo "App: src-tauri/target/release/bundle/macos/KiroaaS.app"
