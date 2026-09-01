from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from check_sbom_licenses import license_ids
from dependency_exceptions import load_exceptions


class DependencyExceptionTests(unittest.TestCase):
    def write_policy(self, payload: dict[str, object]) -> Path:
        temporary = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False)
        with temporary:
            json.dump(payload, temporary)
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        return Path(temporary.name)

    def test_accepts_a_complete_unexpired_exception(self) -> None:
        path = self.write_policy(
            {
                "schema_version": 1,
                "exceptions": [
                    {
                        "ecosystem": "python",
                        "advisory_id": "GHSA-example",
                        "package": "example",
                        "reason": "upstream fix pending",
                        "owner": "@maintainer",
                        "expires": "2999-01-01",
                    }
                ],
            }
        )
        self.assertEqual(len(load_exceptions(path)), 1)

    def test_rejects_an_expired_exception(self) -> None:
        path = self.write_policy(
            {
                "schema_version": 1,
                "exceptions": [
                    {
                        "ecosystem": "python",
                        "advisory_id": "GHSA-example",
                        "package": "example",
                        "reason": "expired test",
                        "owner": "@maintainer",
                        "expires": "2000-01-01",
                    }
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "expired"):
            load_exceptions(path)


class LicensePolicyTests(unittest.TestCase):
    def test_declared_license_replaces_noassertion_conclusion(self) -> None:
        package = {"licenseConcluded": "NOASSERTION", "licenseDeclared": "MIT"}
        self.assertEqual(license_ids(package), {"MIT"})


if __name__ == "__main__":
    unittest.main()
