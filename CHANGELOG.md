# Changelog

All notable changes to Editable Motion Paths are documented here.

The project is currently in prototype development; versions before 1.0 may change interaction details and internal architecture.

## [0.12.0] - 2026-11-25

### Added
- **Control points for dense keys** (motion capture, Mixamo, baked animation): when there is a key on almost every
  frame, a few keys become control points (one every 8 frames by default). The path is read as a smooth curve
  through the control points plus the small details of the animation. Dragging a control point bends that curve
  roundly (like a Catmull-Rom spline) and the details are kept.
- **Bezier handles on control points**: select a control point and drag its handles to make the curve rounder,
  flatter or to change its direction.
- **Smooth Path**: `Alt + click` on a control point (or the Smooth Path button) replaces the path around it by a
  clean curve through the control points. Useful to repair a zigzag.
- `Alt + drag` on a control point draws its tangent in one gesture, like pulling its handle. Same gesture as on
  normal keys: `Alt + click` cleans the curve, `Alt + drag` shapes it.
- The other keys stay visible, small and transparent, and can still be selected and dragged one by one.
- Preferences: `Control Points` (on/off), `Control Point Spacing`, `Dense Keys Opacity`.
- **Switch between control points and real keys at any time**: `Shift + Alt + C` in the 3D View, or the button
  in the panel. In real keys mode on dense keys there are no handles: with a key on every frame they would have
  no visible effect. Animations with spaced keys keep their handles.

### Changed
- Clicking among close keys picks the nearest one; control points have priority.

### Fixed
- Handles had no effect on keys with Linear interpolation (Mixamo and most FBX imports). Editing a handle, the
  tangent or the corner/smooth state now switches that key and the segment before it to Bezier. Esc restores it.

## [0.11.1] - 2026-11-25

### Fixed
- Armatures without an active bone (typical after a Mixamo or FBX import) showed no path at all. The root bone
  (for example `Hips`) is now shown, which carries the global motion of the character.
- The panel now says "Animated by its bones" instead of "Not animated" for an armature whose bones are animated.

## [0.11.0] - 2026-11-15

### Added
- **Every moving bone has a path**: FK bones (rotation keys), bones moved by the armature object, by parents, IK or
  constraints. Tested on Rigify metarigs and generated Rigify rigs.
- Paths of the selected bones stay visible in Object and Edit Mode. In Object Mode the object path stays editable.
- **Hover a path to add a key, like Loop Cut**: a point snaps to the nearest whole frame with its number; a click
  inserts a key there without changing the motion (the Bezier segment is split exactly). Keys and handles keep
  priority, a drag never inserts, and nothing shows while dragging, playing or scrubbing. Works on every path,
  editable or view only.
- `Bone Point` option: path of the head or of the tail of the bone (tail is best for hands and feet).
- Changes to the animation on any frame (rotation keys of a parent, for example) are detected and the path is
  recalculated by itself.

### Changed
- Paths of bones without Location keys are view only: their keys can't be dragged, but keys can be added.
- `Add Key at Current Frame` keys the channels already animated on the target (like the I key).
- The `Add Key on Path` button is replaced by hovering.

## [0.10.0] - 2026-11-14

### Added
- **Pose bones**: paths are displayed and edited in Pose Mode for bones animated in Location (IK controls, root, hips).
- **Exact paths with animated parents and constraints**: the parent space is evaluated per frame, so the path matches
  the evaluated motion and a dragged key lands where it is dropped, for bones, parented objects and constrained objects.
  The evaluation runs in a temporary scene: the current frame never changes and unkeyed poses are preserved.
- `Refresh` button and `Auto Refresh` option (recalculates when a parent or constraint changes).
- `Add Key at Current Frame`, `Add Key on Path` and `Delete` buttons in the panel.
- Add-on preferences: colors, sizes and behavior are now saved globally instead of per scene, with `Reset to Defaults`.
- French translation, picked automatically from Blender's language.
- Automated headless tests (`tests/`).

### Changed
- The interface is now in English.
- Simpler panel: main actions on top, options in collapsible sections that are closed by default.
- Paths of selected, non-active objects/bones now show their keys.
- The path is drawn with two draw calls instead of one per segment.
- `Add Key on Path` no longer changes the current frame.
- Key type letters are off by default.

### Fixed
- `Alt + drag` tangents now keep both handles aligned in time, so the handle stays under the pointer.
- Clicking a key right after an edit could use a path that was one refresh late.

## [0.9.5] - 2026-11-10

### Changed
- Extension id and name changed to `vino_editable_motion_paths` / "Vino Editable Motion Paths" for the Blender
  Extensions platform. No functional change.

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
