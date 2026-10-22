## 0.1.3 (2026-10-22)

Consume and persist a restoration claim before world writes. Refuse restoration on failed or uncertain saves; interrupted claims are never replayed. Persist partial damage progress, avoid duplicate callbacks, and count per-block failures. Interrupted claims can lose unfinished repair rights.

# Changelog

## Unreleased

- Drop Python 3.10 (EOL) and add Python 3.15 to the tested Python versions.
- Raise the package minimum to Python 3.11 and update the Ruff target accordingly.

## 0.1.2

- Removed the automatic post-restore warning and `show-limit-warning` option.
- Expanded `/cr limits` into a detailed player-facing explanation of all safety and behavior constraints.

## 0.1.1

- Fixed a use-after-free in `ActorExplodeEvent` handling.
- All data from borrowed `Block` wrappers is now copied before assigning `event.block_list`.
- Added an explicit source comment documenting the pybind/C++ ownership constraint.

## 0.1.0

- Initial release.
