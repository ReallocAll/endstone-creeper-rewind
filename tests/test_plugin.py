import json
from types import SimpleNamespace

from conftest import Block, BorrowedBlock, Player
from endstone_creeper_rewind.plugin import BlockSnapshot, CreeperListener, ExplosionSnapshot


class ExplosionEvent:
    def __init__(self, dimension, blocks, type="minecraft:creeper"):
        self.actor = SimpleNamespace(type=type, dimension=dimension)
        self.location = SimpleNamespace(x=1, y=64, z=1)
        self._blocks = [BorrowedBlock(b) for b in blocks]

    @property
    def block_list(self):
        return list(self._blocks)

    @block_list.setter
    def block_list(self, new_value):
        for block in self._blocks:
            block.alive = False
        self._blocks = new_value


def _explode(plugin, server, dimension, blocks):
    event = ExplosionEvent(dimension, blocks)
    CreeperListener(plugin).on_actor_explode(event)
    server.scheduler.finish()
    return event


def test_borrowed_blocks_are_copied_before_list_is_replaced(setup_plugin):
    stone = Block(1, 64, 1, states={"a": 1})
    plugin, server, dimension = setup_plugin(stone)
    event = _explode(plugin, server, dimension, [stone])
    assert event.block_list == []
    assert stone.type == "minecraft:air"
    assert len(plugin._records) == 1
    assert plugin._records[0].blocks[0].states == {"a": 1}


def test_protected_blocks_remain_unmodified(setup_plugin):
    stone = Block(1, 64, 1)
    chest = Block(2, 64, 1, "minecraft:chest")
    plugin, server, dimension = setup_plugin(stone, chest)
    _explode(plugin, server, dimension, [stone, chest])
    assert stone.type == "minecraft:air"
    assert chest.type == "minecraft:chest"
    assert len(plugin._records[0].blocks) == 1


def test_restore_state_one_shot_and_conflict_protection(setup_plugin):
    a = Block(1, 64, 1, states={"facing": "east"})
    b = Block(2, 64, 1, "minecraft:dirt")
    plugin, server, dimension = setup_plugin(a, b)
    _explode(plugin, server, dimension, [a, b])
    assert (a.type, b.type) == ("minecraft:air", "minecraft:air")
    b.set_type("minecraft:oak_planks")
    restored, conflicts, errors = plugin.restore_record(plugin._records[0])
    assert (restored, conflicts, errors) == (1, 1, 0)
    assert a.type == "minecraft:stone" and a.states == {"facing": "east"}
    assert b.type == "minecraft:oak_planks"
    assert not plugin._records  # one-shot, no reusable resource


def test_only_creepers_are_recorded(setup_plugin):
    stone = Block(1, 64, 1)
    plugin, server, dimension = setup_plugin(stone)
    event = ExplosionEvent(dimension, [stone], type="minecraft:tnt")
    CreeperListener(plugin).on_actor_explode(event)
    assert event.block_list and stone.type == "minecraft:stone"
    assert not plugin._records and not server.scheduler.tasks


def test_cap_limits_damage_and_does_not_create_drops(setup_plugin):
    a = Block(1, 64, 1)
    b = Block(2, 64, 1)
    plugin, server, dimension = setup_plugin(a, b)
    plugin.config["max-blocks-per-explosion"] = 1
    _explode(plugin, server, dimension, [a, b])
    assert a.type == "minecraft:air"
    assert b.type == "minecraft:stone"
    assert plugin._records[0].damaged_count == 1


def test_persist_and_expiration(setup_plugin, monkeypatch):
    a = Block(1, 64, 1)
    plugin, server, dimension = setup_plugin(a)
    monkeypatch.setattr("endstone_creeper_rewind.plugin.time.time", lambda: 1000.0)
    _explode(plugin, server, dimension, [a])
    path = plugin._records_path
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1 and data[0]["blocks"][0]["damaged"] is True

    reloaded, _, _ = setup_plugin(a)
    reloaded._load_records()
    assert reloaded._records[0].id == 1
    assert reloaded._next_id == 2
    monkeypatch.setattr("endstone_creeper_rewind.plugin.time.time", lambda: 1400.0)
    reloaded.prune_records(save=False)
    assert reloaded._records == []


def test_nearest_record_and_command_limits(setup_plugin, monkeypatch):
    stone = Block(1, 64, 1)
    plugin, server, dimension = setup_plugin(stone)
    monkeypatch.setattr("endstone_creeper_rewind.plugin.time.time", lambda: 1000.0)
    _explode(plugin, server, dimension, [stone])
    player = Player("Alice", dimension, SimpleNamespace(x=2, y=64, z=1))
    cmd = SimpleNamespace(name="creeperrewind")
    assert plugin.on_command(player, cmd, ["info"])
    assert any("最近记录" in message for message in player.messages)
    plugin.on_command(player, cmd, ["limits"])
    assert any("掉落物" in message for message in player.messages)
    assert any("领地兼容" in message for message in player.messages)
    player.messages.clear()
    plugin.on_command(player, cmd, [])
    assert any("恢复 1 个" in message for message in player.messages)
    assert not any("限制：" in message for message in player.messages)


def test_snapshot_dataclass_schema():
    record = ExplosionSnapshot(1, 100, "overworld", 0, 60, 0,
                               blocks=[BlockSnapshot(0, 60, 0, "minecraft:stone", {"a": 2}, True)])
    assert record.damaged_count == 1
