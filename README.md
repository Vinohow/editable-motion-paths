# Editable Motion Paths

Edit motion paths directly in the 3D View, for objects and pose bones. Free and open source.

![Editable Motion Paths demo](docs/media/editable-motion-paths.gif)

> **Public prototype for Blender 5.2+.** Published on the Blender Extensions platform as
> [Vino Editable Motion Paths](https://extensions.blender.org/add-ons/vino-editable-motion-paths/).

![Status](https://img.shields.io/badge/status-prototype-orange)
![Blender](https://img.shields.io/badge/Blender-5.2%2B-5b5b5b)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)
![Quality](https://github.com/Vinohow/editable-motion-paths/actions/workflows/quality.yml/badge.svg)

Blender's motion paths show a trajectory, but you cannot edit them. Editable Motion Paths turns the path into an
editing tool: drag keys, reshape the curve with Bézier handles, and see the result immediately.

The add-on keeps Blender F-Curves as the source of truth. It does **not** create hidden Curve objects or Follow Path
constraints: everything you do is regular keyframe data, so Undo, the Graph Editor and Auto Key work as usual.

## Features

- **Objects and every moving bone**: FK, IK, root, hips, props... including Rigify rigs, in Object, Pose and Edit Mode.
- **Hover a path to add a key, like Loop Cut**: a point snaps to the nearest frame, a click adds the key without
  changing the motion.
- **Exact with animated parents and constraints**: the path matches the evaluated motion, and a dragged key lands
  where you drop it, even when the parent rotates, moves or follows a constraint.
- Drag Location keyframes directly on the path.
- Spatial Bézier handles to reshape the trajectory.
- `Alt + click`: corner ↔ smooth. `Alt + drag`: draw the tangent.
- Multi-selection with `Shift + click`.
- Axis (`X`/`Y`/`Z`) and plane (`Shift + X/Y/Z`) constraints, `Ctrl` to snap.
- Add a key at the current frame, delete the selected keys.
- Path of the head or of the tail of a bone.
- **Motion capture friendly**: on dense keys (a key per frame), drag a few control points and the keys around
  follow smoothly; every key stays visible and selectable.
- Direction arrows, past/future colors, frame dots (spacing), frame numbers, X-Ray.
- Colors, sizes and behavior are saved in the add-on preferences, so they follow you in every file.
- Interface in English, with a French translation picked automatically from Blender's language.

## Installation

### From Blender (recommended)

1. Open **Edit → Preferences → Get Extensions**.
2. Search for **Vino Editable Motion Paths** and click **Install**.

### From a release ZIP

1. Download `vino_editable_motion_paths-0.12.0.zip` from the
   [latest GitHub Release](https://github.com/Vinohow/editable-motion-paths/releases/latest).
2. In Blender, open **Edit → Preferences → Get Extensions**.
3. Open the menu in the top-right and choose **Install from Disk**, then select the ZIP.

See [Installation](docs/INSTALLATION.md) for development installs and troubleshooting.

## Quick start

1. Select an object, or a bone in Pose Mode.
2. Insert at least two **Location** keyframes.
3. Open **3D View → Sidebar (`N`) → Motion Path**.
4. Drag the keys of the path.

| Gesture | Action |
| --- | --- |
| Click a key | Select without moving |
| Drag a key | Move the keyframe in space |
| Drag a handle | Reshape the trajectory |
| `Alt + click` a key | Corner ↔ smooth |
| `Alt + drag` a key | Draw a manual tangent |
| `Shift + click` | Add/remove a key from the selection |
| Hover the path, click | Add a key at that frame, without changing the motion |
| `X`, `Y`, `Z` while dragging | Lock to an axis |
| `Shift + X/Y/Z` while dragging | Lock to a plane |
| `Ctrl` while dragging | Snap |

For the complete reference, see the [User Guide](docs/USER_GUIDE.md) and the
[Interaction Reference](docs/INTERACTIONS.md).

## Scope and limitations

- **Every moving object or bone gets a path**, whatever moves it: its own keys, FK rotations of its parents, the
  armature object, IK, constraints. Works with Rigify.
- **Dragging keys** works on objects and on bones animated in **Location** (IK controls, root, hips).
- **FK bones** are moved by rotations: their path is view only, because dragging it would need an IK solver. You can
  still click the path to add keys.
- **Drivers and NLA** on the edited channels are not edited.

Read [Known Limitations](docs/KNOWN_LIMITATIONS.md) before reporting an expected gap.

## Feedback wanted

This is a public prototype: the goal is to collect real-world feedback before proposing anything to Blender.

Useful bug reports include the Blender version, the operating system, the add-on version, the exact steps, and a
small `.blend` file when possible. A screen recording helps a lot for interaction bugs.

Use **Issues** for bugs and feature requests, and **Discussions** for workflow ideas.

## Documentation

- [Installation](docs/INSTALLATION.md)
- [User Guide](docs/USER_GUIDE.md)
- [Interaction Reference](docs/INTERACTIONS.md)
- [Known Limitations](docs/KNOWN_LIMITATIONS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Testing / QA](docs/TESTING.md)
- [Development](docs/DEVELOPMENT.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Release Process](docs/RELEASE.md)

## Development

```text
editable-motion-paths/
├── extension/                  # Installable extension source
│   ├── __init__.py
│   ├── translations.py
│   └── blender_manifest.toml
├── tests/                      # Headless tests (bpy module)
├── scripts/                    # Build script
└── docs/
```

Build the installable ZIP:

```bash
python scripts/build_extension.py
```

Run the automated tests (no Blender window needed):

```bash
pip install bpy==5.2.4
python tests/test_core.py
python tests/test_rigs.py
python tests/test_bones.py
```

## License

Editable Motion Paths is released under **GNU GPL v3 or later**. See [LICENSE](LICENSE).

## Disclaimer

This is an independent community project. It is not an official Blender feature and is not endorsed or supported by
the Blender Foundation.
