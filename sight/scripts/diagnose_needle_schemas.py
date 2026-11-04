"""Synthetic local inference comparison; proposals only, never registered execution."""
import asyncio
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sight_core.needle import NeedleRouter
from sight_core.bel import Application, Empty
from sight_core.tools import FileWrite


def compact(schema):
    if isinstance(schema, dict):
        return {key: compact(value) for key, value in schema.items() if key not in {'title', 'default'}}
    if isinstance(schema, list):
        return [compact(item) for item in schema]
    return schema


async def main(output, mode='schemas'):
    cases = [('Open Notepad', 'app.launch', Application, 'Open or focus Notepad or Calculator'),
             ('Open Calculator', 'app.launch', Application, 'Open or focus Notepad or Calculator'),
             ('List files in my private workspace', 'files.list', Empty, 'List filenames in BEL private workspace'),
             ('Create a file named greeting.txt containing Hello Avyansh', 'files.create', FileWrite,
              'Create a new text file in BEL private workspace')]
    rows = []
    router = NeedleRouter()
    if mode == 'descriptions':
        for description in ['Open an application.', 'Launch a desktop application by name.',
                            'Open the specified desktop application.', 'Open an app on the computer.',
                            'Launch applications including Notepad and Calculator.',
                            'Launch an application on Windows.',
                            'Open Notepad or Calculator.',
                            'Launch a Windows application.']:
            for prompt in ['Open Notepad', 'Open Calculator']:
                tools = [{'name': 'app.launch', 'description': description,
                          'parameters': compact(Application.model_json_schema())}]
                result = await router.propose(prompt, tools)
                rows.append({'prompt': prompt, 'variant': description, 'tools': tools, 'result': result})
                print(json.dumps({'prompt': prompt, 'variant': description, 'status': result['status'],
                                  'confidence': result['confidence'], 'reason': result['reason']}), flush=True)
        cases = []
    for prompt, name, schema, description in cases:
        for variant in ['original', 'compact', 'underscores', 'simple_description']:
            parameters = schema.model_json_schema()
            if variant != 'original':
                parameters = compact(parameters)
            if variant in {'underscores', 'simple_description'}:
                name_value = name.replace('.', '_')
            else:
                name_value = name
            if variant == 'simple_description':
                description_value = {'app.launch': 'Open an application.', 'files.list': 'List files.',
                                     'files.create': 'Create a text file with the given name and content.'}[name]
            else:
                description_value = description
            tools = [{'name': name_value, 'description': description_value, 'parameters': parameters}]
            result = await router.propose(prompt, tools)
            rows.append({'prompt': prompt, 'variant': variant, 'tools': tools, 'result': result})
            print(json.dumps({'prompt': prompt, 'variant': variant, 'status': result['status'],
                              'confidence': result['confidence'], 'reason': result['reason']}), flush=True)
    result = {'completed_utc': datetime.now(timezone.utc).isoformat(), 'kind': 'actual native inference schema experiment',
              'minimum_confidence': router.minimum_confidence, 'actions_executed': 0, 'rows': rows}
    with Path(output).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)


if __name__ == '__main__':
    asyncio.run(main(*sys.argv[1:]))
