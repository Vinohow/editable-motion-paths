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
