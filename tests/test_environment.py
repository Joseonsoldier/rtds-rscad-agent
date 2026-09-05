"""Isolate every standard unittest discovery process before production imports.

Import this helper before rtds_agent modules. Credentials/configuration are never
inherited from an operator installation, even without an external CI launcher.
"""
import atexit
import os
from pathlib import Path
import tempfile

_TEMP = tempfile.TemporaryDirectory(prefix="rtds-isolated-test-process-")
_ROOT = Path(_TEMP.name)
atexit.register(_TEMP.cleanup)
os.environ.update({"RTDS_AGENT_CONFIG":str(_ROOT / "absent-config.json"),
                   "RTDS_AGENT_DATA_DIR":str(_ROOT / "data"), "RSCAD_HOME":"",
                   "OPENAI_API_KEY":"", "OPENAI_VECTOR_STORE_ID":"", "PYTHONUTF8":"1"})
