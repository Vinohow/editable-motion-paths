# Architecture

## Design goal

Editable Motion Paths treats the trajectory as an interactive view of Blender animation data - not as a second animation system.

```text
Blender Location F-Curves
          │
          ├── path evaluation / sampling
          │
          ├── viewport cache
          │
          ├── GPU overlay
          │      ├── path
          │      ├── arrows
          │      ├── labels
          │      └── samples
          │
          └── interactive controls
                 ├── key positions
                 └── spatial handles
                        │
                        └── write back to F-Curves
```

## Source of truth

F-Curves remain authoritative. The add-on does not create a Curve object and does not convert object motion into a Follow Path constraint.

## Blender 5 actions

F-Curves are read through the layered Action / slot / channelbag API of Blender 5.

## Path sampling

The path is sampled from animation data into a runtime cache. The prototype avoids using repeated `scene.frame_set()` calls as the normal redraw sampling mechanism because frame mutation during interactive transforms can cause flicker and expensive scene reevaluation.

## Targets

A path belongs to a target: an object, or one pose bone of an armature. Targets are identified by name
(`(object name, bone name)`), never by a kept RNA reference, so caches survive Undo/Redo.

## Parent space

The animated value is a *local* Location. Its world position depends on the parent space, which can change over time
(animated parent, parent bones, constraints). For each frame the add-on stores an affine map:

```text
world(frame) = A(frame) @ local_location(frame) + b(frame)
```

- `A` is the linear part of the parent space. For bones it is obtained from `Bone.convert_local_to_pose`, so the
  inherit options (rotation, scale, local location) are respected.
- `b` is computed from the evaluated world position, so anything else that offsets the target is absorbed.

Displaying the path only needs F-Curve evaluation and this map. Editing uses the inverse of `A(frame)`, which is why
a dragged key lands under the pointer even when the parent is rotated at that frame.

Static, unparented, unconstrained objects skip this step: their map is read from the live object.

### Baking without touching the scene

The map is baked in a temporary scene that links only the needed objects and has its own dependency graph.
The user's scene never changes frame, the viewport does not flicker, and unkeyed poses are not lost. The temporary
scene is removed immediately.

One bake evaluates every Location-animated bone of the armature, so switching between controls is instant.

### Staleness

On each tick, the baked map of the current frame is compared with the live one. A difference means the parent space
changed: the cache is dropped and baked again (when the user is not dragging, playing or scrubbing). A difference
that survives a fresh bake is an unkeyed pose; it is remembered so it does not cause a bake loop.

## Runtime cache

Path geometry is runtime state. Cache invalidation is triggered by animation/dependency updates, Undo/Redo and explicit dirty-state changes.

A stale cached path must never become independent persistent animation data.

## Interaction state

Viewport selection/hover state is runtime UI state only. It must not be saved as animation data.

## Spatial handles

Blender Location animation is stored as three scalar curves (X, Y and Z), each with time/value handles. A viewport handle is therefore a spatial abstraction.

The add-on reconstructs a 3D tangent from the component curves and maps direct 3D handle edits back to the scalar curves while attempting to preserve temporal handle distances/easing.

This mapping is one of the most important areas for continued testing.

## Cross-platform rendering

Prototype history showed that GPU point-size behavior was not visually consistent enough across Windows and macOS/Metal. Editable path keys and handles therefore use explicit screen-space disk geometry rather than relying on large GPU point primitives.

## Safety principles

- Do not rebuild/destroy interactive gizmo state while Blender is actively manipulating it.
- Avoid retaining Blender RNA references longer than necessary when data may be rebuilt.
- Keep direct interactions non-blocking.
- Keep ordinary Blender viewport navigation/selection available.
- Prefer cache replacement over partially invalid intermediate draw state.

## Settings

Per-scene state (what is shown, frame range) lives on the scene. Look and behavior (colors, sizes, snapping,
performance) live in the add-on preferences so they are shared by every file.

## Open questions

- Drivers and NLA blending on the edited channels.
- A native implementation could evaluate the parent space in Blender's own motion path code instead of a temporary
  scene.
