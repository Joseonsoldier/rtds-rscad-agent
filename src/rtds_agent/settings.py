"""Per-user settings. Importing this module never connects or writes files."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path


class ConfigurationError(ValueError):
    pass


def within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def user_data_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "rtds-agent"
    return Path.home() / ".local/share/rtds-agent"


def _absolute(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ConfigurationError(f"{label} must be an absolute path")
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    rscad_home: Path | None = None
    source_roots: tuple[Path, ...] = ()
    document_roots: tuple[Path, ...] = ()
    vector_store_id: str = ""
    expected_rscad_version: str = "2.7.3"

    @property
    def projects_root(self) -> Path:
        return self.data_dir / "projects"

    @property
    def definition_root(self) -> Path:
        return (self.rscad_home or self.data_dir / "unconfigured") / "MLIB/COMPONENTS"

    @property
    def sdk_root(self) -> Path:
        return (self.rscad_home or self.data_dir / "unconfigured") / "python/internal interpreter/Lib/site-packages"

    def validated(self) -> Settings:
        paths = [self.data_dir, *self.source_roots, *self.document_roots]
        if self.rscad_home:
            paths.append(self.rscad_home)
        if any(not p.is_absolute() for p in paths):
            raise ConfigurationError("All configured roots must be absolute")
        protected = [Path(__file__).resolve().parent, *self.source_roots, *self.document_roots]
        if self.rscad_home:
            protected.extend(self.rscad_home / name for name in ("BIN", "DOC", "MLIB", "Examples", "python", "FIRMWARE", "HDWR", "SECURITY"))
        if any(within(self.data_dir, p) or within(p, self.data_dir) for p in protected):
            raise ConfigurationError("Data directory must not overlap code, source, document or vendor directories")
        if self.expected_rscad_version != "2.7.3":
            raise ConfigurationError("This alpha supports RSCAD FX 2.7.3 only")
        if self.vector_store_id and not self.vector_store_id.startswith("vs_"):
            raise ConfigurationError("vector_store_id must start with vs_")
        return self

    def as_dict(self) -> dict:
        return {"schema_version": 1, "data_dir": str(self.data_dir),
                "rscad_home": str(self.rscad_home) if self.rscad_home else None,
                "source_roots": [str(p) for p in self.source_roots],
                "document_roots": [str(p) for p in self.document_roots],
                "vector_store_id": self.vector_store_id,
                "expected_rscad_version": self.expected_rscad_version}


def config_path() -> Path:
    return _absolute(os.environ.get("RTDS_AGENT_CONFIG") or str(user_data_dir() / "config.json"), "RTDS_AGENT_CONFIG")


def get_settings() -> Settings:
    path = config_path()
    value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    allowed = {"schema_version", "data_dir", "rscad_home", "source_roots", "document_roots", "vector_store_id", "expected_rscad_version"}
    if not isinstance(value, dict) or set(value) - allowed:
        raise ConfigurationError("Unknown configuration field; credentials belong only in environment variables")
    if value.get("schema_version", 1) != 1:
        raise ConfigurationError("Unsupported configuration version")
    home_value = os.environ.get("RSCAD_HOME") or value.get("rscad_home")
    home = _absolute(home_value, "rscad_home") if home_value else None
    sources = value.get("source_roots", [str(home / "Examples")] if home else [])
    docs = value.get("document_roots", [str(home / "DOC")] if home else [])
    return Settings(
        _absolute(os.environ.get("RTDS_AGENT_DATA_DIR") or value.get("data_dir") or user_data_dir(), "data_dir"),
        home, tuple(_absolute(p, "source_root") for p in sources),
        tuple(_absolute(p, "document_root") for p in docs),
        os.environ.get("OPENAI_VECTOR_STORE_ID", value.get("vector_store_id", "")),
        value.get("expected_rscad_version", "2.7.3"),
    ).validated()
