"""Validate, package, and publish a release from one tested Git commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parent.parent
PLATFORMS = {
    "windows-x86_64": ("x86_64-pc-windows-msvc", (".exe", ".msi")),
    "darwin-aarch64": ("aarch64-apple-darwin", (".dmg",)),
    "darwin-x86_64": ("x86_64-apple-darwin", (".dmg",)),
}


def read_json(path: Path) -> dict:
    """Read a UTF-8 JSON document."""
    return json.loads(path.read_text(encoding="utf-8"))


def version_tuple(version: str) -> tuple[int, int, int]:
    """Accept stable semantic versions only; prereleases require a separate channel."""
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version):
        raise ValueError("Release version must be a stable semantic version, such as 1.3.1")
    return tuple(int(part) for part in version.split("."))


def validate(root: Path = ROOT) -> str:
    """Require every package manifest and release notes to describe the same version."""
    version = read_json(root / "package.json")["version"]
    version_tuple(version)
    npm_lock = read_json(root / "package-lock.json")
    cargo = tomllib.loads((root / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    cargo_lock = tomllib.loads((root / "src-tauri/Cargo.lock").read_text(encoding="utf-8"))
    versions = [
        npm_lock["version"], npm_lock["packages"][""]["version"],
        cargo["package"]["version"],
        read_json(root / "src-tauri/tauri.conf.json")["package"]["version"],
        next(item["version"] for item in cargo_lock["package"] if item["name"] == "kiroaas"),
    ]
    if any(value != version for value in versions):
        raise ValueError("Package, npm lock, Cargo, Cargo lock, and Tauri versions must match")
    notes = root / "releases" / f"v{version}.md"
    if not notes.is_file() or not notes.read_text(encoding="utf-8").strip():
        raise ValueError(f"Write release notes in releases/v{version}.md before publishing")
    return version


def bump(version: str, root: Path = ROOT) -> None:
    """Update all package versions without creating a tag or publishing anything."""
    version_tuple(version)
    for name in ("package.json", "package-lock.json", "src-tauri/tauri.conf.json"):
        path = root / name
        data = read_json(path)
        if name.endswith("tauri.conf.json"):
            data["package"]["version"] = version
        else:
            data["version"] = version
            if name == "package-lock.json":
                data["packages"][""]["version"] = version
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for name, pattern in (
        ("src-tauri/Cargo.toml", r'(?m)^(version = ")[^"]+("\s*)$'),
        ("src-tauri/Cargo.lock", r'(?m)(^name = "kiroaas"\nversion = ")[^"]+(")'),
    ):
        path = root / name
        text, count = re.subn(pattern, lambda match: match[1] + version + match[2],
                              path.read_text(encoding="utf-8"), count=1)
        if count != 1:
            raise ValueError(f"Cannot update package version in {name}")
        path.write_text(text, encoding="utf-8")
    print(f"Version set to {version}. Write releases/v{version}.md and push to main to publish.")


def gh_json(endpoint: str) -> dict | None:
    """Read GitHub metadata, distinguishing absent releases from authorization failures."""
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, check=False)
    if result.returncode:
        if "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(f"GitHub metadata request failed: {endpoint}")
    return json.loads(result.stdout)


def release_plan(version: str, repository: str, sha: str) -> bool:
    """Publish new versions and resume drafts, never overwrite an already published release."""
    release = gh_json(f"repos/{repository}/releases/tags/v{version}")
    if release and not release["draft"]:
        return False
    latest = gh_json(f"repos/{repository}/releases/latest")
    if latest and version_tuple(version) <= version_tuple(latest["tag_name"].removeprefix("v")):
        raise ValueError("A new release must have a version higher than the latest published release")
    tagged = gh_json(f"repos/{repository}/git/ref/tags/v{version}")
    if tagged:
        commit = gh_json(f"repos/{repository}/commits/v{version}")
        if not commit or commit["sha"] != sha:
            raise ValueError("The release tag already points to another commit; bump the version")
    return True


def plan() -> None:
    """Export the release decision for GitHub Actions; PRs always exercise packaging."""
    version = validate()
    publish = os.environ["GITHUB_REF"] == "refs/heads/main" and os.environ["GITHUB_EVENT_NAME"] != "pull_request"
    if publish:
        publish = release_plan(version, os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"])
    build = publish or os.environ["GITHUB_EVENT_NAME"] == "pull_request"
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"version={version}\nshould_build={str(build).lower()}\nshould_publish={str(publish).lower()}\n")
    print(f"Version {version}: build={build}, publish={publish}")


def package_backend() -> None:
    """Smoke-test the frozen backend, then create the archive consumed by Tauri."""
    source = ROOT / "python-backend/build/dist/kiro-gateway"
    executable = source / ("kiro-gateway.exe" if os.name == "nt" else "kiro-gateway")
    with tempfile.TemporaryDirectory() as temporary:
        result = subprocess.run([str(executable), "--help"], cwd=temporary,
                                capture_output=True, text=True, timeout=60, check=False)
    if result.returncode or "--port" not in result.stdout:
        raise RuntimeError(f"Frozen backend smoke test failed:\n{result.stdout}\n{result.stderr}")
    archive = ROOT / "src-tauri/resources/kiro-gateway.tar.gz"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(source, arcname="kiro-gateway")
    print(f"Frozen backend passed --help smoke test; packaged {archive.name}")


def digest(path: Path) -> str:
    """Hash an installer without reading it all into memory."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def collect(platform: str, sha: str, root: Path = ROOT) -> None:
    """Collect exact platform installers with source-commit and checksum metadata."""
    version = validate(root)
    target, suffixes = PLATFORMS[platform]
    bundle = root / "src-tauri/target" / target / "release/bundle"
    destination = root / "release-assets" / platform
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for suffix in suffixes:
        candidates = list(bundle.rglob(f"KiroaaS_{version}_*{suffix}"))
        if len(candidates) != 1 or not candidates[0].stat().st_size:
            raise ValueError(f"Expected exactly one nonempty {suffix} installer for {platform}")
        source = candidates[0]
        shutil.copy2(source, destination / source.name)
        files.append({"name": source.name, "sha256": digest(source), "size": source.stat().st_size})
    metadata = {"version": version, "commit": sha, "platform": platform, "target": target, "files": files}
    (destination / f"build-{platform}.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def verify_assets(directory: Path, version: str, sha: str) -> list[Path]:
    """Reject missing platforms, mixed commits, tampered assets, and duplicate filenames."""
    files: dict[str, Path] = {}
    for platform, (target, suffixes) in PLATFORMS.items():
        metadata = read_json(directory / f"build-{platform}.json")
        if (metadata["version"], metadata["commit"], metadata["platform"], metadata["target"]) != (version, sha, platform, target):
            raise ValueError("Release artifacts must all come from the same version and tested commit")
        if sorted(Path(item["name"]).suffix for item in metadata["files"]) != sorted(suffixes):
            raise ValueError(f"Incomplete installer set for {platform}")
        for item in metadata["files"]:
            name = item["name"]
            if Path(name).name != name or name in files or not name.startswith(f"KiroaaS_{version}_"):
                raise ValueError("Invalid or duplicate release asset filename")
            path = directory / name
            if not path.is_file() or not item["size"] or path.stat().st_size != item["size"] or digest(path) != item["sha256"]:
                raise ValueError("Release asset size or SHA-256 does not match its build metadata")
            files[name] = path
    checksum_file = directory / "SHA256SUMS.txt"
    checksum_file.write_text("".join(f"{digest(path)}  {name}\n" for name, path in sorted(files.items())), encoding="utf-8")
    return [*files.values(), checksum_file]


def publish(directory: Path) -> None:
    """Upload a complete release as a draft, then make it public after every upload succeeds."""
    version = validate()
    repository, sha = os.environ["GITHUB_REPOSITORY"], os.environ["GITHUB_SHA"]
    assets = verify_assets(directory, version, sha)
    if not release_plan(version, repository, sha):
        print("This version is already published; leaving it unchanged.")
        return
    tag = f"v{version}"
    release = gh_json(f"repos/{repository}/releases/tags/{tag}")
    common = ["--repo", repository]
    if not release:
        subprocess.run(["gh", "release", "create", tag, *common, "--target", sha,
                        "--title", f"{tag} Release", "--notes-file", str(ROOT / "releases" / f"{tag}.md"),
                        "--draft"], check=True)
    subprocess.run(["gh", "release", "upload", tag, *common, *map(str, assets), "--clobber"], check=True)
    subprocess.run(["gh", "release", "edit", tag, *common, "--draft=false", "--latest"], check=True)


def main() -> None:
    """Run the release helper from the repository root or CI."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    commands.add_parser("plan")
    commands.add_parser("package-backend")
    commands.add_parser("bump").add_argument("version")
    commands.add_parser("collect").add_argument("platform", choices=PLATFORMS)
    commands.add_parser("publish").add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "validate":
        print(f"Validated release v{validate()}")
    elif args.command == "bump":
        bump(args.version)
    elif args.command == "plan":
        plan()
    elif args.command == "package-backend":
        package_backend()
    elif args.command == "collect":
        collect(args.platform, os.environ["GITHUB_SHA"])
    elif args.command == "publish":
        publish(args.directory)


if __name__ == "__main__":
    main()
