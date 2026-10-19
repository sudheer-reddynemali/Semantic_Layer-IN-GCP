"""Write data/sample_data.csv from data/sample_data.json.

The CSV has the 29 physical columns in ontology order. Empty cells are nulls.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from record_io import default_csv_path, default_json_path, load_json_records, write_csv_records


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Export sample_data.json to a 29-column CSV.")
    parser.add_argument("--input", type=Path, default=None, help="Source JSON. Defaults to data/sample_data.json.")
    parser.add_argument("--output", type=Path, default=None, help="Destination CSV. Defaults to data/sample_data.csv.")
    args = parser.parse_args(argv)
    source = args.input or default_json_path()
    target = args.output or default_csv_path()
    records = load_json_records(source)
    write_csv_records(target, records)
    print(f"wrote {len(records)} records to {target}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
