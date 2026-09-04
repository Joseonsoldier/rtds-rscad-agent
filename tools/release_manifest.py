"""Check or deliberately refresh portable package hashes after code review."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src/rtds_agent"
MANIFEST = ROOT / "release_manifest.json"


def payload():
    return {"schema_version": 1, "scope": "code and schemas; no installation or experiment approval",
            "files": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(ROOT.rglob("*")) if p.is_file() and p.suffix in {".py", ".json"} and p != MANIFEST}}


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    args = parser.parse_args()
    value = payload()
    if args.write:
        MANIFEST.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        print(f"Recorded {len(value['files'])} code/schema hashes; rerun tests before release")
        return 0
    if not MANIFEST.exists() or json.loads(MANIFEST.read_text(encoding="utf-8")) != value:
        print("Release manifest does not match reviewed source")
        return 1
    print(f"Release manifest matches {len(value['files'])} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
