"""Release invariants tested without network access or real installers."""

import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("release", Path(__file__).parents[1] / "release.py")
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)
SHA = "a" * 40


class ReleaseTests(unittest.TestCase):
    """Verify version synchronization and fail-closed publication of all platforms."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "src-tauri").mkdir()
        (self.root / "releases").mkdir()
        self.write("package.json", {"version": "1.3.1"})
        self.write("package-lock.json", {"version": "1.3.1", "packages": {"": {"version": "1.3.1"}}})
        self.write("src-tauri/tauri.conf.json", {"package": {"version": "1.3.1"}})
        (self.root / "src-tauri/Cargo.toml").write_text('[package]\nname = "kiroaas"\nversion = "1.3.1"\n', encoding="utf-8")
        (self.root / "src-tauri/Cargo.lock").write_text('[[package]]\nname = "kiroaas"\nversion = "1.3.1"\n', encoding="utf-8")
        (self.root / "releases/v1.3.1.md").write_text("Fix credential import.\n", encoding="utf-8")

    def write(self, name: str, data: dict) -> None:
        """Write synthetic metadata."""
        (self.root / name).write_text(json.dumps(data), encoding="utf-8")

    def installers(self) -> Path:
        """Collect four synthetic installers and merge their upload directories."""
        merged = self.root / "merged"
        merged.mkdir()
        for platform, (target, suffixes) in release.PLATFORMS.items():
            bundle = self.root / "src-tauri/target" / target / "release/bundle"
            bundle.mkdir(parents=True)
            for suffix in suffixes:
                (bundle / f"KiroaaS_1.3.1_{platform}{suffix}").write_bytes(b"synthetic installer")
            release.collect(platform, SHA, self.root)
            for file in (self.root / "release-assets" / platform).iterdir():
                shutil.copy2(file, merged / file.name)
        return merged

    def test_validate_and_bump_keep_manifests_in_sync(self) -> None:
        self.assertEqual(release.validate(self.root), "1.3.1")
        release.bump("1.3.2", self.root)
        with self.assertRaisesRegex(ValueError, "release notes"):
            release.validate(self.root)
        (self.root / "releases/v1.3.2.md").write_text("Next release.\n", encoding="utf-8")
        self.assertEqual(release.validate(self.root), "1.3.2")

    def test_mismatched_versions_fail_before_building(self) -> None:
        self.write("src-tauri/tauri.conf.json", {"package": {"version": "1.3.0"}})
        with self.assertRaisesRegex(ValueError, "must match"):
            release.validate(self.root)

    def test_invalid_versions_are_not_release_tags(self) -> None:
        for version in ("v1.3.1", "1.3.1-rc.1", "01.3.1", "1.3", "1.3.1\n", "$(command)"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.version_tuple(version)

    def test_complete_artifacts_generate_checksums(self) -> None:
        merged = self.installers()
        files = release.verify_assets(merged, "1.3.1", SHA)
        self.assertEqual(len(files), 5)
        checksums = (merged / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(checksums), 4)
        self.assertTrue(all(line.startswith(release.digest(files[0])) for line in checksums))

    def test_missing_platform_blocks_publication(self) -> None:
        merged = self.installers()
        (merged / "build-darwin-aarch64.json").unlink()
        with self.assertRaises(FileNotFoundError):
            release.verify_assets(merged, "1.3.1", SHA)

    def test_tampered_installer_blocks_publication(self) -> None:
        merged = self.installers()
        next(merged.glob("*.exe")).write_bytes(b"different installer")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            release.verify_assets(merged, "1.3.1", SHA)

    def test_mixed_source_commits_block_publication(self) -> None:
        merged = self.installers()
        with self.assertRaisesRegex(ValueError, "same version and tested commit"):
            release.verify_assets(merged, "1.3.1", "b" * 40)

    def test_missing_installer_blocks_collection(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one"):
            release.collect("windows-x86_64", SHA, self.root)

    def test_published_versions_are_never_overwritten(self) -> None:
        with patch.object(release, "gh_json", return_value={"draft": False}) as api:
            self.assertFalse(release.release_plan("1.3.1", "owner/repo", SHA))
        self.assertEqual(api.call_count, 1)

    def test_new_version_is_releasable(self) -> None:
        with patch.object(release, "gh_json", side_effect=[None, {"tag_name": "v1.3.0"}, None]):
            self.assertTrue(release.release_plan("1.3.1", "owner/repo", SHA))

    def test_downgrade_blocks_publication(self) -> None:
        with patch.object(release, "gh_json", side_effect=[None, {"tag_name": "v1.3.2"}]):
            with self.assertRaisesRegex(ValueError, "higher"):
                release.release_plan("1.3.1", "owner/repo", SHA)

    def test_existing_tag_must_match_the_tested_commit(self) -> None:
        with patch.object(release, "gh_json", side_effect=[{"draft": True}, {"tag_name": "v1.3.0"},
                                                           {"object": {}}, {"sha": "b" * 40}]):
            with self.assertRaisesRegex(ValueError, "another commit"):
                release.release_plan("1.3.1", "owner/repo", SHA)

    def test_draft_for_the_same_commit_can_resume(self) -> None:
        with patch.object(release, "gh_json", side_effect=[{"draft": True}, {"tag_name": "v1.3.0"},
                                                           {"object": {}}, {"sha": SHA}]):
            self.assertTrue(release.release_plan("1.3.1", "owner/repo", SHA))


if __name__ == "__main__":
    unittest.main()
