# Public alpha validation

Validation date: 2026-09-04. Target: Windows, Python 3.12.9, RSCAD FX 2.7.3 / vendor API 1.1.

## Local checks

- **85 synthetic unit/fake-driver tests** cover the retained Compile/Runtime core and public setup, local indexing, definition provenance, isolated edits, path boundaries, inactive policy, rack allow-lists, consumed grants and stale requests.
- A separate virtual environment was populated from the declared package dependencies. The built wheel was installed without importing from the source tree, and the suite, demo and actual STDIO smoke test were repeated.
- The STDIO client discovered **25 tools**, read an inactive default policy and confirmed a Compile request was rejected before live calls.
- A static audit of the installed vendor API passed **24 checks**. The audit parsed local source files; it did not import the vendor API, connect, query racks, compile or start Runtime.
- Source and distribution scans check for common key/token patterns, developer-specific bindings, binaries, proprietary project/document artifacts and generated local data. Wheel and sdist metadata are checked with Twine.
- The release manifest covers packaged code and schemas. It does not contain a personal authorization or certify a simulation.

## Reproduce

From a clean Python 3.12 environment:

```powershell
python -m pip install -c constraints-windows-py312.txt ".[dev]"
python -m unittest discover -s tests -v
python tools/mcp_smoke.py
rtds-agent demo
python tools/release_manifest.py --check
python tools/release_check.py
python -m build
python -m twine check dist/*
```

Inspect both built artifacts with `tools/release_check.py --artifacts` followed by their paths. For a package-install test, clear PYTHONPATH and install the wheel in a new environment before rerunning tests. The CI workflow runs the same synthetic checks on a GitHub-hosted Windows runner; this document records local checks, not a claim that remote CI has already run.

## Not covered

No actual Compile or Runtime was performed for this public alpha qualification. Cloud search/upload was not exercised against an account. No commercial document/SDK/model was included in the distribution. No other RSCAD or Python API version has been qualified. A virtual-environment installation test is not a test on every user's Windows configuration.

The synthetic tests ported from the prototype exclude three methods coupled to private experiment files. Public tests add fresh setup and workflow checks; the old prototype's larger regression count and scientific verdicts are not reused. An operator must qualify the portable release on an isolated licensed simulator, verify actual signal identities and control semantics, and review cleanup evidence before broader use.

The source scanner is a conservative pattern and file-type check, not a guarantee of absence of all secrets or a legal opinion about redistribution rights. Review every added source/fixture and the final Git diff before publishing.
