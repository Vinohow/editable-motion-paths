# Known Limitations

Editable Motion Paths is a public prototype. This document separates known scope limits from bugs.

## What is supported

- Blender 5.2+.
- **Location** animation of objects and of pose bones.
- Animated parents, bone parents and constraints: the path matches the evaluated motion.
- Direct editing in the 3D View.

## Dragging needs Location keys

Every moving object or bone gets a path, but only Location keys can be dragged.

- **FK bones** are moved by rotations: dragging their path would need an IK solver. Their path is view only; keys
  can be added on it.
- **Connected bones** ignore their Location in Blender: view only.

## Edit Mode

Blender shows the rest pose in Edit Mode, so nothing can be calculated there. A path is shown in Edit Mode only if it
was calculated before in Object or Pose Mode.

## Handles on dense keys

With a key on every frame (motion capture), the handle of a real key only shapes the motion between two frames, and
the path is drawn frame by frame: its effect would not be visible. Real keys mode therefore shows no handles on dense
keys. Use the control points mode (`Shift + Alt + C`) and their handles to shape the curve.

## Linear interpolation

Imported animation often uses Linear interpolation, where Blender ignores the handles. Editing a handle switches
that key and the segment before it to Bezier, which slightly rounds the motion around it.

## Adding keys

A key added by clicking a path keeps the motion exactly for Bezier, Linear and Constant interpolation. With the easing
interpolations (Sine, Back, Elastic...) the curve can change slightly around the new key.

## Parents and constraints

For bones, parented objects and constrained objects, the add-on evaluates the parent space once per frame and caches
it. This is what makes the path exact, and it has a cost:

- The first display of a path on a heavy rig can take a moment. The duration is shown in **Performance**.
- When the animation that moves the target changes, the path is recalculated automatically if **Auto Refresh** is
  on. A change that does not come from keys (a constraint target moved by hand, a driver) is detected on the current
  frame only: click **Refresh** in that case.
- On very heavy rigs, turn **Auto Refresh** off and use **Refresh**.
- If a constraint on the edited bone or object itself overrides its Location (for example Copy Location with full
  influence), the path shows the evaluated motion but dragging its keys has little or no visible effect.

## Drivers and NLA

Location channels driven by drivers, or blended through NLA strips, are displayed from the evaluated motion at the
time of the last refresh but are not edited. Only the keyframes of the assigned Action are edited.

## Unkeyed poses

The path shows the animation, not the unkeyed pose. If you pose a parent without keying it, the path stays where the
animation puts it until you insert a keyframe.

## Platform coverage

Windows and macOS have been tested during development. Linux needs broader community testing.

GPU/backend-specific visual differences should be reported with OS, GPU and Blender version.

## Very large animations

Long frame ranges, many displayed paths or dense sampling increase viewport work. Use:

- the **Active** display mode;
- the **Around Frame** range;
- **Adaptive Sampling** and **Max Samples**.

Report severe performance problems with a reproducible scene and basic scene statistics.

## Prototype compatibility

Before 1.0, setting names, UI grouping and interaction details may evolve based on user feedback.
