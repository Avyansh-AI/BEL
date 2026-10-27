"""Cross-skill forgetting and concurrent usage accounting use real workers/SQLite."""
from concurrent.futures import ThreadPoolExecutor
import threading

from sight_core.brain_store import BrainStore
from sight_core.forge import Forge, SkillManifest


def promote(forge, identifier):
    candidate = forge.stage(SkillManifest(id=identifier, title='Uppercase', operations=[{'op': 'upper'}],
        tests=[{'text': 'a', 'expected': 'A'}, {'text': 'b', 'expected': 'B'}]))
    return forge.promote(candidate['candidate_id'], candidate['digest'])


def test_forgetting_underscore_id_preserves_other_skill_provenance(tmp_path):
    forge = Forge(BrainStore(tmp_path / 'brain'))
    for identifier in ('text_a', 'textxa'):
        promote(forge, identifier)
        forge.invoke(identifier, 'hello', task='task-' + identifier)
    with forge.store.connect() as db:
        before = [tuple(r) for r in db.execute('SELECT * FROM graph_edges')
                  if 'skill:textxa:1' in tuple(r)]
    assert len(before) == 2
    assert forge.forget('text_a')['removed_versions'] == 1
    with forge.store.connect() as db:
        after = [tuple(r) for r in db.execute('SELECT * FROM graph_edges')
                 if 'skill:textxa:1' in tuple(r)]
    assert after == before
    assert forge.active('text_a') is None
    assert forge.invoke('textxa', 'still here')['text'] == 'STILL HERE'


def test_concurrent_invocations_count_one_first_use_and_one_reuse(tmp_path, monkeypatch):
    forge = Forge(BrainStore(tmp_path / 'brain'))
    promote(forge, 'text.upper')
    active = forge.active
    barrier = threading.Barrier(2)

    def together(*args):
        row = active(*args)
        barrier.wait(timeout=5)
        return row

    monkeypatch.setattr(forge, 'active', together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(forge.invoke, 'text.upper', text) for text in ('one', 'two')]
        assert [p.result(timeout=10)['text'] for p in pending] == ['ONE', 'TWO']
    row = forge.list()[0]
    assert (row['invoked'], row['reused'], row['failed']) == (2, 1, 0)
