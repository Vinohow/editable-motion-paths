# Editable Motion Paths

Interactive editable motion paths for Blender 5.2+.

![Editable Motion Paths demo](docs/media/editable-motion-paths.gif)

> **Prototype / public beta for Blender 5.2+** - edit object location motion paths directly in the 3D View.

![Status](https://img.shields.io/badge/status-prototype-orange)
![Blender](https://img.shields.io/badge/Blender-5.2%2B-5b5b5b)
![License](https://img.shields.io/badge/license-GPL--3.0--or--later-blue)
![Quality](https://github.com/Vinohow/editable-motion-paths/actions/workflows/quality.yml/badge.svg)

Editable Motion Paths is an experimental Blender add-on that turns motion paths from a mostly visual aid into an interactive spatial editing tool.

The add-on keeps Blender F-Curves as the source of truth. It does **not** create hidden Curve objects or Follow Path constraints.

## Demo

Demo media is published with GitHub Releases so the repository never references a missing asset.

## Current features

- Direct manipulation of location keyframes in the 3D View.
- Spatial Bézier handles for reshaping the trajectory.
- `Alt + click` on a path key: corner ↔ smooth.
- `Alt + drag` on a path key: manually draw/size a smooth tangent.
- Multi-selection with `Shift + click`.
- Axis constraints with `X`, `Y`, `Z`.
- Plane constraints with `Shift + X/Y/Z`.
- Optional Global or Local constraint space.
- Snap while dragging with `Ctrl`.
- Direction arrows along the motion path.
- Past/future path differentiation around the current frame.
- Optional frame labels and key-type badges.
- X-Ray mode.
- Configurable colors, key size, handle size, line width and picking tolerance.
- Display the active object path or paths for selected objects.
- Configurable time range and adaptive sampling.
- HiDPI/Retina-friendly screen-space key and handle rendering.
- Undo/Redo-aware cache invalidation.

## Installation

### Recommended: install the release ZIP

1. Download `editable_motion_paths-0.9.4.zip` from the latest GitHub Release.
2. In Blender, open **Edit → Preferences → Get Extensions**.
3. Open the menu in the top-right and choose **Install from Disk**.
4. Select the ZIP.
5. Enable **Editable Motion Paths** if Blender does not enable it automatically.
6. In the 3D View, press `N` and open the **Motion Path** tab.

Current manifest target: **Blender 5.2.0+**.

See [Installation](docs/INSTALLATION.md) for development installs and troubleshooting.

## Quick start

1. Select an object.
2. Insert at least two **Location** keyframes.
3. Open **3D View → Sidebar (`N`) → Motion Path**.
4. Make sure **Trajectory** and **Editable** are enabled.
5. Interact directly with the path.

| Gesture                   | Action                              |
| ------------------------- | ----------------------------------- |
| Click key                 | Select without moving               |
| Drag key                  | Move spatial keyframe               |
| Click selected key        | Show handles                        |
| Drag handle               | Edit spatial tangent                |
| `Alt + click` key         | Corner ↔ smooth                     |
| `Alt + drag` key          | Draw a manual aligned tangent       |
| `Shift + click`           | Add/remove key from multi-selection |
| `X`, `Y`, `Z` during drag | Constrain to axis                   |
| `Shift + X/Y/Z`           | Constrain to complementary plane    |
| `Ctrl` during drag        | Snap using configured increment     |

For the complete behavior reference, see [User Guide](docs/USER_GUIDE.md) and [Interaction Reference](docs/INTERACTIONS.md).

## Project status

This repository is intentionally being published as a **prototype** before any attempt at official Blender integration.

The goal of this public phase is to collect real-world feedback about:

- interaction design;
- stability;
- performance;
- rigs/constraints/parenting edge cases;
- macOS/Windows/Linux differences;
- workflows that are not covered by the current prototype.

Please report problems using the GitHub issue templates. Video captures and minimal `.blend` reproduction files are especially useful.

## Known scope / limitations

The current prototype is focused on **Object Location** animation.

Complex evaluated animation - animated parents, constraints, drivers, NLA combinations, pose bones and other dependency-graph-heavy cases - still needs broader testing and may not be represented exactly in every case.

Read [Known Limitations](docs/KNOWN_LIMITATIONS.md) before reporting expected prototype gaps.

## Feedback wanted

Useful feedback is specific and reproducible. When opening a bug report, please include:

- Blender exact version;
- operating system;
- add-on version;
- whether Auto Key is enabled;
- exact steps to reproduce;
- expected result;
- actual result;
- a small `.blend` file when possible;
- screen recording for interaction/picking bugs;
- crash log if Blender crashes.

Use **Issues** for actionable bugs and feature requests. Use **Discussions** for workflow ideas and open-ended design feedback.

## Documentation

- [Installation](docs/INSTALLATION.md)
- [User Guide](docs/USER_GUIDE.md)
- [Interaction Reference](docs/INTERACTIONS.md)
- [Testing / QA](docs/TESTING.md)
- [Known Limitations](docs/KNOWN_LIMITATIONS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development](docs/DEVELOPMENT.md)
- [Roadmap](ROADMAP.md)
- [Contributing](CONTRIBUTING.md)
- [Release Process](docs/RELEASE.md)

## Repository layout

```text
editable-motion-paths/
├── extension/                  # Installable extension source
│   ├── __init__.py
│   └── blender_manifest.toml
├── docs/
├── .github/
├── scripts/
├── README.md
├── CHANGELOG.md
├── CONTRIBUTING.md
├── ROADMAP.md
└── LICENSE
```

## Build a local ZIP

```bash
python scripts/build_extension.py
```

The script packages only the contents of `extension/` so `blender_manifest.toml` and `__init__.py` are at the root of the installable ZIP.

## License

Editable Motion Paths is released under **GNU GPL v3 or later**. See [LICENSE](LICENSE).

## Disclaimer

This is an independent community project. It is not an official Blender feature and is not endorsed or supported by the Blender Foundation.
