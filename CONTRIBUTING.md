# Contributing

Use Python 3.12 and install `.[dev]` in a separate virtual environment. Run the synthetic unittest suite, local STDIO smoke test and source/artifact release checks. Keep generated settings, indexes, model files, logs and credentials outside the repository.

Do not submit RTDS/vendor software, documentation, MLIB definitions or examples without separately established redistribution permission. Tests should generate their own minimal synthetic fixtures. Do not add default-active policies, relax exact target/hash/readback/restore checks, or connect public CI to a real rack.

Explain a changed behavior, why it is needed and what was actually tested. Separate parsing/provenance, execution success and engineering acceptance. A previous result on one model or RSCAD release is not universal verification. Version/API changes require new integration qualification; do not claim support by only editing a version string.

Review changes before refreshing `release_manifest.json`; then rerun tests and inspect the checksum diff. The release workflow must use public source/fixtures only and no privileged lab credentials.
