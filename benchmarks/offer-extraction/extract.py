"""Extract any local quotation without benchmark labels, SharePoint access or persistence."""

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "apps" / "backend"
sys.path.insert(0, str(BACKEND))

from app.offers.extraction import extract_offers  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--output", type=Path, help="Write JSON here instead of stdout")
    args = parser.parse_args()
    document = args.document.resolve()
    output = args.output.resolve() if args.output else None
    os.chdir(BACKEND)
    result = extract_offers(document.read_bytes(), document.name)
    text = (
        json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    )
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text)
    else:
        print(text, end="")
    if result.failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
