# Contributing

Thanks for helping test and improve Editable Motion Paths.

The project is currently a prototype, so high-quality bug reports and workflow feedback are as valuable as code contributions.

## Before opening an issue

1. Confirm you are using the latest release.
2. Check existing issues for the same behavior.
3. Read [Known Limitations](docs/KNOWN_LIMITATIONS.md).
4. Try reproducing the problem in a small new `.blend` file.

## Bug reports

Please include:

- Blender exact version/build;
- OS and version;
- GPU when the bug is visual/rendering-related;
- Editable Motion Paths version;
- minimal reproduction steps;
- expected behavior;
- actual behavior;
- Auto Key state;
- relevant path settings;
- screen recording for input/picking issues;
- crash log if Blender crashes;
- minimal `.blend` file if safe to share.

Do not upload confidential production scenes. Reduce the issue to a minimal reproduction whenever possible.

## Feature requests

Please describe the workflow problem first, then your proposed solution.

Helpful structure:

- **Workflow:** what are you trying to do?
- **Friction:** what is slow/confusing/impossible today?
- **Proposal:** what interaction would solve it?
- **Blender precedent:** does a similar interaction already exist in Blender?
- **Tradeoffs:** what could become ambiguous or slower?

## Pull requests

Keep pull requests focused. Avoid combining unrelated UX, rendering and animation-data changes in one PR.

Before submitting:

- run `python -m compileall -q extension scripts`;
- build the extension ZIP with `python scripts/build_extension.py`;
- install the generated ZIP in Blender 5.2+;
- run the relevant sections of [Testing](docs/TESTING.md);
- update `CHANGELOG.md` for user-visible changes;
- update docs if interaction or settings change.

## Coding principles

See [Development](docs/DEVELOPMENT.md) for the project runtime target and verification workflow.


- Blender F-Curves remain the source of truth.
- Avoid hidden scene objects used only as implementation state.
- Do not change the current scene frame merely to sample the path during normal viewport redraw.
- Do not keep fragile Blender RNA references across operations if the referenced data may be rebuilt.
- Prefer native Blender interaction conventions.
- Keep normal Blender selection/navigation usable.
- Avoid global keymap conflicts.
- Keep direct-edit feedback deterministic: click must not become a move until the drag threshold is passed.
- Cross-platform behavior matters: Windows, macOS/Metal and Linux should be considered.

## License

By contributing, you agree that your contribution is distributed under GPL-3.0-or-later, matching the project license.
