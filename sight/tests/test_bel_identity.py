"""BEL branding/config compatibility; model transport is explicitly a fixture."""
import asyncio
import json
import os

import httpx
import pytest

from sight_core import identity
from sight_core.cli import main
from sight_core.config import Config
from sight_core.models import ModelStatus, OllamaProvider, SYSTEM_PROMPT


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    for prefix in ("BEL", "SIGHT"):
        for name in ("DATA_DIR", "PORT", "OLLAMA_MODEL"):
            monkeypatch.delenv(prefix + "_" + name, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "local"))


def test_new_install_uses_bel_without_creating_data(tmp_path):
    config = Config.from_env()
    expected = "BEL" if os.name == "nt" else "bel"
    assert config.data_dir == (tmp_path / "local" / expected).resolve()
    assert not config.data_dir.exists()
    assert config.model == "" and config.thinking is None


def test_existing_legacy_directory_is_reused_in_place(tmp_path):
    legacy = tmp_path / "local" / ("SIGHT" if os.name == "nt" else "sight")
    legacy.mkdir(parents=True)
    original = b'{"model":"gemma4:e4b-it-qat","thinking":true}\n'
    (legacy / "local-model.json").write_bytes(original)
    (tmp_path / "local" / ("BEL" if os.name == "nt" else "bel")).mkdir()
    config = Config.from_env()
    assert config.data_dir == legacy.resolve()
    assert config.model == "gemma4:e4b-it-qat" and config.thinking is True
    assert (legacy / "local-model.json").read_bytes() == original


def test_bel_environment_wins_and_preserves_saved_thinking(monkeypatch, tmp_path):
    selected = tmp_path / "selected"
    selected.mkdir()
    (selected / "local-model.json").write_text('{"model":"saved:tag","thinking":false}')
    monkeypatch.setenv("SIGHT_DATA_DIR", str(tmp_path / "unused"))
    monkeypatch.setenv("BEL_DATA_DIR", str(selected))
    monkeypatch.setenv("SIGHT_PORT", "8084")
    monkeypatch.setenv("BEL_PORT", "8094")
    monkeypatch.setenv("SIGHT_OLLAMA_MODEL", "legacy:tag")
    monkeypatch.setenv("BEL_OLLAMA_MODEL", "gemma4:e4b-it-qat")
    config = Config.from_env()
    assert config.data_dir == selected.resolve()
    assert config.port == 8094 and config.model == "gemma4:e4b-it-qat"
    assert config.thinking is False
    assert config.origins == {"http://localhost:8094", "http://127.0.0.1:8094"}
    assert not (tmp_path / "unused").exists()


def test_legacy_environment_and_explicit_empty_model_remain_supported(monkeypatch, tmp_path):
    monkeypatch.setenv("SIGHT_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SIGHT_PORT", "8084")
    monkeypatch.setenv("SIGHT_OLLAMA_MODEL", "legacy:tag")
    config = Config.from_env()
    assert (config.data_dir, config.port, config.model) == (tmp_path.resolve(), 8084, "legacy:tag")
    monkeypatch.setenv("BEL_OLLAMA_MODEL", "")
    assert Config.from_env().model == ""


@pytest.mark.parametrize("value", ["invalid", "", "1023", "65536"])
def test_invalid_bel_port_does_not_fall_back_to_legacy(monkeypatch, value):
    monkeypatch.setenv("SIGHT_PORT", "8084")
    monkeypatch.setenv("BEL_PORT", value)
    with pytest.raises(ValueError, match="BEL_PORT"):
        Config.from_env()


def test_empty_bel_directory_does_not_select_working_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("BEL_DATA_DIR", "")
    monkeypatch.setenv("SIGHT_DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError, match="data directory"):
        Config.from_env()


def test_model_request_uses_bel_identity_without_changing_verified_profile(tmp_path):
    sent = []
    def response(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "Ready, Avyansh."}, "done": True, "done_reason": "stop"})
    provider = OllamaProvider(Config(tmp_path, model="gemma4:e4b-it-qat", thinking=True),
                              transport=httpx.MockTransport(response))
    async def ready():
        return ModelStatus("ready", "test fixture", supports_thinking=True)
    provider._metadata_health = ready
    assert asyncio.run(provider.generate("Introduce yourself"))["status"] == "ok"
    system = sent[0]["messages"][0]
    assert system == {"role": "system", "content": SYSTEM_PROMPT}
    assert "BEL (Behavioral Executive Logic)" in system["content"]
    assert "Avyansh" in system["content"] and "explicit owner approval" in system["content"]
    assert "never authority" in system["content"] and "SIGHT" not in system["content"]
    assert sent[0]["model"] == "gemma4:e4b-it-qat" and sent[0]["think"] is True
    assert sent[0]["options"]["temperature"] == .2
    assert sent[0]["options"]["num_ctx"] == 4096


def test_identity_and_cli_are_bel_without_claiming_wake_enrollment(capsys):
    assert identity.identity() == {"name": "BEL", "full_name": "Behavioral Executive Logic",
                                   "default_owner": "Avyansh", "wake_phrase": "BEL"}
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    assert "usage: bel" in capsys.readouterr().out
