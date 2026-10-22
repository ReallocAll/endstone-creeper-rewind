import json

import pytest
from conftest import Block
from test_plugin import _explode


def test_partial_lookup_failure_consumes_once_and_restart_cannot_replay(setup_plugin, monkeypatch):
    a, b = Block(1, 64, 1), Block(2, 64, 1)
    plugin, server, dimension = setup_plugin(a, b)
    _explode(plugin, server, dimension, [a, b])
    record = plugin._records[0]
    original = dimension.get_block_at

    def lookup(x, y, z):
        if x == 2:
            raise RuntimeError('lookup fault')
        # The claim must already be on disk before the FIRST world lookup.
        assert json.loads(plugin._records_path.read_text())[0]['restored']
        return original(x, y, z)

    monkeypatch.setattr(dimension, 'get_block_at', lookup)
    assert plugin.restore_record(record) == (1, 0, 1)
    a.set_type('minecraft:air')
    assert plugin.restore_record(record) == (0, 0, 2)
    reloaded, _, _ = setup_plugin(a, b)
    reloaded._load_records()
    assert not reloaded._records
    assert a.type == 'minecraft:air'


def test_failed_claim_save_performs_no_world_writes(setup_plugin, monkeypatch):
    a = Block(1, 64, 1)
    plugin, server, dimension = setup_plugin(a)
    _explode(plugin, server, dimension, [a])
    record = plugin._records[0]
    monkeypatch.setattr(plugin, '_save_records', lambda: False)
    assert plugin.restore_record(record) == (0, 0, 1)
    assert a.type == 'minecraft:air' and record.restored
    # The old disk entitlement can survive, but no restored block was created.
    reloaded, _, _ = setup_plugin(a)
    reloaded._load_records()
    assert reloaded.restore_record(reloaded._records[0]) == (1, 0, 0)


def test_failed_final_compaction_cannot_resurrect_claim(setup_plugin, monkeypatch):
    a = Block(1, 64, 1)
    plugin, server, dimension = setup_plugin(a)
    _explode(plugin, server, dimension, [a])
    save = plugin._save_records
    calls = []

    def save_once():
        calls.append(True)
        return save() if len(calls) == 1 else False

    monkeypatch.setattr(plugin, '_save_records', save_once)
    assert plugin.restore_record(plugin._records[0]) == (1, 0, 0)
    assert json.loads(plugin._records_path.read_text())[0]['restored']
    a.set_type('minecraft:air')
    reloaded, _, _ = setup_plugin(a)
    reloaded._load_records()
    assert not reloaded._records


def test_interruption_after_claim_loses_unused_rights(setup_plugin, monkeypatch):
    a = Block(1, 64, 1)
    plugin, server, dimension = setup_plugin(a)
    _explode(plugin, server, dimension, [a])
    monkeypatch.setattr(dimension, 'get_block_at', lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        plugin.restore_record(plugin._records[0])
    reloaded, _, _ = setup_plugin(a)
    reloaded._load_records()
    assert not reloaded._records and a.type == 'minecraft:air'


def test_no_persistence_still_claims_before_write(setup_plugin):
    a = Block(1, 64, 1)
    plugin, server, dimension = setup_plugin(a)
    plugin.config['persist'] = False
    _explode(plugin, server, dimension, [a])
    record = plugin._records[0]
    assert plugin.restore_record(record) == (1, 0, 0)
    a.set_type('minecraft:air')
    assert plugin.restore_record(record) == (0, 0, 1)
    assert not plugin._records_path.exists()


def test_damage_fault_saves_acknowledged_progress(setup_plugin, monkeypatch):
    a, b = Block(1, 64, 1), Block(2, 64, 1)
    plugin, server, dimension = setup_plugin(a, b)
    monkeypatch.setattr(b, 'set_type', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('write fault')))
    _explode(plugin, server, dimension, [a, b])
    saved = json.loads(plugin._records_path.read_text())[0]['blocks']
    assert [block['damaged'] for block in saved] == [True, False]
    assert a.type == 'minecraft:air' and b.type == 'minecraft:stone'


def test_fsync_failure_refuses_claim(setup_plugin, monkeypatch):
    a = Block(1, 64, 1)
    plugin, server, dimension = setup_plugin(a)
    _explode(plugin, server, dimension, [a])
    monkeypatch.setattr('endstone_creeper_rewind.plugin.os.fsync',
                        lambda fd: (_ for _ in ()).throw(OSError('disk fault')))
    assert plugin.restore_record(plugin._records[0]) == (0, 0, 1)
    assert a.type == 'minecraft:air'


def test_damage_callback_is_not_replayed_after_partial_fault(setup_plugin, monkeypatch):
    a, b = Block(1, 64, 1), Block(2, 64, 1)
    plugin, server, dimension = setup_plugin(a, b)
    setter = b.set_type
    monkeypatch.setattr(b, 'set_type', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('fault')))
    _explode(plugin, server, dimension, [a, b])
    monkeypatch.setattr(b, 'set_type', setter)
    plugin.apply_simulated_damage(plugin._records[0].id)
    assert b.type == 'minecraft:stone'
