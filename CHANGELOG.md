# Changelog

All notable changes to Editable Motion Paths are documented here.

The project is currently in prototype development; versions before 1.0 may change interaction details and internal architecture.

## [0.9.4] - 2026-10-09

### Added
- Screen-space disk rendering for editable keys and handles for more consistent macOS/Windows behavior.
- Adjustable key and handle size.
- Adjustable smooth-key, corner-key and selected-key colors.
- Optional key outline and outline thickness.
- Single `Trajectories` display selector instead of ambiguous Active/Selected tab-like buttons.
- Contextual `Edit Selection` accordion that remains visible and is disabled when nothing is selected.

### Changed
- Removed double-rendering of editable keys by overlay + gizmo while direct editing is active.
- Improved Retina/HiDPI visibility.
- Consolidated panel UX into a single page with accordions.

## [0.9.3] - 2026-10-09

### Added
- `Alt + drag` on a key to create and size a manual aligned tangent.
- Accordion-based panel organization.
- Help/gesture section moved to the bottom.

## [0.9.2]

### Added
- `X/Y/Z` axis constraints while dragging keys/handles.
- `Shift + X/Y/Z` complementary plane constraints.
- Global/Local constraint space.
- Temporary visual axis guide.

## [0.9.1]

### Fixed
- Clear click-vs-drag threshold to avoid accidental moves.
- Key hit priority over nearby handles.
- More deterministic modifier-click behavior.

## [0.9.0]

### Added
- Multi-selection.
- Past/future path colors.
- Frame labels and key-type badges.
- X-Ray option.
- Active-object / selected-objects path display.
- Adaptive sampling and sample limits.
- Appearance controls.

## [0.8.1]

### Fixed
- Prevented gizmo recreation during active interaction.
- Reduced risk from stale Blender RNA references during drag.

## [0.8.0]

### Changed
- Moved direct path controls toward Blender gizmo-style interaction.

## Earlier prototypes

Versions 0.2–0.7 established live path drawing, direct key editing, direction arrows, handle editing, Auto Key preview and cross-platform packaging. They are retained only as development history and are not recommended for use.
