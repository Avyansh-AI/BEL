"""Predeclared, serial live comparison; never changes the owner's model/config.

All requests use real Ollama through the production adapter. Only temperature
and paired sampling seeds differ; there is no answer repair or automatic retry.
"""
import argparse
import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sight_core.config import Config
from sight_core.models import OFFICIAL_GEMMA, OllamaProvider, SYSTEM_PROMPT

CASES = [
    ('discount_regression', 'A price of 250 is reduced by 20%, then 10% tax is added to the reduced price. Reply only the final number.', '220', True),
    ('discount_holdout', 'An item costs 180. Apply a 25% discount, then add 8% tax to the discounted price. Reply only the final number.', '145.8', True),
    ('reverse_percentage', 'A price becomes 72 after a 20% increase. What was the original price? Reply only the number.', '60', True),
    ('basket', 'Buy 3 items at 17 each and 5 items at 9 each, then subtract a voucher of 10 from the total. Reply only the amount paid.', '86', True),
    ('rate', 'A vehicle travels 150 kilometres in 2.5 hours. Reply only its average speed in kilometres per hour as a number.', '60', True),
    ('ratio', 'Split 84 in the ratio 2:5. Reply only the larger share as a number.', '60', True),
    ('parallel_plan', 'Task A takes 10 minutes. B takes 15 minutes and C takes 12 minutes. Both B and C depend on A and can then run in parallel. Reply only the earliest total completion time in minutes.', '25', True),
    ('sequential_plan', 'A download takes 10 minutes, installation then takes 15 minutes, and testing then takes 12 minutes. Reply only their total duration in minutes.', '37', True),
    ('weighted_mean', 'Two groups have average scores of 60 and 90. They contain 3 and 2 people respectively. Reply only the combined average score.', '72', True),
    ('invalid_inference', 'Every red block is heavy. Some heavy blocks are wooden. Must some red blocks be wooden? Reply only YES or NO.', 'NO', False),
    ('valid_inference', 'Every sparrow is a bird. Every bird is warm-blooded. Must every sparrow be warm-blooded? Reply only YES or NO.', 'YES', False),
    ('instruction', 'Return exactly SIGHT_READY and nothing else.', 'SIGHT_READY', False),
]
SEEDS = [1, 7, 19, 31, 59]
PROFILES = [('official_default', 1.0), ('conservative_candidate', 0.2)]


class EvaluationProvider(OllamaProvider):
    async def request_json(self, client, method, path, **kwargs):
        if path == '/api/chat':
            kwargs['json']['options'].update(temperature=self.temperature, seed=self.seed)
        return await super().request_json(client, method, path, **kwargs)


async def run(destination, thinking=False, thinking_temperature=1.0):
    if destination.exists():
        raise ValueError('Use a new output path; failed results must remain preserved')
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = ROOT.parent / 'test-data' / ('sampling-' + uuid.uuid4().hex)
    provider = EvaluationProvider(Config(data, model=OFFICIAL_GEMMA, thinking=thinking))
    profiles = [('official_thinking' if thinking_temperature == 1.0 else 'conservative_thinking', thinking_temperature)] if thinking else PROFILES
    result = {'started_utc': datetime.now(timezone.utc).isoformat(), 'model': OFFICIAL_GEMMA,
              'system_prompt': SYSTEM_PROMPT, 'thinking': thinking, 'cloud_requests': 0,
              'cases': CASES, 'seeds': SEEDS, 'profiles': profiles, 'rows': [], 'complete': False,
              'selection_rule': 'Candidate must reduce total failures without a worse failure count on any case; thinking qualification requires all 60 visible answers correct within existing timeout/output limits. No automatic adoption; limited benchmark, not a general correctness guarantee.',
              'source_hashes': {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in sorted((ROOT / 'sight_core').glob('*.py'))}}

    def save():
        destination.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')

    save()
    for case, prompt, expected, numeric in CASES:
        for seed in SEEDS:
            for profile, temperature in profiles:
                provider.seed, provider.temperature = seed, temperature
                started = time.monotonic()
                answer = await provider.generate(prompt)
                visible = answer.get('say', '').strip().strip('`').strip().removesuffix('.')
                correct = visible == expected
                if numeric:
                    try:
                        correct = Decimal(visible) == Decimal(expected)
                    except InvalidOperation:
                        correct = False
                passed = answer.get('status') == 'ok' and answer.get('offline') is True and correct
                result['rows'].append({'case': case, 'seed': seed, 'profile': profile,
                                       'temperature': temperature, 'answer': answer,
                                       'seconds': round(time.monotonic() - started, 3), 'passed': passed})
                save()
        print(json.dumps({'case': case, 'failures': {name: sum(not r['passed'] for r in result['rows'] if r['case'] == case and r['profile'] == name) for name, _ in profiles}}), flush=True)
    result['complete'] = True
    result['summary'] = {name: {'passed': sum(r['passed'] for r in result['rows'] if r['profile'] == name),
                                'total': sum(r['profile'] == name for r in result['rows'])}
                         for name, _ in profiles}
    result['finished_utc'] = datetime.now(timezone.utc).isoformat()
    save()
    print(json.dumps({'evidence': str(destination), 'summary': result['summary']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--thinking', action='store_true', help='Evaluate supported thinking mode with the official sampling profile; saved owner configuration is unchanged')
    parser.add_argument('--thinking-temperature', type=float, choices=(1.0, 0.2), default=1.0,
                        help='Optional predeclared thinking-only sampling comparison')
    args = parser.parse_args()
    if not args.thinking and args.thinking_temperature != 1.0:
        parser.error('--thinking-temperature requires --thinking')
    asyncio.run(run(args.output.resolve(), thinking=args.thinking, thinking_temperature=args.thinking_temperature))
