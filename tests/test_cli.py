from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from daemonstate_public.adapters import (
    AdapterUnavailable,
    BundleRequest,
    HostedAdapterStub,
    LocalFileAdapter,
)
from daemonstate_public.cli import (
    SCHEMA_VERSION,
    load_bundled_example,
    main,
    render_markdown,
    validate_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "daemonstate_public" / "examples" / "synthetic_context.json"


class PublicDemoTests(unittest.TestCase):
    def test_bundled_fixture_is_explicitly_synthetic(self) -> None:
        bundle = load_bundled_example()
        self.assertEqual(bundle["schema_version"], SCHEMA_VERSION)
        self.assertTrue(bundle["provenance"]["synthetic"])
        self.assertEqual(validate_bundle(bundle), [])

    def test_renderer_discloses_limitations_and_next_action(self) -> None:
        rendered = render_markdown(load_bundled_example())
        self.assertIn("Synthetic data only", rendered)
        self.assertIn("private DaemonState engine is not included", rendered)
        self.assertIn("### Exact next action", rendered)
        self.assertIn("public demo did not execute this command", rendered)

    def test_validator_rejects_non_synthetic_or_unknown_fields(self) -> None:
        bundle = copy.deepcopy(load_bundled_example())
        bundle["provenance"]["synthetic"] = False
        bundle["private_score"] = 0.99
        errors = validate_bundle(bundle)
        self.assertTrue(any("must be true" in error for error in errors))
        self.assertTrue(any("unknown field" in error for error in errors))

    def test_demo_json_command_is_machine_readable(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(["demo", "--format", "json"])
        self.assertEqual(result, 0)
        bundle = json.loads(output.getvalue())
        self.assertTrue(bundle["provenance"]["synthetic"])

    def test_invalid_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "invalid.json"
            path.write_text('{"schema_version": "wrong"}', encoding="utf-8")
            errors = io.StringIO()
            with redirect_stderr(errors):
                result = main(["validate", str(path)])
        self.assertEqual(result, 2)
        self.assertIn("ERROR", errors.getvalue())

    def test_local_adapter_reads_only_the_requested_fixture(self) -> None:
        adapter = LocalFileAdapter(FIXTURE)
        bundle = adapter.fetch_bundle(BundleRequest("workspace-synthetic-taskboard"))
        self.assertEqual(bundle["bundle_id"], "synthetic-taskboard-session-001")
        with self.assertRaises(LookupError):
            adapter.fetch_bundle(BundleRequest("another-workspace"))

    def test_hosted_adapter_is_an_explicit_stub(self) -> None:
        with self.assertRaises(AdapterUnavailable):
            HostedAdapterStub().fetch_bundle(BundleRequest("workspace-synthetic-taskboard"))


if __name__ == "__main__":
    unittest.main()
