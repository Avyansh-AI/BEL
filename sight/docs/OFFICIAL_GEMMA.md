# Official Gemma selection

The owner changed the requested model to normal Gemma. The selected model is now **`gemma4:e4b-it-qat`**, the official quantized Gemma 4 E4B build in [Ollama's library](https://ollama.com/library/gemma4:e4b-it-qat). The previous uncensored model remains installed but is no longer selected by SIGHT or `Run-Gemma.ps1`.

The official download completed on 21 October 2026. The follow-up verified all six local manifest/config/model/projector/license/parameter blobs against their SHA-256 digests. This proves file integrity, not answer quality. [Installation evidence](../reports/gemma_official_install.json), [selection and integrity checks](../reports/official_model_switch.json).

**Local follow-up, 24 October; evidence reviewed 26 October: transport restored and a thinking profile qualified on bounded tests.** Ollama v0.40.9 has been restored from its verified official archive, and an actual metadata mismatch in SIGHT's model validator was repaired. Non-thinking mode subsequently failed arithmetic: 13/14 acceptance and 36/60 repeated reasoning cases. Thinking at temperature 1.0 scored 53/60; thinking at 0.2 scored 60/60 and then 14/14 through SIGHT's production adapter, including JSON, Hindi, persistent memory corrections/deletion and model-generated declarative Forge lifecycle. These finite tests do not guarantee general correctness. The owner explicitly approved enabling thinking for the current checkout. The 24 October source/dependencies/profile passed a 3,601.906-second stability test: 468/468 checks and 12/12 correct model answers. That run predates the subsequent browser worker repairs; see the [27 October follow-up](BROWSER_DIAGNOSTICS_20261027.md) for current-build verification. [Model evidence](LOCAL_MODEL_AUDIT_20261023.md), [profile qualification](DEPENDENCY_SECURITY_20261024.md).

At the earlier ZIP's publication, Ollama was absent and the loopback service unavailable; no official inference was claimed for that artifact. Earlier wrong answers and the earlier one-hour soak concern the uncensored model. They remain historical evidence, not results for the official model.

SIGHT now uses temperature **0.2 when thinking is enabled**, top-p 0.95, top-k 64 and repetition penalty 1.0. The saved configuration in this working checkout enables thinking; existing configurations that explicitly disable it remain respected. Context stays at 4,096 tokens, one request runs at a time, and thinking output is capped at 1,536 tokens within the existing 120-second deadline. Non-thinking mode retains temperature 1.0 and a 512-token cap, including the existing single empty-answer recovery for ordinary chat. No model weights or prompt-specific answer substitutions were introduced. The 60-case thinking benchmark had 3.398-second median and 8.578-second maximum latency; cold loading and other workloads can take longer.

`Run-Gemma.ps1 -Thinking` selects thinking in the standalone Ollama CLI. It does **not** apply SIGHT's system prompt or temperature profile; the qualified settings above belong to SIGHT's Python adapter. Use SIGHT to test that full profile.

From the build's top-level folder, after installing Python 3.12 and [Ollama for Windows](https://docs.ollama.com/windows):

```powershell
Push-Location .
try { .\sight\scripts\install.ps1 }
finally { Pop-Location }
ollama pull gemma4:e4b-it-qat
.\Start-Local-Runtime.ps1
$env:SIGHT_DATA_DIR = Join-Path $PWD.Path 'owner-data'
Push-Location sight
try { .\.venv\Scripts\python.exe -m sight_core.cli configure-model gemma4:e4b-it-qat }
finally { Pop-Location }
.\Start-SIGHT.ps1
```

Open SIGHT using `Open-SIGHT.ps1` in a second PowerShell window. Use `Run-Gemma.ps1` for a direct local chat. Model weights and Ollama are separate downloads and are not included in the GitHub source or handoff ZIP. No cloud provider is enabled by these steps.
