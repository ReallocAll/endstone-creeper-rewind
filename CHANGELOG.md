# Changelog

## 0.1.2

- Removed the automatic post-restore warning and `show-limit-warning` option.
- Expanded `/cr limits` into a detailed player-facing explanation of all safety and behavior constraints.

## 0.1.1

- Fixed a use-after-free in `ActorExplodeEvent` handling.
- All data from borrowed `Block` wrappers is now copied before assigning `event.block_list`.
- Added an explicit source comment documenting the pybind/C++ ownership constraint.

## 0.1.0

- Initial release.
