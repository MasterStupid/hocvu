"""Prevent dependency manifests from reintroducing known vulnerable releases."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import tomllib
import unittest

from packaging.requirements import Requirement
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]
# Highest patched versions required by the reported advisory ranges.
SECURITY_FLOORS = {
    "pypdf": "6.21.1",
    "pillow": "13.0.0",
    "python-multipart": "0.0.32",
    "sentence-transformers": "6.1.0",
    "aiohttp": "3.14.4",
    "anyio": "4.14.2",
    "certifi": "2026.10.19",
    "h11": "0.16.0",
    "idna": "3.15",
    "torch": "2.13.0",
    "transformers": "5.10.0",
    "httpcore2": "2.10.0",
    "httpx2": "2.12.0",
}
SEMANTIC_PACKAGES = {
    "sentence-transformers", "torch", "transformers", "httpcore2", "httpx2",
}
WORKSPACE = next(
    parent for parent in (ROOT, *ROOT.parents) if (parent / "pnpm-lock.yaml").exists()
)


def read_requirements(filename):
    requirements = {}
    for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            requirement = Requirement(line)
            requirements[requirement.name.lower()] = requirement
    return requirements


class DependencySecurityTests(unittest.TestCase):
    def test_manifests_enforce_patched_minimum_versions(self):
        for filename in ("requirements.txt", "requirements.production.txt"):
            requirements = read_requirements(filename)
            for name, fixed in SECURITY_FLOORS.items():
                # Semantic retrieval remains optional in the hosted manifest.
                if filename == "requirements.production.txt" and name in SEMANTIC_PACKAGES:
                    self.assertNotIn(name, requirements)
                    continue
                with self.subTest(manifest=filename, package=name):
                    self.assertIn(name, requirements)
                    bounds = [
                        spec for spec in requirements[name].specifier
                        if spec.operator in (">=", "==") and "*" not in spec.version
                    ]
                    self.assertTrue(
                        any(Version(spec.version) >= Version(fixed) for spec in bounds),
                        f"{filename}: {name} must require at least {fixed}",
                    )

    def test_installed_affected_packages_satisfy_manifest_and_security_floors(self):
        requirements = read_requirements("requirements.txt")
        for name, fixed in SECURITY_FLOORS.items():
            with self.subTest(package=name):
                try:
                    installed = Version(version(name))
                except PackageNotFoundError:
                    if name in SEMANTIC_PACKAGES:
                        continue  # Not required for hosted BM25 operation.
                    raise
                self.assertGreaterEqual(installed, Version(fixed))
                self.assertIn(installed, requirements[name].specifier)

    def test_hosted_and_root_requirements_stay_aligned(self):
        for filename in ("requirements.txt", "requirements.production.txt"):
            self.assertEqual(
                (WORKSPACE / filename).read_text(),
                (WORKSPACE / "artifacts/hocvu/app" / filename).read_text(),
            )

    def test_workspace_manifest_and_lock_enforce_http_security_floors(self):
        project = tomllib.loads((WORKSPACE / "pyproject.toml").read_text())["project"]
        requirements = {
            requirement.name.lower(): requirement
            for requirement in map(Requirement, project["dependencies"])
        }
        locked = {
            package["name"]: Version(package["version"])
            for package in tomllib.loads((WORKSPACE / "uv.lock").read_text())["package"]
        }
        for name in ("aiohttp", "anyio", "certifi", "h11", "idna"):
            fixed = Version(SECURITY_FLOORS[name])
            with self.subTest(package=name):
                self.assertIn(name, requirements)
                self.assertTrue(any(
                    spec.operator in (">=", "==") and Version(spec.version) >= fixed
                    for spec in requirements[name].specifier
                ))
                self.assertGreaterEqual(locked[name], fixed)
                self.assertIn(locked[name], requirements[name].specifier)
        self.assertTrue(SEMANTIC_PACKAGES.isdisjoint(requirements))

    def test_node_lock_excludes_reported_vulnerable_versions(self):
        lock = (WORKSPACE / "pnpm-lock.yaml").read_text()
        floors = {
            "body-parser": "2.4.0", "fast-uri": "3.1.9",
            "postcss-selector-parser": "6.1.5", "qs": "6.16.1",
            "undici": "7.30.1", "zod": "4.6.6",
        }
        for name, fixed in floors.items():
            versions = re.findall(rf"^  {re.escape(name)}@(\d[^:\n()]*):", lock, re.M)
            with self.subTest(package=name):
                self.assertTrue(versions, f"{name} missing from the lockfile")
                for release in versions:
                    self.assertGreaterEqual(Version(release), Version(fixed))
