"""Official model sampling and direct launcher selection; no live inference."""
import asyncio
import json
import os
from pathlib import Path
import subprocess

import httpx
import pytest

from sight_core.config import Config
from sight_core.models import ModelStatus, OllamaProvider


@pytest.mark.parametrize('changed', [None, 'digest', 'quantization', 'general.parameter_count',
                                    'general.architecture', 'gemma4.block_count', 'gemma4.embedding_length', 'renamed_artifact'])
def test_official_runtime_metadata_identity_without_display_name(tmp_path, changed):
    # Captured from the actual restored Ollama 0.40.9 runtime, not invented metadata.
    captured = json.loads((Path(__file__).parent / 'fixtures/official_gemma_metadata.json').read_text())
    tag, info = captured['tag'], captured['metadata']
    if changed == 'digest':tag['digest'] = '0' * 64
    elif changed == 'quantization':tag['details']['quantization_level'] = 'Q8_0'
    elif changed == 'renamed_artifact':
        tag['digest'] = '0' * 64
        info['model_info']['general.name'] = 'Gemma 4 E4B'
    elif changed:info['model_info'][changed] = 'wrong identity'

    def respond(request):
        if request.url.path == '/api/tags':return httpx.Response(200, json={'models': [tag]})
        assert request.url.path == '/api/show', 'Metadata checks must not load the weights'
        return httpx.Response(200, json=info)

    provider = OllamaProvider(Config(tmp_path, model='gemma4:e4b-it-qat'), transport=httpx.MockTransport(respond))
    state = asyncio.run(provider.health())
    assert state.status == ('ready' if changed is None else 'unsupported_model')
    assert not state.inference_verified


@pytest.mark.parametrize('model,thinking,expected', [
    ('gemma4:e4b-it-qat', False, (1.0, .95, 64, 1.0)),
    ('gemma4:e4b-it-qat', True, (.2, .95, 64, 1.0)),
    ('gemma4:e4b-it-qat', None, (.2, .95, 64, 1.0)),
    ('sight-gemma4-e4b:uncensored', False, (.7, .9, 40, 1.1)),
])
def test_official_model_does_not_inherit_derivative_sampling(tmp_path, model, thinking, expected):
    sent = []
    def respond(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={'message': {'content': '4'}, 'done': True, 'done_reason': 'stop'})
    provider = OllamaProvider(Config(tmp_path, model=model, thinking=thinking), transport=httpx.MockTransport(respond))
    async def health():return ModelStatus('ready', 'fixture', supports_thinking=True)
    provider._metadata_health = health
    assert asyncio.run(provider.generate('2 plus 2'))['status'] == 'ok'
    options = sent[0]['options']
    assert tuple(options[k] for k in ('temperature', 'top_p', 'top_k', 'repeat_penalty')) == expected
    assert sent[0]['model'] == model and sent[0]['think'] is (thinking is not False)
    assert options['num_ctx'] == 4096 and options['num_predict'] == (512 if thinking is False else 1536)


def test_official_empty_answer_recovery_uses_nonthinking_profile(tmp_path):
    sent = []
    def respond(request):
        sent.append(json.loads(request.content))
        message = {'thinking': 'private synthetic reasoning', 'content': ''} if len(sent) == 1 else {'content': '4'}
        return httpx.Response(200, json={'message': message, 'done': True, 'done_reason': 'stop'})
    provider = OllamaProvider(Config(tmp_path, model='gemma4:e4b-it-qat', thinking=True),
                              transport=httpx.MockTransport(respond))
    async def health():return ModelStatus('ready', 'fixture', supports_thinking=True)
    provider._metadata_health = health
    answer = asyncio.run(provider.generate_chat('2 plus 2'))
    assert answer['say'] == '4' and answer['local_inference_requests'] == 2
    assert [(r['think'], r['options']['temperature'], r['options']['num_predict']) for r in sent] == [
        (True, .2, 1536), (False, 1.0, 512)]
    assert 'private synthetic reasoning' not in json.dumps(answer)


@pytest.mark.parametrize('thinking', [False, True])
def test_direct_helper_selects_normal_gemma(tmp_path, thinking):
    if os.name != 'nt':pytest.skip('Windows launcher')
    launcher = str(Path(__file__).resolve().parents[2]/'Run-Gemma.ps1').replace("'", "''")
    fake = tmp_path/'fake-ollama.ps1'
    fake.write_text("ConvertTo-Json -InputObject @($args) -Compress\nexit 0\n", encoding='utf-8')
    wrapper = tmp_path/'wrapper.ps1'
    wrapper.write_text("""$ErrorActionPreference='Stop'
function Invoke-RestMethod { return [pscustomobject]@{models=@([pscustomobject]@{name='gemma4:e4b-it-qat'})} }
& 'LAUNCHER' -OllamaExecutable 'FAKE' -Prompt '2 plus 2' THINKING
""".replace('LAUNCHER',launcher).replace('FAKE',str(fake).replace("'","''"))
       .replace('THINKING','-Thinking' if thinking else ''),encoding='utf-8')
    exe=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    result=subprocess.run([str(exe),'-NoProfile','-NonInteractive','-File',str(wrapper)],
                          capture_output=True,text=True,timeout=15,creationflags=0x08000000)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(result.stdout)==['run','gemma4:e4b-it-qat','--think=true' if thinking else '--think=false','2 plus 2']
