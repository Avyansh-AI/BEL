"""Serial live acceptance of the owner's exact model; no cloud or owner data.

Freeze cases before inference, retain failed answers, and never substitute a
handwritten skill for failed model generation. This is not the hour-long soak.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sight_core.brain_store import BrainStore
from sight_core.config import Config
from sight_core.forge import Forge, SkillGenerate, SkillManifest
from sight_core.memory import MemoryInput, MemoryService
from sight_core.models import OFFICIAL_GEMMA, OllamaProvider
from sight_core.routing import ModelRouter
from sight_core.store import Store

CASES = [
    ('exact_instruction', 'Return exactly SIGHT_READY and nothing else.', 'SIGHT_READY'),
    ('arithmetic', 'Reply only the number: 2 plus 2?', '4'),
    ('discount', 'A price of 250 is reduced by 20%, then 10% tax is added to the reduced price. Reply only the final number.', '220'),
    ('schedule', 'I have 35 minutes. Download takes 10 minutes, installation then takes 15 minutes, and testing then takes 12 minutes. Can all three finish in time? Reply only YES or NO.', 'NO'),
    ('non_entailment', 'Every red block is heavy. Some heavy blocks are wooden. Must some red blocks be wooden? Reply only YES or NO.', 'NO'),
    ('entailment', 'Every sparrow is a bird. Every bird is warm-blooded. Must every sparrow be warm-blooded? Reply only YES or NO.', 'YES'),
    ('python_instruction', 'Return only a Python expression that returns a sorted copy of items without changing items.', 'sorted(items)'),
    ('hindi_comprehension', '17 में 25 जोड़ने पर कितना होगा? केवल अंक लिखें।', '42'),
]
JSON_SCHEMA = {'type': 'object', 'properties': {'city': {'type': 'string'}, 'count': {'type': 'integer'}},
               'required': ['city', 'count'], 'additionalProperties': False}


async def run(destination, thinking=False):
    identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
    data = ROOT.parent / 'test-data' / ('official-acceptance-' + identifier)
    if destination.exists():
        raise ValueError('Use a new evidence path; prior results must be preserved')
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = {'started_utc': datetime.now(timezone.utc).isoformat(), 'model': OFFICIAL_GEMMA,
              'thinking': thinking, 'cloud_requests': 0, 'test_data': str(data), 'complete': False,
              'cases': CASES, 'json_schema': JSON_SCHEMA, 'rows': [],
              'grading': 'Exact visible answers (outer whitespace/backticks and one trailing period ignored). JSON equality. Tone screen is not a semantic quality proof.',
              'source_hashes': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT / 'sight_core').glob('*.py'))}}

    def save():
        destination.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    save()
    provider = OllamaProvider(Config(data, model=OFFICIAL_GEMMA, thinking=thinking))
    result['health'] = vars(await provider.health())
    if result['health']['status'] != 'ready':
        result['blocker'] = result['health']['message']
        save()
        print(json.dumps({'evidence': str(destination), 'blocker': result['blocker']}), flush=True)
        return 1
    with httpx.Client(base_url='http://127.0.0.1:11434', timeout=5, trust_env=False) as client:
        result['runtime'] = client.get('/api/version').json()
        result['tag'] = next(row for row in client.get('/api/tags').json()['models'] if row['name'] == OFFICIAL_GEMMA)
    router = ModelRouter(provider, Store(data), local_only=True)
    memory = MemoryService(BrainStore(data))
    forge = Forge(memory.store)

    async def measure(name, prompt, expected=None, *, schema=None, context=''):
        started = time.monotonic()
        answer = await router.generate(prompt, json_schema=schema, local_context=context)
        text = answer.get('say', '').strip().strip('`').strip().removesuffix('.')
        passed = answer.get('status') == 'ok' and answer.get('offline') is True
        if schema:
            try:
                passed = passed and json.loads(answer.get('say', '')) == expected
            except ValueError:
                passed = False
        elif expected is not None:
            passed = passed and text == expected
        else:
            passed = passed and bool(text) and not re.search(r'\b(?:bruh|no cap|fr fr|slay|yeet|rizz|lowkey|bestie|lol|lmao)\b|[\U0001F300-\U0001FAFF]', text, re.I)
        row = {'case': name, 'prompt': prompt, 'expected': expected, 'answer': answer,
               'seconds': round(time.monotonic() - started, 3), 'passed': bool(passed)}
        result['rows'].append(row)
        save()
        print(json.dumps({'case': name, 'status': answer.get('status'), 'passed': bool(passed), 'seconds': row['seconds']}), flush=True)

    for name, prompt, expected in CASES:
        await measure(name, prompt, expected)
    await measure('structured_json', 'Return JSON with city equal to Jaipur and count equal to 3. No additional fields.',
                  {'city': 'Jaipur', 'count': 3}, schema=JSON_SCHEMA)
    await measure('tone_screen', 'Explain in three sentences why a laptop slows down when RAM is full. Use professional language.')
    source = memory.put(MemoryInput(key='favorite_color', content='cobalt', source_uri='synthetic acceptance owner confirmation'))
    memory = MemoryService(BrainStore(data))  # Reopen actual persisted storage.
    prompt = 'What is my saved favorite_color? Reply only the color, or UNKNOWN if no saved color appears.'
    await measure('persisted_memory_recall', prompt, 'cobalt', context=memory.context(prompt)['text'])
    memory.put(MemoryInput(key='favorite_color', content='jade'), source['id'])
    await measure('corrected_memory_recall', prompt, 'jade', context=memory.context(prompt)['text'])
    memory.delete(source['id'])
    await measure('deleted_memory_not_recalled', prompt, 'UNKNOWN', context=memory.context(prompt)['text'])
    generated = await forge.generate(SkillGenerate(id='text.liveclean', description='Remove duplicate lines then sort the remaining lines alphabetically.',
        tests=[{'text': 'b\na\nb', 'expected': 'a\nb'}, {'text': 'z\nx\nz', 'expected': 'x\nz'}]), router)
    result['live_forge'] = generated
    passed = generated.get('state') == 'tested'
    if passed:
        first = forge.promote(generated['candidate_id'], generated['digest'])
        invoked = forge.invoke(first['id'], 'c\nb\nc')
        reused = forge.invoke(first['id'], 'e\nd\ne')
        second = forge.stage(SkillManifest(id=first['id'], title='Synthetic rollback target test', operations=[{'op':'upper'}],
            tests=[{'text':'a','expected':'A'}, {'text':'b','expected':'B'}]))
        forge.promote(second['candidate_id'], second['digest'])
        forge.rollback(first['id'], first['version'])
        rolled_back = forge.invoke(first['id'], 'c\na\nc')
        passed = invoked['text'] == 'b\nc' and reused['text'] == 'd\ne' and rolled_back['text'] == 'a\nc'
        result['forge_lifecycle'] = {'promoted': first, 'invoked': invoked, 'reused': reused, 'rollback_invoked': rolled_back,
            'authority': 'Explicit synthetic acceptance harness promotion of declarative text transforms only; no owner skill or executable code activated'}
    result['rows'].append({'case': 'live_declarative_forge_lifecycle', 'passed': passed})
    result['complete'] = True
    result['passed'] = all(row['passed'] for row in result['rows'])
    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps({'evidence': str(destination), 'passed': result['passed'],
                      'passed_cases': sum(row['passed'] for row in result['rows']), 'total_cases': len(result['rows'])}), flush=True)
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--thinking', action='store_true', help='Test thinking mode without changing saved owner settings')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.output.resolve(), thinking=args.thinking)))
