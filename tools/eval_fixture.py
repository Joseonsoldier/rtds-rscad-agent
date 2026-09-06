"""Authored, disposable inputs for model evaluations; no vendor code is executed."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_metadata(root: Path) -> dict:
    root = root.absolute()
    return {
        "schema_version": "1.0", "authored_synthetic": True, "root": str(root),
        "config": str(root / "config/config.json"), "data_dir": str(root / "data"),
        "source_root": str(root / "sources"), "documents": str(root / "documents"),
        "rscad_home": str(root / "synthetic_install"),
        "project": str(root / "sources/synthetic.rtfx"),
        "known_symbol": "rtds.authored.signal", "unknown_symbol": "rtds.authored.missing_signal",
        "component_id": 1, "context": "subsystem:0", "component_context": "subsystem:0", "subsystem": "subsystem:0",
        "signature": "signal(name: str) -> str",
        "component_type": "synthetic_gain", "parameter": "Gain", "stored_value": "1",
        "grounding_paths": [str(root / "documents/authored-guide.md")],
        "test_spec": {"test_id": "authored-inactive-policy", "execution_mode": "runtime_read_only_signal_capture",
            "runtime_required": True, "event": {"type": "none"},
            "runtime_controls": {"read_only_signal_capture": True, "runtime_parameter_writes": [],
                "hardware_io_changes": [], "rack_configuration_changes": [], "deployment_actions": []},
            "runtime_capture": {"warmup_seconds": 0, "minimum_samples_per_channel": 3},
            "measurement_channels": [{"channel_id": "v", "signal_path": "synthetic-only", "units": "V"}],
            "output_requirements": {"raw_numeric_data_required": True, "screenshot_only_pass_fail_forbidden": True}},
    }


def fixture_config(meta: dict) -> dict:
    return {"schema_version": 1, "data_dir": meta["data_dir"], "rscad_home": meta["rscad_home"],
            "source_roots": [meta["source_root"]], "document_roots": [meta["documents"]],
            "vector_store_id": "", "expected_rscad_version": "2.7.3"}


def create_fixture(root: Path) -> dict:
    """Create only a fresh root, with independent writable and protected directories."""
    root = root.absolute()
    for ancestor in (root, *root.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError("Fixture ancestors must not be links")
    root.mkdir(parents=True, exist_ok=False)
    meta = fixture_metadata(root)
    for name in ("data", "sources", "documents", "config", "synthetic_install/MLIB/COMPONENTS",
                 "synthetic_install/python/internal interpreter/Lib/site-packages/rtds"):
        (root / name).mkdir(parents=True, exist_ok=True)
    sdk = root / "synthetic_install/python/internal interpreter/Lib/site-packages/rtds"
    (sdk / "__init__.py").write_text('__version__ = "1.1"\nraise AssertionError("Authored fixture must never be imported")\n', encoding="utf-8")
    (sdk / "authored.py").write_text('def signal(name: str) -> str:\n    """Authored synthetic signal declaration; never a live API qualification."""\n    raise AssertionError("Do not execute")\n', encoding="utf-8")
    (root / "synthetic_install/MLIB/COMPONENTS/synthetic_gain").write_text(
        'PARAMETERS:\n Gain "Synthetic gain" "pu" REAL 1 0 10\nNODES:\n', encoding="utf-8")
    with zipfile.ZipFile(meta["project"], "w") as archive:
        archive.writestr(zipfile.ZipInfo("synthetic.dfx", (2020, 1, 1, 0, 0, 0)), "DRAFT 1\nSUBSYSTEM-START:\nCOMPONENT_TYPE=synthetic_gain\n0 0 0 0 1\nPARAMETERS-START:\nGain: 1\nPARAMETERS-END:\nUUID: 1\nSUBSYSTEM-END:\n")
        archive.writestr(zipfile.ZipInfo("authored.txt", (2020, 1, 1, 0, 0, 0)), "Authored fixture; no engineering qualification.\n")
    Path(meta["grounding_paths"][0]).write_text("Authored synthetic inactive-policy test. No live simulator operation is authorized or represented.\n", encoding="utf-8")
    Path(meta["config"]).write_text(json.dumps(fixture_config(meta), indent=2) + "\n", encoding="utf-8")
    (root / "fixture.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    hashes = {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*")) if p.is_file()}
    (root / "original_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    return enriched_metadata(meta, hashes)


def enriched_metadata(meta: dict, hashes: dict) -> dict:
    content = {key: value for key, value in hashes.items() if key not in {"config/config.json", "fixture.json"}}
    # Profile and authored input bytes are stable across independent absolute roots.
    profile = {"schema_version": "1.0", "content_hashes": content, "test_spec": meta["test_spec"]}
    return {**meta, "project_path": meta["project"], "source_sha256": hashes["sources/synthetic.rtfx"],
            "sdk_sha256": hashes["synthetic_install/python/internal interpreter/Lib/site-packages/rtds/authored.py"],
            "fixture_sha256": hashlib.sha256(json.dumps(profile, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
            "original_hashes": hashes, "manifest": str(Path(meta["root"]) / "original_hashes.json"),
            "manifest_sha256": digest(Path(meta["root"]) / "original_hashes.json")}


def load_fixture(root: Path) -> dict:
    root = root.absolute()
    for path in (root, *root.parents, *root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Fixture must not contain links")
        if path.is_file() and path.stat().st_nlink != 1:
            raise ValueError("Fixture must not contain hard links")
    meta = fixture_metadata(root)
    if json.loads((root / "fixture.json").read_text(encoding="utf-8")) != meta:
        raise ValueError("Unexpected fixture metadata")
    if json.loads(Path(meta["config"]).read_text(encoding="utf-8")) != fixture_config(meta):
        raise ValueError("Unexpected fixture configuration")
    hashes = json.loads((root / "original_hashes.json").read_text(encoding="utf-8"))
    expected = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
                and not p.is_relative_to(root / "data") and p.name != "original_hashes.json"}
    if not isinstance(hashes, dict) or set(hashes) != expected:
        raise ValueError("Unexpected original file manifest")
    for relative, sha in hashes.items():
        if digest(root / relative) != sha:
            raise ValueError("Original fixture hash mismatch")
    return enriched_metadata(meta, hashes)


def verify_fixture(meta: dict) -> bool:
    """Revalidate every protected file against the caller's original metadata."""
    current = load_fixture(Path(meta["root"]))
    for key in ("original_hashes", "manifest_sha256", "fixture_sha256", "source_sha256", "sdk_sha256"):
        if current[key] != meta[key]:
            raise ValueError("Fixture originals changed since creation")
    return True
