"""Conservative public source and distribution audit. Never prints secret values."""
import argparse
import json
from pathlib import Path
import re
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", "__pycache__", "build", "dist", ".validation", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".rtfx", ".dfx", ".sib", ".inf", ".sqlite", ".db", ".csv", ".zip", ".pem", ".key", ".pfx", ".png", ".pdf"}
PATTERNS = {
    "openai_key": re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}"),
    "github_token": re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "personal_store": re.compile(r"vs_[0-9a-f]{24,}"),
    "private_profile": re.compile(r"[A-Za-z]:[/\\]Users[/\\]ADMIN\b", re.I),
    "old_install_binding": re.compile(r"[A-Za-z]:[/\\]RSCAD_273|_[r]tds_expert_agent"),
}


def inspect(name, data):
    issues = []
    p = Path(name)
    if p.suffix.lower() in FORBIDDEN_SUFFIXES or p.name in {"config.json", "execution_policy.json", ".env", "execution.lock"}:
        issues.append({"file": name, "kind": "private_or_vendor_artifact_type"})
    if len(data) > 2 * 1024 * 1024:
        issues.append({"file": name, "kind": "unexpected_large_file"})
    try:
        content = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return issues + [{"file": name, "kind": "unexpected_binary"}]
    for label, pattern in PATTERNS.items():
        if pattern.search(content):
            issues.append({"file": name, "kind": label})
    return issues


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifacts", type=Path, nargs="*")
    args = parser.parse_args()
    issues = []
    checked = 0
    for p in ROOT.rglob("*"):
        rel = p.relative_to(ROOT)
        if any(part in SKIP or part.endswith(".egg-info") for part in rel.parts):
            continue
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT):
            issues.append({"file": str(rel), "kind": "link_or_path_escape"})
        elif p.is_file():
            checked += 1
            issues.extend(inspect(rel.as_posix(), p.read_bytes()))
    for artifact in args.artifacts or []:
        if artifact.suffix == ".whl":
            with zipfile.ZipFile(artifact) as archive:
                for name in archive.namelist():
                    if not name.endswith("/"):
                        checked += 1
                        issues.extend(inspect(name, archive.read(name)))
        elif artifact.name.endswith(".tar.gz"):
            with tarfile.open(artifact) as archive:
                for entry in archive.getmembers():
                    if entry.issym() or entry.islnk():
                        issues.append({"file": entry.name, "kind": "archive_link"})
                    elif entry.isfile():
                        checked += 1
                        issues.extend(inspect(entry.name, archive.extractfile(entry).read()))
        else:
            issues.append({"file": artifact.name, "kind": "unknown_distribution"})
    print(json.dumps({"checked": checked, "issues": issues, "passed": not issues}, indent=2))
    return bool(issues)


if __name__ == "__main__":
    raise SystemExit(main())
