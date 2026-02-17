# KiroaaS Windows Build Script
$ErrorActionPreference = "Stop"

Write-Host "=== KiroaaS Windows Build Script ==="

# Initialize fnm (Node version manager) if available
if (Get-Command fnm -ErrorAction SilentlyContinue) {
    fnm env --use-on-cd --shell powershell | Out-String | Invoke-Expression
}

# Prefer Python 3.14/3.12 from standard install path over Anaconda
$PythonExe = "python"
$PipExe = "pip"
foreach ($ver in @("Python314", "Python313", "Python312")) {
    $candidate = "$env:LOCALAPPDATA\Programs\Python\$ver\python.exe"
    if (Test-Path $candidate) {
        $PythonExe = $candidate
        $PipExe = "$env:LOCALAPPDATA\Programs\Python\$ver\Scripts\pip.exe"
        break
    }
}

# Check prerequisites
Write-Host "Checking prerequisites..."

if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Rust not installed. Visit https://rustup.rs/ to install."
    exit 1
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Node.js not installed"
    exit 1
}

& $PythonExe --version
if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: Python not found at $PythonExe"
    exit 1
}

Write-Host "Prerequisites OK"

# Install Node dependencies
Write-Host "Installing Node dependencies..."
npm install

# Install Python dependencies
Write-Host "Installing Python dependencies..."
Push-Location python-backend
& $PipExe install -r requirements.txt
& $PipExe install pyinstaller
Pop-Location

# Build Python backend
Write-Host "Building Python backend..."
Push-Location python-backend/build
& $PythonExe build.py
if ($LASTEXITCODE -ne 0) {
    Pop-Location
    Write-Host "Error: Python backend build failed"
    exit 1
}
Pop-Location

# Package Python backend as tar.gz
Write-Host "Packaging Python backend..."
if (Test-Path src-tauri/resources/kiro-gateway) {
    Remove-Item -Recurse -Force src-tauri/resources/kiro-gateway
}
New-Item -ItemType Directory -Force -Path src-tauri/resources | Out-Null
Push-Location python-backend/build/dist
tar czf ../../../src-tauri/resources/kiro-gateway.tar.gz kiro-gateway
Pop-Location

# Build Tauri app
Write-Host "Building Windows app..."
$keyPath = "$env:USERPROFILE\.tauri\kiroaas.key"
if (Test-Path $keyPath) {
    $env:TAURI_PRIVATE_KEY = Get-Content $keyPath -Raw
    $env:TAURI_KEY_PASSWORD = ""
} else {
    Write-Host "Warning: Signing key not found at $keyPath, building without updater signing"
}
npm run tauri:build

Write-Host ""
Write-Host "=== Build Complete ==="
Write-Host "MSI: src-tauri/target/release/bundle/msi/"
Write-Host "NSIS: src-tauri/target/release/bundle/nsis/"
