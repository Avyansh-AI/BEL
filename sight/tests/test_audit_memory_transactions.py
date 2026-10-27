"""Real SQLite interleavings and crash recovery for the October repository audit."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryInput, MemoryService


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def memory(tmp_path):
    return MemoryService(BrainStore(tmp_path / 'memory'), clock=lambda: 1_000_000)


def after_first_transaction(memory, monkeypatch, update):
    """Commit another writer at the first transaction boundary, without sleeps."""
    connect = memory.store.connect
    first = True

    @contextmanager
    def interleaved():
        nonlocal first
        with connect() as db:
            yield db
        if first:
            first = False
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(update).result(timeout=10)

    monkeypatch.setattr(memory.store, 'connect', interleaved)


@pytest.mark.parametrize('remote', [False, True])
def test_context_uses_one_revision_snapshot(memory, monkeypatch, remote):
    preference = memory.put(MemoryInput(key='direction', content='left', privacy_scope='cloud_allowed'))
    episode = memory.put(MemoryInput(store='episode', key='trip', content='journey left', privacy_scope='cloud_allowed'))
    writer = MemoryService(BrainStore(memory.store.root), clock=memory.clock)

    def update():
        with writer.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for row, content in ((preference, 'right'), (episode, 'journey right')):
                writer._put(db, MemoryInput(store=row['store'], key=row['key'], content=content,
                                            privacy_scope='cloud_allowed'), row['id'], writer.clock())

    after_first_transaction(memory, monkeypatch, update)
    context = memory.context('journey', remote=remote)
    assert 'direction: left' in context['text'] and 'trip: journey left' in context['text']
    assert {row['revision'] for row in context['sources']} == {1}
    current = memory.context('journey', remote=remote)
    assert 'direction: right' in current['text'] and 'trip: journey right' in current['text']
    assert {row['revision'] for row in current['sources']} == {2}


def test_purge_does_not_delete_a_concurrent_renewal(memory, monkeypatch):
    source = memory.put(MemoryInput(key='note', content='old quartz', ttl_days=1))
    summary = memory.compact([source['id']])
    memory.clock = lambda: 1_086_401
    writer = MemoryService(BrainStore(memory.store.root), clock=memory.clock)
    renewed = []

    def update():
        renewed.append(writer.put(MemoryInput(key='note', content='renewed jade', ttl_days=2)))

    after_first_transaction(memory, monkeypatch, update)
    memory.purge_expired()
    assert memory.export() == renewed
    assert memory.search('jade') == renewed
    assert not memory.search('quartz')
    assert memory.get(summary['id']) is None


def stored_rows(memory):
    with memory.store.connect() as db:
        return {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                for table in ('profiles', 'episodes', 'memory_fts', 'graph_edges', 'brain_events')}


@pytest.mark.parametrize('fault', ['exception', 'process_crash'])
def test_purge_failure_rolls_back_records_indexes_lineage_and_events(memory, fault):
    source = memory.put(MemoryInput(key='note', content='quartz', ttl_days=1))
    memory.compact([source['id']])
    memory.put(MemoryInput(store='episode', key='second', content='jade', ttl_days=1))
    memory.clock = lambda: 1_086_401
    before = stored_rows(memory)
    if fault == 'exception':
        # Failure occurs after the profile and its derived summary were deleted.
        with memory.store.connect() as db:
            db.execute("""CREATE TRIGGER reject_expiry BEFORE DELETE ON episodes
                          WHEN OLD.key='second'
                          BEGIN SELECT RAISE(ABORT, 'injected expiry failure'); END""")
        with pytest.raises(sqlite3.IntegrityError, match='injected expiry failure'):
            memory.purge_expired()
    else:
        code = '''import os, sys
from contextlib import contextmanager
from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryService
store = BrainStore(sys.argv[1])
connect = store.connect
@contextmanager
def fault_connection():
    with connect() as db:
        db.create_function('crash_now', 0, lambda: os._exit(89))
        db.execute("CREATE TEMP TRIGGER crash_expiry BEFORE DELETE ON episodes WHEN OLD.key='second' BEGIN SELECT crash_now(); END")
        yield db
store.connect = fault_connection
MemoryService(store, clock=lambda: 1086401).purge_expired()
'''
        result = subprocess.run([sys.executable, '-c', code, str(memory.store.root)], cwd=ROOT,
                                capture_output=True, text=True, timeout=15)
        assert result.returncode == 89, result.stderr
    assert stored_rows(memory) == before
