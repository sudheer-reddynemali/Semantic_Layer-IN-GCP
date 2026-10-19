"""Compare FalkorDB observation nodes to a JSON or CSV record file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from falkor_client import connect, connection_settings, load_env_file, wait_until_ready
from fact_graph import compare_graph, prepare_plans
from record_io import configured_path, default_json_path, load_records


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the observation graph against JSON or CSV records.")
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="JSON or CSV records. Defaults to INPUT_DATA_FILE in .env, or data/sample_data.json.",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    load_env_file(root / ".env")
    settings = connection_settings()
    source = args.input or configured_path("INPUT_DATA_FILE", default_json_path())
    if source is None:
        raise ValueError("No input file configured. Set INPUT_DATA_FILE in .env or pass --input.")
    records = load_records(source)
    config = {
        "provenance_platform": settings["provenance_platform"],
        "source_table": settings["source_table"],
        "source_field_mapping": settings["source_field_mapping"],
        "data_version": settings["data_version"],
    }
    plans, collapsed = prepare_plans(records, config)
    client = connect(
        settings["host"], settings["port"], settings["username"], settings["password"]
    )
    wait_until_ready(client, attempts=5)
    errors = compare_graph(client, settings["graph"], plans)
    print(f"checked {len(plans)} observation keys from {source.name} against {settings['graph']}")
    if collapsed:
        print(f"duplicate keys collapsed: {collapsed}")
    if errors:
        print("validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validation passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
