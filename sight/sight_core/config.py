from dataclasses import dataclass
from pathlib import Path
import os
import json
from .security import reject_links, safe_file
from .identity import APP_NAME, LEGACY_APP_NAME


def environment_value(name, default=None):
    """An explicit BEL value wins, including an empty model selection."""
    return os.environ.get("BEL_" + name, os.environ.get("SIGHT_" + name, default))


def default_data_directory():
    if os.name == "nt":
        parent = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        current, legacy = parent / APP_NAME, parent / LEGACY_APP_NAME
    else:
        parent = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        current, legacy = parent / APP_NAME.lower(), parent / LEGACY_APP_NAME.lower()
    # Keep the existing directory identity: ChatGPT's OS-vault namespace is path-bound.
    if legacy.exists() or legacy.is_symlink():
        return legacy
    return current


def read_local_model(data_dir):
    settings = safe_file(Path(data_dir) / "local-model.json")
    if not settings.is_file():
        return {}
    try:
        saved = json.loads(settings.read_text(encoding="utf-8"))
        if not isinstance(saved, dict) or not isinstance(saved.get("model", ""), str):
            raise ValueError()
        if saved.get("thinking") is not None and type(saved["thinking"]) is not bool:
            raise ValueError()
        return saved
    except (ValueError, OSError):
        raise ValueError("Invalid local-model.json; repair the saved model setting") from None


@dataclass(frozen=True)
class Config:
    data_dir: Path
    port: int = 8080
    model: str = ""  # Require an exact, owner-verified Ollama model tag.
    ollama_url: str = "http://127.0.0.1:11434"
    model_timeout: float = 120
    thinking: bool | None = None

    @classmethod
    def from_env(cls):
        port_key = "BEL_PORT" if "BEL_PORT" in os.environ else "SIGHT_PORT"
        try:
            port = int(environment_value("PORT", "8080"))
        except ValueError:
            raise ValueError(f"{port_key} must be an integer port between 1024 and 65535") from None
        if not 1024 <= port <= 65535:
            raise ValueError(f"{port_key} must be between 1024 and 65535")
        directory = environment_value("DATA_DIR", default_data_directory())
        if not str(directory).strip():
            raise ValueError("BEL_DATA_DIR or SIGHT_DATA_DIR must name a data directory")
        data_dir = reject_links(Path(directory).expanduser()).resolve()
        saved = read_local_model(data_dir)
        return cls(data_dir, port, environment_value("OLLAMA_MODEL", saved.get("model", "")), thinking=saved.get('thinking'))

    @property
    def origins(self):
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    @property
    def hosts(self):
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
