"""Minimal Endstone doubles; no Bedrock server is needed to run unit tests."""

import logging
import sys
import types
from pathlib import Path

import pytest


class CommandSender:
    def __init__(self):
        self.messages = []

    def send_message(self, value):
        self.messages.append(value)


class Player(CommandSender):
    def __init__(self, name, dimension, location):
        super().__init__()
        self.name = name
        self.dimension = dimension
        self.location = location


class Plugin:
    def __init__(self):
        self.config = {}
        self.server = None
        self.data_folder = None
        self.logger = logging.getLogger("test-creeper-rewind")

    def save_default_config(self):
        pass

    def register_events(self, listener):
        self.listener = listener


class EventPriority:
    MONITOR = object()


def event_handler(*args, **kwargs):
    def apply(func):
        return func

    return apply


endstone = types.ModuleType("endstone")
endstone.__path__ = []
endstone.Player = Player
command = types.ModuleType("endstone.command")
command.CommandSender = CommandSender
command.Command = type("Command", (), {})
event = types.ModuleType("endstone.event")
event.ActorExplodeEvent = type("ActorExplodeEvent", (), {})
event.EventPriority = EventPriority
event.event_handler = event_handler
plugin = types.ModuleType("endstone.plugin")
plugin.Plugin = Plugin
sys.modules.update({
    "endstone": endstone,
    "endstone.command": command,
    "endstone.event": event,
    "endstone.plugin": plugin,
})


class Block:
    def __init__(self, x, y, z, type="minecraft:stone", states=None):
        self.x, self.y, self.z = x, y, z
        self.type = type
        self.states = dict(states or {})
        self.alive = True

    @property
    def data(self):
        return types.SimpleNamespace(type=self.type, block_states=dict(self.states))

    def set_type(self, type, apply_physics=True):
        self.type = type
        self.states = {}

    def set_data(self, data, apply_physics=True):
        self.type = data.type
        self.states = dict(data.block_states)


class BorrowedBlock:
    """Simulates an event-owned C++ Block exposed via a borrowed Python pointer."""

    def __init__(self, world_block):
        self._block = world_block
        self.alive = True

    def __getattr__(self, name):
        if not self.alive:
            raise ReferenceError("borrowed C++ Block already destroyed")
        return getattr(self._block, name)


class Dimension:
    name = "overworld"

    def __init__(self, blocks):
        self.blocks = {(b.x, b.y, b.z): b for b in blocks}

    def get_block_at(self, x, y, z):
        return self.blocks[(x, y, z)]


class Scheduler:
    def __init__(self):
        self.tasks = []

    def run_task(self, plugin, callback, delay):
        assert delay == 1
        self.tasks.append(callback)

    def finish(self):
        for task in self.tasks[:]:
            task()
        self.tasks.clear()


class Server:
    def __init__(self, dimension):
        self.dimension = dimension
        self.scheduler = Scheduler()
        self.level = types.SimpleNamespace(get_dimension=lambda name: dimension if name == dimension.name else None)

    def create_block_data(self, type, states):
        return types.SimpleNamespace(type=type, block_states=dict(states))


@pytest.fixture
def setup_plugin(tmp_path: Path):
    from endstone_creeper_rewind.plugin import CreeperRewindPlugin

    def make(*blocks):
        dimension = Dimension(list(blocks))
        server = Server(dimension)
        instance = CreeperRewindPlugin()
        instance.server = server
        instance.data_folder = str(tmp_path)
        return instance, server, dimension

    return make
