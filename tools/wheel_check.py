"""Validate a built wheel in a fresh venv, outside the source checkout.

Dependency installation may access a package index unless --wheelhouse is used.
All product calls use synthetic or empty temporary settings; no rack/API keys.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import venv

ROOT = Path(__file__).resolve().parents[1]


def _environment(root: Path) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}
                   and not key.startswith(("OPENAI_", "RTDS_", "RSCAD_", "PIP_"))}
    environment.update({"RTDS_AGENT_CONFIG": str(root / "config.json"), "PYTHONUTF8": "1",
                        "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
    (root / "config.json").write_text(json.dumps({
        "schema_version": 1, "data_dir": str(root / "data"), "rscad_home": None,
        "source_roots": [], "document_roots": [], "vector_store_id": "",
    }), encoding="utf-8")
    return environment


def check_wheel(wheel: Path, *, constraints: Path | None, wheelhouse: Path | None) -> dict:
    wheel = wheel.resolve(strict=True)
    if wheel.suffix != ".whl" or not wheel.is_file():
        raise ValueError("Supply one built wheel file")
    with tempfile.TemporaryDirectory(prefix="rtds-wheel-check-") as directory:
        root = Path(directory).resolve()
        if not root.is_relative_to(Path(tempfile.gettempdir()).resolve()) or root.is_relative_to(ROOT):
            raise ValueError("Wheel check must run in an isolated temporary directory outside the checkout")
        environment = _environment(root)
        installation = root / "venv"
        venv.EnvBuilder(with_pip=True).create(installation)
        python = installation / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        checks = []

        def run(label: str, arguments: list[str], *, json_output: bool = False, timeout: int = 90):
            print(f"wheel_check: {label}", file=sys.stderr, flush=True)
            completed = subprocess.run([str(python), "-I", *arguments], cwd=root, env=environment,
                                       capture_output=True, text=True, encoding="utf-8", timeout=timeout)
            if completed.returncode:
                # Do not emit inherited settings or secrets. Child output is from
                # isolated checks; retain only a bounded diagnostic on failure.
                details = (completed.stderr or completed.stdout)[-6000:]
                raise RuntimeError(f"{label} failed (exit {completed.returncode}): {details}")
            checks.append(label)
            return json.loads(completed.stdout) if json_output else completed.stdout.strip()

        arguments = ["-m", "pip", "install", "--disable-pip-version-check", "--no-input"]
        if constraints is not None:
            arguments.extend(["--constraint", str(constraints.resolve(strict=True))])
        if wheelhouse is not None:
            arguments.extend(["--no-index", "--find-links", str(wheelhouse.resolve(strict=True))])
        arguments.append(str(wheel))
        run("install wheel and declared dependencies", arguments, timeout=300)
        run("pip check", ["-m", "pip", "check"])
        probe = root / "installed_probe.py"
        probe.write_text('''from pathlib import Path
from importlib import metadata
import json, sys
import rtds_agent
from rtds_agent.integrity import verify_release
from rtds_agent.skill_catalog import list_skills
installation, checkout = map(lambda p: Path(p).resolve(), sys.argv[1:])
loaded = Path(rtds_agent.__file__).resolve()
assert loaded.is_relative_to(installation), "Imported outside isolated venv"
assert not loaded.is_relative_to(checkout), "Imported source checkout"
skills = list_skills()
assert len(skills["skills"]) == 6
print(json.dumps({"import_path_in_venv": loaded.relative_to(installation).as_posix(),
                  "version": metadata.version("rtds-rscad-agent"),
                  "integrity": verify_release(), "skill_count": len(skills["skills"])}))
''', encoding="utf-8")
        installed = run("installed import, release integrity and packaged resources",
                        [str(probe), str(installation), str(ROOT)], json_output=True)
        demo = run("installed synthetic demo", ["-m", "rtds_agent", "demo"], json_output=True)
        if demo.get("mode") != "synthetic_mock_only" or demo.get("live_calls_made") is not False:
            raise RuntimeError("Demo did not report a synthetic-only execution")
        dry_run = run("installed skills dry-run", ["-m", "rtds_agent", "skills", "export", "--destination",
                                                   str(root / "exported-skills"), "--dry-run"], json_output=True)
        if dry_run.get("files_written") != 0 or (root / "exported-skills").exists():
            raise RuntimeError("Skill dry-run wrote files")
        exported = run("installed skills export", ["-m", "rtds_agent", "skills", "export", "--destination",
                                                   str(root / "exported-skills")], json_output=True)
        if exported.get("status") != "exported" or len(exported.get("skills", [])) != 6:
            raise RuntimeError("Installed skill export is incomplete")
        smoke = root / "mcp_smoke.py"
        shutil.copyfile(ROOT / "tools" / "mcp_smoke.py", smoke)
        transport = run("installed real STDIO public contract", [str(smoke)], json_output=True, timeout=120)
        if transport.get("status") != "passed" or transport.get("live_rscad_calls") is not False:
            raise RuntimeError("STDIO check did not confirm its isolated no-live result")
        return {"status": "passed", "wheel": wheel.name,
                "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "checks": checks, "installed": installed, "stdio": transport,
                "skills_exported": len(exported["skills"]), "live_rscad_calls": False,
                "source_checkout_imported": False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--constraints", type=Path, default=ROOT / "constraints-windows-py312.txt")
    parser.add_argument("--wheelhouse", type=Path, help="Use only local dependency wheels (no package index)")
    args = parser.parse_args(argv)
    try:
        result = check_wheel(args.wheel, constraints=args.constraints, wheelhouse=args.wheelhouse)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc), "live_rscad_calls": False}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
