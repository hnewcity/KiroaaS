# Kiro Gateway Desktop App - Build Instructions

This guide walks you through building the Kiro Gateway desktop application from source.

## Prerequisites

### 1. Install Rust

Rust is required for building the Tauri backend.

**macOS/Linux:**

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
```

**Windows:**
Download and run the installer from: <https://rustup.rs/>

**Verify Installation:**

```bash
rustc --version
cargo --version
```

### 2. Install Node.js

Download from: <https://nodejs.org/> (v18 or later recommended)

**Verify Installation:**

```bash
node --version
npm --version
```

### 3. Install Python

Python 3.14 or later is required.

**Verify Installation:**

```bash
python3 --version
```

## Build Steps

### Step 1: Clone and Install Dependencies

```bash
# Clone the repository (if not already done)
git clone https://github.com/hnewcity/KiroaaS.git
cd kiro-gateway

# Install Node.js dependencies
npm install

# Install Python dependencies
cd python-backend
pip install -r requirements.txt
pip install pyinstaller
cd ..
```

### Step 2: Build the Python Backend

The Python FastAPI server needs to be bundled into a standalone executable:

```bash
cd python-backend/build
python build.py
cd ../..
```

This creates the executable at:

- **macOS/Linux**: `python-backend/build/dist/kiro-gateway`
- **Windows**: `python-backend/build/dist/kiro-gateway.exe`

**Verify the build:**

```bash
# macOS/Linux
ls -lh python-backend/build/dist/kiro-gateway

# Windows
dir python-backend\build\dist\kiro-gateway.exe
```

### Step 3: Copy Python Executable to Tauri Resources

```bash
# Create resources directory
mkdir -p src-tauri/resources

# Copy the executable
# macOS/Linux
cp python-backend/build/dist/kiro-gateway src-tauri/resources/

# Windows
copy python-backend\build\dist\kiro-gateway.exe src-tauri\resources\
```

### Step 4: Build the Desktop Application

```bash
npm run tauri:build
```

This will:

1. Build the React frontend (production mode)
2. Compile the Rust backend
3. Bundle everything into a native application
4. Create installers for your platform

**Build output location:**

- **macOS**: `src-tauri/target/release/bundle/dmg/` and `src-tauri/target/release/bundle/macos/`
- **Windows**: `src-tauri/target/release/bundle/msi/` and `src-tauri/target/release/bundle/nsis/`
- **Linux**: `src-tauri/target/release/bundle/deb/` and `src-tauri/target/release/bundle/appimage/`

### Step 5: Test the Application

**macOS:**

```bash
open src-tauri/target/release/bundle/macos/Kiro\ Gateway.app
```

**Windows:**

```bash
.\src-tauri\target\release\kiro-gateway-client.exe
```

**Linux:**

```bash
./src-tauri/target/release/kiro-gateway-client
```

## Development Mode

For development, you don't need to build the Python executable. Just run:

```bash
npm run tauri:dev
```

This will:

- Start the Vite dev server (React frontend with hot-reload)
- Launch the Tauri window
- Run the Python server directly with `python3` (not the bundled executable)

## Platform-Specific Notes

### macOS

**Code Signing (Optional but Recommended):**

For distribution, you should sign your app:

```bash
# Set your signing identity
export APPLE_SIGNING_IDENTITY="Developer ID Application: Your Name (TEAM_ID)"

# Build with signing
npm run tauri:build
```

**Notarization (Required for Distribution):**

To distribute outside the App Store, you need to notarize:

```bash
# After building, notarize the app
xcrun notarytool submit \
  src-tauri/target/release/bundle/dmg/Kiro\ Gateway_1.0.0_aarch64.dmg \
  --apple-id your@email.com \
  --team-id TEAM_ID \
  --password app-specific-password \
  --wait
```

### Windows

**Code Signing (Optional but Recommended):**

To avoid Windows Defender SmartScreen warnings:

1. Obtain a code signing certificate
2. Configure in `src-tauri/tauri.conf.json`:

   ```json
   "windows": {
     "certificateThumbprint": "YOUR_CERT_THUMBPRINT"
   }
   ```

### Linux

**Additional Dependencies:**

Some Linux distributions may require additional packages:

```bash
# Debian/Ubuntu
sudo apt install libwebkit2gtk-4.0-dev \
  build-essential \
  curl \
  wget \
  libssl-dev \
  libgtk-3-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev

# Fedora
sudo dnf install webkit2gtk3-devel \
  openssl-devel \
  curl \
  wget \
  libappindicator-gtk3 \
  librsvg2-devel

# Arch
sudo pacman -S webkit2gtk \
  base-devel \
  curl \
  wget \
  openssl \
  appmenu-gtk-module \
  gtk3 \
  libappindicator-gtk3 \
  librsvg
```

## Troubleshooting

### "rustc: command not found"

Rust is not installed or not in PATH.

**Solution:**

1. Install Rust: <https://rustup.rs/>
2. Restart your terminal
3. Verify: `rustc --version`

### "PyInstaller not found"

PyInstaller is not installed.

**Solution:**

```bash
pip install pyinstaller
```

### "Failed to bundle project"

The Python executable might be missing from resources.

**Solution:**

1. Verify the executable exists: `ls python-backend/build/dist/kiro-gateway`
2. Copy it to resources: `cp python-backend/build/dist/kiro-gateway src-tauri/resources/`
3. Rebuild: `npm run tauri:build`

### Build is very slow

First build takes longer as Rust compiles all dependencies.

**Solution:**

- Subsequent builds will be much faster (incremental compilation)
- Use `npm run tauri:dev` for development (faster iteration)

### "Cannot find module '@tauri-apps/api'"

Node modules not installed.

**Solution:**

```bash
npm install
```

## Build Optimization

### Reduce Bundle Size

1. **Strip debug symbols** (already configured in `Cargo.toml`):

   ```toml
   [profile.release]
   strip = true
   ```

2. **Enable LTO** (already configured):

   ```toml
   lto = true
   ```

3. **Optimize Python bundle**:
   - Remove unnecessary packages from `requirements.txt`
   - Use `--exclude` in PyInstaller spec for large unused modules

### Faster Development Builds

Use the development profile:

```bash
npm run tauri:dev
```

This skips:

- Python executable bundling (uses system Python)
- Frontend minification
- Rust optimizations

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Build Desktop App

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]

    runs-on: ${{ matrix.os }}

    steps:
      - uses: actions/checkout@v3

      - name: Setup Node.js
        uses: actions/setup-node@v3
        with:
          node-version: 18

      - name: Setup Rust
        uses: actions-rs/toolchain@v1
        with:
          toolchain: stable

      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.14'

      - name: Install dependencies
        run: |
          npm install
          cd python-backend
          pip install -r requirements.txt
          pip install pyinstaller

      - name: Build Python backend
        run: |
          cd python-backend/build
          python build.py

      - name: Copy to resources
        run: |
          mkdir -p src-tauri/resources
          cp python-backend/build/dist/kiro-gateway* src-tauri/resources/

      - name: Build Tauri app
        run: npm run tauri:build

      - name: Upload artifacts
        uses: actions/upload-artifact@v3
        with:
          name: app-${{ matrix.os }}
          path: src-tauri/target/release/bundle/
```

## Next Steps

After building:

1. **Test the application** thoroughly on your target platform
2. **Configure credentials** in the Settings tab
3. **Start the server** and verify it works
4. **Distribute** the installer to users

For more information, see:

- [Desktop App Documentation](DESKTOP_APP.md)
- [Main README](../README.md)
