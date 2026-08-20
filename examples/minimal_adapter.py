"""Read the bundled fictional bundle through the public adapter protocol."""

from pathlib import Path

from daemonstate_public.adapters import BundleRequest, LocalFileAdapter


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "daemonstate_public" / "examples" / "synthetic_context.json"


def main() -> None:
    adapter = LocalFileAdapter(FIXTURE)
    bundle = adapter.fetch_bundle(BundleRequest("workspace-synthetic-taskboard"))
    print(f"adapter={adapter.name}")
    print(f"schema={bundle['schema_version']}")
    print(f"synthetic={str(bundle['provenance']['synthetic']).lower()}")


if __name__ == "__main__":
    main()
