"""Loopback-only Gemma adapter. Optional cloud policy lives in routing.py."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
import json
from typing import AsyncIterator, Protocol

import httpx
from .identity import SYSTEM_PROMPT

OFFICIAL_GEMMA = 'gemma4:e4b-it-qat'
# Exact owner-selected artifact, verified against all installed blobs. Official
# QAT metadata has no E4B display name; never infer identity from the tag alone.
OFFICIAL_GEMMA_DIGEST = 'ee665637121887cf3befff38abbb1be4ee117c7db867d97a67e29049ecd7e15f'
OFFICIAL_GEMMA_DIGESTS = {
    OFFICIAL_GEMMA_DIGEST,
    '65da2fa3cd9d19d86c7fe3c871b1050a4ac1fbbbd80e51be7789fa9fbfa9f908',
}
OFFICIAL_GEMMA_IDENTITY = {
    'general.architecture': 'gemma4', 'general.parameter_count': 7463013674,
    'gemma4.block_count': 42, 'gemma4.embedding_length': 2560,
}


@dataclass
class ModelStatus:
    status: str
    message: str
    model: str = ""
    configured: bool = False
    supports_tools: bool = False
    supports_vision: bool = False
    inference_verified: bool = False
    last_error: str = ""
    supports_thinking: bool = False


class Provider(Protocol):
    async def health(self) -> ModelStatus: ...
    async def generate(self, text: str) -> dict: ...
    def stream(self, text: str) -> AsyncIterator[str]: ...
    async def cancel(self): ...
    def limits(self) -> dict: ...
    def estimated_cost(self, text: str) -> dict: ...


class OllamaProvider:
    def __init__(self, config, transport=None):
        if config.ollama_url != "http://127.0.0.1:11434":
            raise ValueError("Only the approved loopback Ollama endpoint is supported")
        self.config = config
        self.transport = transport
        self.lock = asyncio.Lock()
        self.active: asyncio.Task | None = None
        self.last_error = ""
        self.inference_verified = False

    def discover_executable(self) -> str | None:
        import os, shutil, glob
        which = shutil.which("ollama")
        if which:
            return which
        if os.name == "nt":
            appdata = os.environ.get("LOCALAPPDATA", "")
            if appdata:
                prog = os.path.join(appdata, "Programs", "Ollama", "ollama.exe")
                if os.path.exists(prog):
                    return prog
            root = getattr(self.config, "data_dir", None)
            if root:
                for pat in (os.path.join(str(root), "**", "ollama.exe"), os.path.join(str(root.parent), "**", "ollama.exe")):
                    matches = glob.glob(pat, recursive=True)
                    if matches:
                        return matches[0]
        return None

    def resolve_models_directory(self) -> str | None:
        import os
        env_dir = os.environ.get("OLLAMA_MODELS")
        if env_dir and os.path.isdir(env_dir):
            return env_dir
        if os.name == "nt" and os.path.isdir(r"D:\Ollama Models"):
            return r"D:\Ollama Models"
        home_models = os.path.join(os.path.expanduser("~"), ".ollama", "models")
        if os.path.isdir(home_models):
            return home_models
        return None

    def _is_daemon_ready(self) -> bool:
        try:
            with httpx.Client(base_url=self.config.ollama_url, timeout=1.5, trust_env=False) as client:
                res = client.get("/api/version")
                return res.status_code == 200
        except Exception:
            return False

    def start_daemon_if_needed(self, wait_ready_sec: float = 0.0) -> bool:
        import os, subprocess, time
        if self._is_daemon_ready():
            return True
        exe = self.discover_executable()
        if not exe or not os.path.exists(exe):
            return False
        env = os.environ.copy()
        models_dir = self.resolve_models_directory()
        if models_dir:
            env["OLLAMA_MODELS"] = models_dir
        env.setdefault("OLLAMA_HOST", "127.0.0.1:11434")
        env.setdefault("OLLAMA_NO_CLOUD", "true")
        env.setdefault("CUDA_MODULE_LOADING", "EAGER")
        env.setdefault("OLLAMA_NUM_PARALLEL", "1")
        env.setdefault("OLLAMA_MAX_LOADED_MODELS", "1")
        env.setdefault("OLLAMA_CONTEXT_LENGTH", "4096")
        flags = 0x08000000 if os.name == "nt" else 0
        def _spawn(extra_env: dict[str, str] | None = None):
            child_env = env.copy()
            if extra_env:
                child_env.update(extra_env)
            return subprocess.Popen(
                [exe, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=child_env,
                creationflags=flags,
            )

        def _wait_ready(proc, timeout_sec: float) -> bool:
            deadline = time.monotonic() + timeout_sec
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    return self._is_daemon_ready()
                if self._is_daemon_ready():
                    return True
                time.sleep(0.5)
            return self._is_daemon_ready()

        try:
            proc = _spawn()
            if wait_ready_sec > 0:
                gpu_wait = min(wait_ready_sec, 12.0)
                if _wait_ready(proc, gpu_wait):
                    return True
                # If GPU discovery stalled, fall back cleanly to CPU mode
                if proc.poll() is None and os.environ.get("OLLAMA_LLM_LIBRARY") != "cpu":
                    try:
                        proc.terminate()
                        proc.wait(timeout=3)
                    except Exception:
                        pass
                    proc = _spawn({"OLLAMA_LLM_LIBRARY": "cpu", "CUDA_VISIBLE_DEVICES": "-1"})
                    remaining = max(5.0, wait_ready_sec - gpu_wait)
                    return _wait_ready(proc, remaining)
                return False
            return True
        except Exception:
            return False

    def client(self, timeout=None):
        return httpx.AsyncClient(base_url=self.config.ollama_url, timeout=timeout or self.config.model_timeout, trust_env=False, follow_redirects=False, transport=self.transport)

    def limits(self):
        return {"concurrent_inference": 1, "context_tokens": 4096, "output_tokens": 1536, "nonthinking_output_tokens": 512, "thinking": "automatic when supported; owner can disable", "model_file_budget_bytes": 6 * 1024**3, "vram_target_bytes": 8 * 1024**3, "vram_measured": False, "idle_unload": "5m", "batch_tokens": 128, "memory_mapped": True, "stream_mode": "buffered"}

    def estimated_cost(self, text):
        return {"api_usd": 0, "electricity_cost": "unknown"}

    async def request_json(self, client, method, path, **kwargs):
        # A local runtime is still an untrusted response source. Bound the raw
        # body and reject compression before decoding (including error bodies).
        async with client.stream(method, path, headers={'accept-encoding': 'identity'}, **kwargs) as response:
            if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                raise ValueError('Compressed runtime responses are unsupported')
            limit = 1024 * 1024
            if response.is_stream_consumed:
                body = response.content
                if len(body) > limit:raise ValueError('Runtime response exceeds 1 MiB')
            else:
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > limit:
                        raise ValueError('Runtime response exceeds 1 MiB')
                    body.extend(chunk)
            try:
                data = json.loads(body)
            except ValueError:
                if response.status_code == 200:raise
                data = {}
            return response.status_code, data

    async def health(self):
        status = await self._metadata_health()
        status.inference_verified = self.inference_verified
        status.last_error = self.last_error
        if status.status == "ready" and self.last_error:
            status.status = self.last_error
            status.message = "The last local inference failed: " + self.last_error + ". Retry after checking Ollama and available memory."
        return status

    async def _metadata_health(self):
        if not self.config.model:
            return ModelStatus("needs_model", "Select an installed Gemma 4 E4B Ollama tag with BEL_OLLAMA_MODEL; no model is configured.")
        try:
            async with asyncio.timeout(5), self.client(2) as client:
                code, response = await self.request_json(client, 'GET', '/api/tags')
                if code != 200:
                    return ModelStatus("offline", "The local Ollama runtime did not return a valid model list.", self.config.model)
                models = response.get("models", [])
                selected = next((m for m in models if m.get("name") == self.config.model), None)
                if not selected:
                    return ModelStatus("model_missing", "The configured model tag is not installed in Ollama.", self.config.model)
                details = selected.get("details", {})
                # Tag names alone do not prove model identity, quantization or memory use.
                if details.get("family") not in {"gemma4", "gemma4_e4b"} or not details.get("quantization_level"):
                    return ModelStatus("unsupported_model", "Ollama metadata does not establish a quantized Gemma 4 model; verify the requested E4B variant before use.", self.config.model)
                if not 0 < selected.get("size", 0) <= self.limits()["model_file_budget_bytes"]:
                    return ModelStatus("resource_limit", "Model artifact exceeds the conservative 6 GiB limit or has unknown size; target VRAM validation is required.", self.config.model)
                code, info = await self.request_json(client, 'POST', '/api/show', json={'model': self.config.model})
                if code != 200:
                    return ModelStatus("unsupported_model", "Ollama model metadata could not be verified.", self.config.model)
                model_info = info.get('model_info', {})
                if self.config.model == OFFICIAL_GEMMA:
                    verified = (selected.get('digest') in OFFICIAL_GEMMA_DIGESTS
                                and details.get('quantization_level') == 'Q4_0'
                                and all(model_info.get(key) == value for key,value in OFFICIAL_GEMMA_IDENTITY.items()))
                else:
                    verified = 'e4b' in ' '.join(str(v) for v in model_info.values()).lower()
                if not verified:
                    return ModelStatus("unsupported_model", "Model metadata does not confirm the E4B variant. No weights were loaded.", self.config.model)
                capabilities = info.get("capabilities", [])
                return ModelStatus("ready", "Installed quantized Gemma 4 E4B metadata verified; target VRAM measurement remains pending.", self.config.model, True, "tools" in capabilities, "vision" in capabilities, supports_thinking='thinking' in capabilities)
        except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
            return ModelStatus("offline", "Ollama is unavailable on 127.0.0.1:11434. Start the local runtime and verify the selected model.", self.config.model)

    async def generate_json(self, text, schema):
        return await self.generate(text, json_schema=schema)

    async def generate_chat(self, text):
        return await self.generate(text, recover_empty=True)

    async def generate(self, text, *, json_schema=None, recover_empty=False):
        # Reserve room for the system prompt, reasoning and answer in 4096 tokens.
        # Reject rather than silently dropping the beginning of the user's prompt.
        if len(text.encode("utf-8")) > 1280:
            return {"status": "context_limit", "say": "This request exceeds the conservative local context budget. Shorten it to at most 1280 UTF-8 bytes.", "offline": True}
        status = await self._metadata_health()
        if status.status != "ready":
            return {"status": status.status, "say": status.message, "offline": True, "model": status.model}
        if self.lock.locked():
            return {"status": "busy", "say": "Local inference is busy. One model request is allowed at a time.", "offline": True}
        async with self.lock:
            self.active = asyncio.current_task()
            try:
                async with asyncio.timeout(self.config.model_timeout), self.client() as client:
                    thinking = status.supports_thinking and self.config.thinking is not False
                    payload={"model": self.config.model, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}], "stream": False, "think": thinking, "keep_alive": "5m", "options": {"num_ctx": 4096, "num_predict": 1536 if thinking else 512, "num_batch": 128, "use_mmap": True, "temperature": 0.7, "top_p": 0.9, "top_k": 40, "repeat_penalty": 1.1}}
                    if self.config.model == OFFICIAL_GEMMA:
                        # The lower thinking temperature passed the recorded paired
                        # local evaluation. Preserve the owner's non-thinking mode.
                        payload['options'].update(temperature=0.2 if thinking else 1.0,top_p=0.95,top_k=64,repeat_penalty=1.0)
                    if json_schema is not None:payload['format']=json_schema
                    code, data = await self.request_json(client, 'POST', '/api/chat', json=payload)
                    first_usage = None
                    message = data.get('message', {})
                    if (recover_empty and json_schema is None and thinking and code == 200
                            and data.get('done') is True and data.get('done_reason') == 'stop'
                            and isinstance(message, dict) and isinstance(message.get('thinking'), str)
                            and message['thinking'].strip() and isinstance(message.get('content', ''), str)
                            and not message.get('content', '').strip()):
                        # The checkpoint sometimes ends in its thinking channel. Retry
                        # text chat once, with the same weights and shared time/lock budget.
                        # Durable jobs and Forge never enter this opt-in chat recovery.
                        first_usage = {k: data.get(k) for k in ('prompt_eval_count', 'eval_count')}
                        payload['think'] = False
                        payload['options']['num_predict'] = 512
                        if self.config.model == OFFICIAL_GEMMA:
                            payload['options']['temperature'] = 1.0
                        code, data = await self.request_json(client, 'POST', '/api/chat', json=payload)
                    if code != 200:
                        try:
                            reason = str(data.get("error", "")).lower()
                        except (ValueError, AttributeError):
                            reason = ""
                        self.last_error = "resource_limit" if any(word in reason for word in ("out of memory", "not enough", "insufficient memory", "more system memory", "than is available")) else "runtime_error" if any(word in reason for word in ("cuda", "runner", "terminated", "llama-server")) else "model_missing" if code == 404 else "model_error"
                        return {"status": self.last_error, "say": "Local inference failed: " + self.last_error + ". Check Ollama and available RAM/VRAM; no local action was performed.", "offline": True}
                    answer = data.get("message", {}).get("content")
                    if data.get('done_reason') == 'length':
                        self.last_error = 'output_limit'
                        return {'status':'output_limit','say':'The local model reached its output limit before finishing. Shorten or split this request. No automatic retry was sent.','offline':True,'model':self.config.model}
                    if not isinstance(answer, str) or not answer.strip():
                        self.last_error = "model_error"
                        return {"status": "model_error", "say": "The local runtime returned no usable response.", "offline": True}
                    if any(marker in answer for marker in ('<|channel>', '<channel|>', '<|turn>', '<turn|>')):
                        self.last_error = 'model_error'
                        return {'status':'model_error','say':'The model returned unparsed conversation markers. Verify its Ollama parser and template.','offline':True}
                    self.last_error = ""
                    self.inference_verified = True
                    usage = {'input_tokens': data.get('prompt_eval_count'), 'output_tokens': data.get('eval_count')}
                    recovery = {}
                    if first_usage is not None:
                        recovery = {'recovery': 'empty_thinking_answer', 'local_inference_requests': 2}
                        for target, source in (('input_tokens', 'prompt_eval_count'), ('output_tokens', 'eval_count')):
                            a, b = first_usage[source], usage[target]
                            usage[target] = a + b if type(a) is int and type(b) is int else None
                    return {"status": "ok", "say": answer[:32000], "offline": True, "model": self.config.model, "usage": usage, **recovery}
            except (httpx.HTTPError, TimeoutError, ValueError, TypeError, AttributeError):
                self.last_error = "offline"
                return {"status": "offline", "say": "Local inference was interrupted or timed out. No external model was contacted.", "offline": True}
            finally:
                self.active = None

    async def stream(self, text):
        # Buffered compatibility stream; native token streaming is explicitly not claimed.
        response = await self.generate(text)
        yield response["say"]

    async def cancel(self):
        if self.active:
            self.active.cancel()

    async def unload(self):
        if self.lock.locked():
            raise ValueError("Cancel the active request before unloading")
        if not self.config.model:
            raise ValueError("No model configured")
        async with asyncio.timeout(10), self.client(10) as client:
            code, _ = await self.request_json(client, 'POST', '/api/generate', json={"model": self.config.model, "keep_alive": 0})
            if code != 200:
                raise ValueError("Ollama did not acknowledge unloading")
        return {"ok": True, "status": "unload_acknowledged", "vram_verified": False}


def cloud_status():
    return [{"id": name, "status": "disabled", "configured": False, "billing_enabled": False, "reason": "Requires owner authorization, protected credentials, provider implementation and validation in the next phase."} for name in ("groq", "gemini", "openrouter", "chatgpt", "codex")]
