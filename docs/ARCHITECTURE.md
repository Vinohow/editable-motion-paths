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

The implementation includes handling for layered Action/slot/channelbag access used by modern Blender versions, while retaining compatibility logic for legacy-style F-Curve access where available.

## Path sampling

The path is sampled from animation data into a runtime cache. The prototype avoids using repeated `scene.frame_set()` calls as the normal redraw sampling mechanism because frame mutation during interactive transforms can cause flicker and expensive scene reevaluation.

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

## Future architecture questions

Community testing should inform whether exact support for constraints, rigs and NLA can remain in Python or requires a different evaluation strategy.
