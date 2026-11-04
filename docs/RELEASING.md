# Automatic releases

GitHub Actions runs the backend tests, release-tool tests, version validation, and
frontend build on pull requests and pushes to `main`. Pull requests also build the
installers, but cannot publish a release.

When a new version reaches `main`, the workflow builds Windows x64 (NSIS and MSI),
macOS Apple Silicon, and macOS Intel installers. Each frozen Python backend is
smoke-tested before bundling. All platforms must succeed and identify the same
commit before publication. Uploads go to a draft first; the release becomes public
only after all installers and `SHA256SUMS.txt` have been uploaded.

## Publish the next version

1. Run `python scripts/release.py bump 1.3.2` to update the npm, Cargo, and Tauri
   manifests and lockfiles together.
2. Write the release notes in `releases/v1.3.2.md`.
3. Commit the changes and push or merge them to `main`.
4. Follow the **CI and release** run in the repository's Actions tab.

No manual tag, artifact upload, or personal access token is required. The workflow
uses GitHub's built-in token, with write permission restricted to the publication
job. A commit that keeps the already published version runs verification without
publishing again. To recover a failed run, use **Re-run failed jobs**; a full rerun
or **Run workflow** on `main` can also resume an existing draft for the same commit.
If a draft tag exists and the source commit changed, use a new version rather than
moving the old tag.

## Distribution scope

This publishes downloadable installers on GitHub Releases, matching the existing
distribution method. Windows installers are not Authenticode-signed; macOS builds
use the repository's existing ad-hoc signing and are not notarized. No signing
secrets are needed for this workflow. It does not publish Tauri updater signatures
or deploy the website's `latest.json` endpoint; those require the existing updater
private key and a separately configured website deployment.

The workflows pin action revisions, the Rust toolchain, and PyInstaller; npm and
Cargo dependency lockfiles are committed. Never add account credentials or local
application configuration to the repository or release assets.
