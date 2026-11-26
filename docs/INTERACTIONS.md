# Interaction Reference

This document defines the intended interaction contract. Treat unexpected deviations as bugs unless they are listed in Known Limitations.

## Pointer interactions

| Input | Target | Expected behavior |
|---|---|---|
| Click | Key | Select only; no accidental move |
| Drag | Key | Move key spatially |
| Click | Selected key | Keep selection and expose handles |
| Drag | Handle | Modify spatial tangent |
| `Shift + click` | Key | Add/remove key from multi-selection |
| `Alt + click` | Key | Toggle corner ↔ smooth |
| `Alt + drag` | Key | Draw/size manual aligned tangent |
| `Alt + click` | Control point (dense keys) | Smooth Path around it |
| `Alt + drag` | Control point (dense keys) | Draw the tangent of the control curve |

## Panel actions

| Button | Result |
|---|---|
| Add Key at Current Frame | Key the current values of the active object or bone (like the I key) |
| Delete | Delete the selected path keys |
| Corner / Smooth | Same as `Alt + click` on the selected key |
| Refresh | Recalculate the paths, including the motion of parents and constraints |
| Use Real Keys / Use Control Points | Switch dense keys between the two modes (`Shift + Alt + C`) |
| Smooth Path | Replace the path around the selected control points by a clean curve (`Alt + click`) |

## Targets

| Mode | Path shown for |
|---|---|
| Object Mode | The active object (editable) + its active or selected bones |
| Pose Mode | The active bone (or every selected bone) |
| Edit Mode | Same as Object Mode, view only |

## Hover insertion

| Input | Target | Expected behavior |
|---|---|---|
| Hover | Path, away from keys | A point snaps to the nearest whole frame, with its number |
| Click | Path | Insert a key at that frame; the motion does not change |
| Drag | Path | Nothing inserted |
| Hover | Close to a key or a handle | No preview: the key or handle has priority |

## During drag

| Input | Result |
|---|---|
| `X` | X-axis constraint |
| `Y` | Y-axis constraint |
| `Z` | Z-axis constraint |
| `Shift + X` | YZ plane |
| `Shift + Y` | XZ plane |
| `Shift + Z` | XY plane |
| Repeat same constraint | Free movement |
| Hold `Ctrl` | Snap |

## UX rules

### Click is not drag

A key must not move until the mouse exceeds the configured internal drag threshold. This prevents “lottery” behavior where selection unexpectedly changes animation.

### Key hit priority

When a key marker and handle hit-region overlap, the key's central hit area takes priority. Handles should not steal clicks from the key center.

### No permanent edit mode

Direct interaction should coexist with ordinary Blender viewport work. Users should not need to enter a blocking modal mode simply to select path keys.

### Contextual controls

Handle controls should appear only when relevant. The panel's selection section remains visible, but its content is disabled when nothing is selected.

### Native conventions first

When possible, use Blender conventions rather than introducing new shortcuts:

- Shift for additive selection;
- Alt for alternate/tangent behavior;
- X/Y/Z for axis constraints;
- Ctrl for snapping;
- Undo/Redo through Blender.
