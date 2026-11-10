import pytest
from sight_core.bel import Bel
from sight_core.capabilities import Capabilities
from sight_core.store import Store
from sight_core.tools import LocalFiles
from sight_core.brain_store import BrainStore
from sight_core.memory import MemoryService


@pytest.fixture
def bel_setup(tmp_path):
    store = Store(tmp_path / "data")
    files = LocalFiles(tmp_path / "data/files")
    brain_store = BrainStore(tmp_path / "brain_data")
    memory = MemoryService(brain_store)
    bel = Bel(store, files, Capabilities(store, files), memory=memory)
    return bel, store, memory


def test_explicit_checkpoint_pre_compress(bel_setup):
    bel, store, memory = bel_setup
    bel.remember("req-1", "user", "Project Alpha goals: implement local memory sentry.")
    bel.remember("req-1", "assistant", "Acknowledged. Sentry registered.")
    
    seq = bel.checkpoint_pre_compress()
    assert seq is not None
    assert seq >= 2

    with store.connect() as db:
        saved_checkpoint = db.execute("SELECT value FROM bel_meta WHERE key='last_pre_compress_checkpoint'").fetchone()[0]
        assert "Project Alpha goals" in saved_checkpoint
        assert "[user]" in saved_checkpoint

    # Verify long-term memory episode was persisted
    episodes = memory.search("Project Alpha")
    assert len(episodes) > 0
    assert "local memory sentry" in episodes[0]["content"]


def test_watermark_triggers_automatic_checkpoint(bel_setup):
    bel, store, memory = bel_setup
    # Write 165 turns to trigger watermark >= 160
    for i in range(165):
        bel.remember(f"req-{i}", "user", f"Instruction number {i} regarding system configuration.")

    with store.connect() as db:
        row = db.execute("SELECT value FROM bel_meta WHERE key='last_pre_compress_seq'").fetchone()
        assert row is not None
        assert int(row[0]) > 0

        checkpoint = db.execute("SELECT value FROM bel_meta WHERE key='last_pre_compress_checkpoint'").fetchone()[0]
        assert "Instruction number" in checkpoint

    # Ensure events logged
    events = [e for e in store.events(50) if e["type"] == "bel.memory.pre_compressed"]
    assert len(events) >= 1
