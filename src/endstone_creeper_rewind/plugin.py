import json
import time
from dataclasses import asdict, dataclass, field
from math import dist
from pathlib import Path
from typing import Any

from endstone import Player
from endstone.command import Command, CommandSender
from endstone.event import ActorExplodeEvent, EventPriority, event_handler
from endstone.plugin import Plugin

AIR_TYPES = {
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
}

# Endstone BlockData restores block type + block states, but not generic block-entity NBT.
# Keep these blocks out of the simulated Creeper damage so ordinary-player rollback cannot
# erase inventories/text/administrative data.
PROTECTED_EXACT = {
    "minecraft:barrel",
    "minecraft:bee_nest",
    "minecraft:beehive",
    "minecraft:beacon",
    "minecraft:blast_furnace",
    "minecraft:brewing_stand",
    "minecraft:chest",
    "minecraft:chiseled_bookshelf",
    "minecraft:crafter",
    "minecraft:command_block",
    "minecraft:campfire",
    "minecraft:chain_command_block",
    "minecraft:decorated_pot",
    "minecraft:dispenser",
    "minecraft:dropper",
    "minecraft:ender_chest",
    "minecraft:furnace",
    "minecraft:hopper",
    "minecraft:jigsaw",
    "minecraft:lectern",
    "minecraft:repeating_command_block",
    "minecraft:smoker",
    "minecraft:soul_campfire",
    "minecraft:suspicious_gravel",
    "minecraft:suspicious_sand",
    "minecraft:trial_spawner",
    "minecraft:vault",
    "minecraft:spawner",
    "minecraft:mob_spawner",
    "minecraft:structure_block",
    "minecraft:trapped_chest",
}

PROTECTED_MARKERS = (
    "shulker_box",
    "_sign",
    "_hanging_sign",
    "_banner",
    "_head",
    "_skull",
)


@dataclass(slots=True)
class BlockSnapshot:
    x: int
    y: int
    z: int
    type: str
    states: dict[str, bool | str | int]
    damaged: bool = False


@dataclass(slots=True)
class ExplosionSnapshot:
    id: int
    created_at: float
    dimension: str
    x: float
    y: float
    z: float
    blocks: list[BlockSnapshot] = field(default_factory=list)
    restored: bool = False

    @property
    def damaged_count(self) -> int:
        return sum(1 for block in self.blocks if block.damaged)


class CreeperListener:
    def __init__(self, plugin: "CreeperRewindPlugin") -> None:
        self.plugin = plugin

    @event_handler(priority=EventPriority.MONITOR, ignore_cancelled=True)
    def on_actor_explode(self, event: ActorExplodeEvent) -> None:
        # Only Creepers. TNT, beds, respawn anchors, End Crystals, etc. are deliberately ignored.
        if event.actor.type != "minecraft:creeper":
            return

        # IMPORTANT: event.block_list contains borrowed Python wrappers around C++ Block
        # objects owned by ActorExplodeEvent. Assigning to event.block_list destroys/replaces
        # those owned Block objects. Therefore every value we need must be copied to plain
        # Python data BEFORE the setter is called. Accessing a saved Block wrapper afterwards
        # is a use-after-free and can crash Endstone with EXCEPTION_ACCESS_VIOLATION.
        original = event.block_list
        if not original:
            return

        max_blocks = self.plugin.cfg_int("max-blocks-per-explosion", 256, minimum=1)
        snapshots: list[BlockSnapshot] = []

        for block in original:
            if len(snapshots) >= max_blocks:
                break

            block_type = block.type
            if self.plugin.is_protected_type(block_type):
                continue

            data = block.data
            snapshots.append(
                BlockSnapshot(
                    x=block.x,
                    y=block.y,
                    z=block.z,
                    type=data.type,
                    states=dict(data.block_states),
                )
            )

        # Only mutate the event after all borrowed Block wrappers have been consumed.
        # Clearing the vanilla destruction list prevents native block destruction/drops;
        # our controlled terrain damage runs one tick later.
        event.block_list = []

        if not snapshots:
            return

        loc = event.location
        snapshot = self.plugin.add_snapshot(
            dimension=event.actor.dimension.name,
            x=float(loc.x),
            y=float(loc.y),
            z=float(loc.z),
            blocks=snapshots,
        )

        # Run after the explosion event has returned. Before removing a block we verify that it
        # still equals the captured state, so another plugin/player changing it in the meantime
        # will not be overwritten.
        self.plugin.server.scheduler.run_task(
            self.plugin,
            lambda sid=snapshot.id: self.plugin.apply_simulated_damage(sid),
            delay=1,
        )


