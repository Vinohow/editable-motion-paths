# Known Limitations

Editable Motion Paths is currently a public prototype. This document separates known scope limits from bugs.

## Supported focus

The primary supported workflow is:

- Object animation;
- Location F-Curves;
- Blender 5.2+;
- direct editing in the 3D View.

## Animation evaluation

The prototype uses a lightweight F-Curve-oriented path evaluation strategy to keep the viewport responsive and avoid repeatedly changing the scene frame during drawing.

As a result, exact evaluated world motion may need additional work for combinations such as:

- animated parents;
- complex constraints;
- drivers;
- NLA blending;
- dependency-graph effects that change world position without simple Location F-Curve values.

If a path differs from final evaluated object motion in one of these cases, open an issue with a minimal reproduction. Real examples are important for deciding the correct future architecture.

## Pose bones

Pose-bone motion-path editing is not yet a declared supported feature.

## Rotation and scale

The prototype is focused on spatial Location paths. Rotation and scale visualization/editing are not part of the current feature contract.

## Platform coverage

Windows and macOS have been actively tested during prototype development. Linux needs broader community testing.

GPU/backend-specific visual differences should be reported with OS, GPU and Blender version.

## Very large animations

Long frame ranges, many selected objects or dense sampling can increase viewport work. Use:

- Active Object display;
- Around Current Frame range;
- Adaptive Sampling;
- Max Samples.

Report severe performance problems with a reproducible scene and basic scene statistics.

## Prototype compatibility

Before 1.0, settings names, UI grouping and interaction details may evolve based on user feedback.
