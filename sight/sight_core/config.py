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
    local_stt: bool = False
    speech_engine: str = 'whisper_cpp'
    asr_directory: Path | None = None
    asr_model: str = 'small-q5_1'
    local_tts: bool = False

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
        speech = environment_value('LOCAL_STT', 'disabled')
        if speech not in {'disabled', 'windows', 'whisper_cpp'}:
            raise ValueError('BEL_LOCAL_STT must be disabled, windows or whisper_cpp')
        speech_engine = environment_value('SPEECH_ENGINE', 'whisper_cpp')
        asr_model = environment_value('ASR_MODEL', 'small-q5_1')
        if speech_engine not in {'windows', 'whisper_cpp'} or asr_model not in {'base-q5_1', 'small-q5_1'}:
            raise ValueError('Invalid offline speech engine or model selection')
        speech_tts = environment_value('LOCAL_TTS', 'windows' if os.name == 'nt' else 'disabled')
        if speech_tts not in {'disabled', 'windows'}:
            raise ValueError('BEL_LOCAL_TTS must be disabled or windows')
        asr_directory = environment_value('ASR_DIRECTORY')
        if asr_directory is not None:
            if not asr_directory.strip():
                raise ValueError('BEL_ASR_DIRECTORY must name an installation directory')
            asr_directory = reject_links(Path(asr_directory).expanduser()).resolve()
        return cls(data_dir, port, environment_value("OLLAMA_MODEL", saved.get("model", "")),
                   thinking=saved.get('thinking'), local_stt=speech != 'disabled',
                   speech_engine=speech_engine, asr_directory=asr_directory, asr_model=asr_model,
                   local_tts=speech_tts != 'disabled')

    @property
    def origins(self):
        return {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}

    @property
    def hosts(self):
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
