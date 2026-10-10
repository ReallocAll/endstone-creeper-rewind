# Development conventions

- Preserve the `creeperrewind` command and `/cr` alias, configuration keys, existing `snapshots.json` schema and Endstone `api_version = "0.11"` unless a change is explicitly required.
- The explosion event's `block_list` exposes borrowed Python wrappers over C++ blocks. Copy every required field to plain Python values **before** assigning `event.block_list`; never access an old block wrapper afterward. Test this invariant.
- The one-shot restore policy, drop-free damage, and non-air conflict checks are anti-duplication invariants. Changes require targeted regression tests.
- Do not assume generic `BlockData` can restore block-entity NBT. Keep complex block types protected until safe restoration is proven.
- Do not call server/world operations off the main thread. Unit tests do not replace a real Endstone/BDS integration test.
- Keep `requires-python >=3.11` and the CI matrix for Python 3.11–3.15 aligned; do not claim live Endstone/BDS compatibility based on Python-only tests.
- Use `uv`, Hatchling, Ruff, pytest. Build with `uv build --wheel` and inspect entry points and bundled `config.toml`.
- Never commit world data, player records, snapshots, secrets, virtual environments or build artifacts. Work through PRs when there is existing shared history; CI must not publish a Release or PyPI package.