class CreeperRewindPlugin(Plugin):
    prefix = "CreeperRewind"
    api_version = "0.11"

    commands = {
        "creeperrewind": {
            "description": "恢复附近最近一次苦力怕造成的地形破坏",
            "usages": [
                "/creeperrewind",
                "/creeperrewind info",
                "/creeperrewind limits",
            ],
            "aliases": ["cr"],
            "permissions": ["creeperrewind.use"],
        }
    }

    permissions = {
        "creeperrewind.use": {
            "description": "允许普通玩家使用苦力怕破坏回溯",
            "default": True,
        }
    }

    def __init__(self) -> None:
        super().__init__()
        self._records: list[ExplosionSnapshot] = []
        self._next_id = 1
        self._cooldowns: dict[str, float] = {}

    def on_enable(self) -> None:
        self.save_default_config()
        self._load_records()
        self.register_events(CreeperListener(self))
        self.logger.info(
            "CreeperRewind enabled: ordinary players may restore nearby recent Creeper terrain damage."
        )

    def on_disable(self) -> None:
        self._save_records()

    # ---------- configuration ----------

    def cfg_int(self, key: str, default: int, *, minimum: int | None = None) -> int:
        try:
            value = int(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        if minimum is not None:
            value = max(minimum, value)
        return value

    def cfg_float(self, key: str, default: float, *, minimum: float | None = None) -> float:
        try:
            value = float(self.config.get(key, default))
        except (TypeError, ValueError):
            value = default
        if minimum is not None:
            value = max(minimum, value)
        return value

    def cfg_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        return value if isinstance(value, bool) else default

    # ---------- record storage ----------

    @property
    def _records_path(self) -> Path:
        return Path(self.data_folder) / "snapshots.json"

    def _load_records(self) -> None:
        if not self.cfg_bool("persist", True):
            return

        path = self._records_path
        if not path.exists():
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            records: list[ExplosionSnapshot] = []
            for item in raw:
                blocks = [BlockSnapshot(**block) for block in item.get("blocks", [])]
                records.append(
                    ExplosionSnapshot(
                        id=int(item["id"]),
                        created_at=float(item["created_at"]),
                        dimension=str(item["dimension"]),
                        x=float(item["x"]),
                        y=float(item["y"]),
                        z=float(item["z"]),
                        blocks=blocks,
                        restored=bool(item.get("restored", False)),
                    )
                )
            self._records = records
            self._next_id = max((record.id for record in records), default=0) + 1
            self.prune_records(save=False)
        except Exception as exc:
            self.logger.error(f"Failed to load snapshots.json: {exc}")
            self._records = []
            self._next_id = 1

    def _save_records(self) -> None:
        if not self.cfg_bool("persist", True):
            return

        try:
            path = self._records_path
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = [asdict(record) for record in self._records]
            temp = path.with_suffix(".json.tmp")
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            temp.replace(path)
        except Exception as exc:
            self.logger.error(f"Failed to save snapshots.json: {exc}")

    def prune_records(self, *, save: bool = True) -> None:
        now = time.time()
        max_age = self.cfg_int("max-age-seconds", 300, minimum=1)
        max_records = self.cfg_int("max-records", 128, minimum=1)

        self._records = [
            record
            for record in self._records
            if not record.restored and now - record.created_at <= max_age
        ]
        if len(self._records) > max_records:
            self._records = self._records[-max_records:]

        if save:
            self._save_records()

    def add_snapshot(
        self,
        *,
        dimension: str,
        x: float,
        y: float,
        z: float,
        blocks: list[BlockSnapshot],
    ) -> ExplosionSnapshot:
        self.prune_records(save=False)
        record = ExplosionSnapshot(
            id=self._next_id,
            created_at=time.time(),
            dimension=dimension,
            x=x,
            y=y,
            z=z,
            blocks=blocks,
        )
        self._next_id += 1
        self._records.append(record)
        self.prune_records(save=False)
        self._save_records()
        return record

    def get_record(self, record_id: int) -> ExplosionSnapshot | None:
        return next((record for record in self._records if record.id == record_id), None)

    # ---------- safety policy ----------

    @staticmethod
    def is_protected_type(block_type: str) -> bool:
        if block_type in PROTECTED_EXACT:
            return True
        return any(marker in block_type for marker in PROTECTED_MARKERS)

    @staticmethod
    def _same_block_state(block: Any, snapshot: BlockSnapshot) -> bool:
        if block.type != snapshot.type:
            return False
        try:
            data = block.data
            return data.type == snapshot.type and dict(data.block_states) == snapshot.states
        except Exception:
            return False

    # ---------- controlled terrain damage ----------

    def apply_simulated_damage(self, record_id: int) -> None:
        record = self.get_record(record_id)
        if record is None or record.restored:
            return

        dimension = self.server.level.get_dimension(record.dimension)
        if dimension is None:
            return

        changed = 0
        for snapshot in record.blocks:
            block = dimension.get_block_at(snapshot.x, snapshot.y, snapshot.z)

            # Do not erase a block that another plugin/player changed after the event.
            if not self._same_block_state(block, snapshot):
                continue

            block.set_type("minecraft:air", apply_physics=False)
            snapshot.damaged = True
            changed += 1

        if changed == 0:
            # Nothing was actually damaged; keeping the record would only confuse players.
            self._records = [r for r in self._records if r.id != record.id]
        self._save_records()

    # ---------- selection / rollback ----------

    def _nearest_record(self, player: Player) -> tuple[ExplosionSnapshot | None, float | None]:
        self.prune_records(save=False)

        dimension_name = player.dimension.name
        location = player.location
        radius = self.cfg_float("search-radius", 20.0, minimum=1.0)

        best: ExplosionSnapshot | None = None
        best_distance: float | None = None

        for record in self._records:
            if record.restored or record.dimension != dimension_name or record.damaged_count == 0:
                continue

            distance = dist(
                (float(location.x), float(location.y), float(location.z)),
                (record.x, record.y, record.z),
            )
            if distance > radius:
                continue
            if best_distance is None or distance < best_distance:
                best = record
                best_distance = distance

        return best, best_distance

    def restore_record(self, record: ExplosionSnapshot) -> tuple[int, int, int]:
        dimension = self.server.level.get_dimension(record.dimension)
        if dimension is None:
            return 0, 0, record.damaged_count

        restored = 0
        conflicts = 0
        failed = 0

        # Restore low to high. Physics is disabled deliberately; this is a snapshot repair,
        # not a normal player placement sequence.
        for snapshot in sorted(record.blocks, key=lambda block: (block.y, block.x, block.z)):
            if not snapshot.damaged:
                continue

            block = dimension.get_block_at(snapshot.x, snapshot.y, snapshot.z)

            # Never overwrite anything a player/plugin has placed since the explosion.
            if block.type not in AIR_TYPES:
                conflicts += 1
                continue

            try:
                data = self.server.create_block_data(snapshot.type, snapshot.states)
                block.set_data(data, apply_physics=False)
                restored += 1
            except Exception as exc:
                self.logger.warning(
                    f"Could not restore {snapshot.type} at "
                    f"{record.dimension} ({snapshot.x}, {snapshot.y}, {snapshot.z}): {exc}"
                )
                failed += 1

        # One-shot consumption is intentional. It prevents a player from restoring,
        # mining the blocks, and repeatedly reusing the same snapshot.
        record.restored = True
        self.prune_records(save=False)
        self._save_records()
        return restored, conflicts, failed

    # ---------- command ----------

    def on_command(self, sender: CommandSender, command: Command, args: list[str]) -> bool:
        if command.name != "creeperrewind":
            return True

        if not isinstance(sender, Player):
            sender.send_message("§c该命令只能由玩家使用。")
            return True

        sub = args[0].lower() if args else ""

        if sub == "limits":
            self._send_limits(sender)
            return True

        record, distance = self._nearest_record(sender)
        if record is None:
            sender.send_message("§e附近没有可回溯的近期苦力怕破坏记录。")
            return True

        age = max(0, int(time.time() - record.created_at))

        if sub == "info":
            sender.send_message(
                f"§a最近记录 #{record.id}：§f{record.damaged_count} 个方块，"
                f"{age} 秒前，距离 {distance:.1f} 格。"
            )
            sender.send_message("§7执行 §f/cr §7即可进行一次性安全回溯。")
            return True

        if sub not in ("", "restore", "undo"):
            sender.send_message("§e用法：/cr [info|limits]")
            return True

        now = time.time()
        cooldown = self.cfg_int("cooldown-seconds", 5, minimum=0)
        last = self._cooldowns.get(sender.name, 0.0)
        if cooldown and now - last < cooldown:
            remaining = max(1, int(cooldown - (now - last) + 0.999))
            sender.send_message(f"§e请等待 {remaining} 秒后再使用。")
            return True
        self._cooldowns[sender.name] = now

        restored, conflicts, failed = self.restore_record(record)
        sender.send_message(
            f"§a苦力怕破坏已回溯：§f恢复 {restored} 个，"
            f"跳过冲突 {conflicts} 个，失败 {failed} 个。"
        )

        return True

    def _send_limits(self, player: Player) -> None:
        max_age = self.cfg_int("max-age-seconds", 300, minimum=1)
        radius = self.cfg_float("search-radius", 20.0, minimum=1.0)
        max_blocks = self.cfg_int("max-blocks-per-explosion", 256, minimum=1)

        player.send_message("§6§lCreeper Rewind 使用规则与限制")
        player.send_message(
            "§7作用范围：§f只处理苦力怕爆炸造成的地形破坏；"
            "TNT、床、重生锚、末影水晶等爆炸不在回溯范围内。"
        )
        player.send_message(
            f"§7回溯条件：§f爆炸记录默认保留 {max_age} 秒，"
            f"使用者必须位于爆炸点 {radius:g} 格内；/cr 会选择附近最近的一条可用记录。"
        )
        player.send_message(
            f"§7破坏上限：§f单次最多接管 {max_blocks} 个普通方块；"
            "超过上限的部分会直接受到保护，不会被苦力怕炸掉。"
        )
        player.send_message(
            "§7掉落物：§f由插件接管并实际破坏的方块不会产生爆炸掉落物。"
            "这是为了避免“捡走掉落物后再回溯方块”的复制问题。"
        )
        player.send_message(
            "§7特殊方块：§f箱子、桶、熔炉、漏斗、潜影盒、告示牌、旗帜、头颅、"
            "蜂巢及部分管理/方块实体会直接受到保护，不参与破坏和回溯。"
        )
        player.send_message(
            "§7冲突保护：§f回溯时只恢复当前位置仍为空气的方块；"
            "如果玩家或其他插件后来放置了方块，该位置会被跳过，绝不会覆盖。"
        )
        player.send_message(
            "§7一次性：§f每条爆炸记录只能回溯一次。执行 /cr 后该记录即被消费；"
            "即使部分位置因冲突或异常被跳过，也不能再次使用同一记录。"
        )
        player.send_message(
            "§7恢复精度：§f普通方块会恢复类型和 block states；"
            "插件不尝试恢复任意方块实体 NBT，因此带库存、文字等复杂数据的方块会被预先保护。"
        )
        player.send_message(
            "§7物理更新：§f破坏与恢复均关闭方块物理更新以避免级联破坏；"
            "少数依赖邻居更新的方块可能需要后续自然方块更新后才完全刷新。"
        )
        player.send_message(
            "§7记录范围：§f只能恢复插件安装并运行期间记录到的苦力怕爆炸；"
            "安装前已经形成的坑无法恢复。未过期记录可按配置跨服务器重启保留。"
        )
        player.send_message(
            "§7领地兼容：§f如果 Territory 或其他保护插件已经取消爆炸，"
            "Creeper Rewind 不会重新制造这次地形破坏。"
        )
        player.send_message("§7命令：§f/cr §7回溯；§f/cr info §7查看附近记录；§f/cr limits §7查看本说明。")
