"""Prevent dependency manifests from reintroducing known vulnerable releases."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import unittest

from packaging.requirements import Requirement
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]
# Highest patched versions required by the reported advisory ranges.
SECURITY_FLOORS = {
    "pypdf": "6.19.0",
    "pillow": "12.3.0",
    "python-multipart": "0.0.31",
    "sentence-transformers": "5.6.0",
}


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
                if filename == "requirements.production.txt" and name == "sentence-transformers":
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
                    if name == "sentence-transformers":
                        continue  # Not required for hosted BM25 operation.
                    raise
                self.assertGreaterEqual(installed, Version(fixed))
                self.assertIn(installed, requirements[name].specifier)
