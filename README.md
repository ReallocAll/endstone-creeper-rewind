# Creeper Rewind

An Endstone plugin that allows ordinary players to undo recent Creeper terrain damage without enabling a general-purpose rollback command.

## Features

- Records block types and block states before a Creeper explosion.
- Prevents the original block destruction, then applies controlled, drop-free terrain damage one tick later.
- Restores only locations that are still air; never overwrites blocks placed after the explosion.
- Protects listed block-entity types (such as containers, signs and beehives) rather than attempting incomplete NBT restoration.
- Stores pending explosion snapshots in `snapshots.json`, with expiry and retention limits.
- Allows use by ordinary players (`creeperrewind.use` defaults to everyone).
- Skips explosions already cancelled by protection plugins.

## Requirements and installation

Endstone **0.11 API** and Python **3.10 or newer**. The plugin has no additional runtime Python dependencies. The package's `api_version` remains `0.11`; BDS-specific compatibility must be checked with the installed Endstone build.

Install the prebuilt `.whl` into the Bedrock server's `plugins/` directory and restart the server. Alternatively, build locally:

```sh
uv build --wheel
```

Copy `dist/endstone_creeper_rewind-0.1.2-py3-none-any.whl` to `plugins/`. On the first run, the plugin creates its `config.toml` in the plugin data directory.

## Commands

| Command | Effect |
| --- | --- |
| `/cr` (`/creeperrewind`) | Restore the nearest eligible explosion once. |
| `/cr info` | Show age, distance and affected block count of the nearest eligible record. |
| `/cr limits` | Display the full rules and limitations in-game. |

## Configuration

The bundled `config.toml` contains the following defaults:

| Key | Default | Description |
| --- | --- | --- |
| `max-age-seconds` | `300` | Maximum recovery age. |
| `search-radius` | `20.0` | Maximum player distance from an explosion. |
| `max-blocks-per-explosion` | `256` | Limit on captured terrain blocks; any overflow is protected. |
| `cooldown-seconds` | `5` | Per-player recovery cooldown. |
| `max-records` | `128` | Retained record limit. |
| `persist` | `true` | Persist pending records across restarts. |

The existing configuration keys and `snapshots.json` format are preserved in v0.1.2.

## Limitations

- **Only Creepers** are handled. TNT, End Crystals, beds and respawn anchors are excluded.
- Controlled terrain damage **does not drop block items**. This is intentional to prevent item duplication when blocks are restored.
- Complex blocks with inventories, text or other block-entity NBT are protected rather than destroyed and reconstructed. This is a conservative type-based policy, not a complete BDS block-entity registry.
- Restore skips every location no longer occupied by air; an explosion record is consumed even if some positions could not be restored.
- Blocks are changed with physics updates disabled; some neighboring blocks may not update until a later event.
- Only explosions observed while this plugin is running are recoverable. Expired records and already-existing craters cannot be recovered.
- If another plugin cancels the explosion, Creeper Rewind does not reapply the destruction.

## Development

```sh
uv sync --group dev
uv run ruff check .
uv run pytest -q
uv build --wheel
```

CI runs static checks, unit tests, wheel build, an isolated wheel installation and package/entry-point checks. The unit tests use Endstone test doubles; they **do not** constitute a live BDS integration test.

## License

GPL-3.0-only. This repository contains original plugin code and no vendored third-party code or media assets. The Endstone runtime is a separate Apache-2.0-licensed dependency.
