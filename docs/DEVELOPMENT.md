# Development

Editable Motion Paths currently targets **Blender 5.2**. Code should use the Blender 5.2 Python API rather than compatibility branches for older Blender versions unless support for another version is explicitly added and tested.

## Principles

- Blender animation data is the source of truth. The add-on must not maintain a second persistent animation model.
- Prefer Blender APIs and Python's standard library over new dependencies.
- Keep interaction predictable: ordinary Blender selection, navigation, Undo/Redo and keymaps must continue to work.
- Avoid broad exception handling. Handle expected Blender RNA/runtime failures explicitly and surface actionable errors where user input or I/O is involved. The two deliberate exceptions are the live timer (a timer that raises is removed by Blender) and the parent-space bake (a failure falls back to an approximate path and is reported in the panel).
- Do not keep fragile RNA references across modal updates when the underlying collection may change.
- Never call `scene.frame_set()` on the user's scene from drawing or live interaction code. Parent spaces are evaluated in a temporary scene (see `docs/ARCHITECTURE.md`).
- User-facing strings are written in English; add their translation to `extension/translations.py`.
- Keep the viewport responsive on long frame ranges by bounding sampling work.
- New behavior must include a reproducible test case in `docs/TESTING.md`.

## Verification before a pull request

Run:

```bash
python -m compileall -q extension scripts tests
python scripts/build_extension.py
pip install bpy==5.2.4
python tests/test_core.py
python tests/test_rigs.py
python tests/test_bones.py
```

Then install the generated archive from `dist/` in Blender 5.2 and execute the relevant manual tests from `docs/TESTING.md`.

The repository CI checks Python syntax, builds the extension archive and verifies ZIP integrity. The headless tests cover the logic; neither replaces interactive testing inside Blender (real mouse input, GPU drawing, gizmos).

## Blender API references

The implementation targets the Blender 5.2 API. In particular, Action Slot access uses Blender's `bpy_extras.anim_utils.animdata_get_channelbag_for_assigned_slot()` helper rather than legacy `Action.fcurves` compatibility paths.
