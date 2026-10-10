# Maintainer Triage Guide

## Priority order

1. Reproducible Blender crash.
2. Data corruption / wrong keyframe values.
3. Undo/Redo failure.
4. Input ambiguity (wrong key/handle picked).
5. Auto Key live-update regression.
6. Major platform rendering/input difference.
7. Performance regression.
8. Feature requests / polish.

## Suggested labels

- `bug`
- `enhancement`
- `crash`
- `data-integrity`
- `undo-redo`
- `interaction`
- `handles`
- `auto-key`
- `performance`
- `evaluation`
- `macos`
- `windows`
- `linux`
- `needs-repro`
- `documentation`

## Reproduction quality

A strong bug report includes:

- exact Blender build;
- exact add-on version;
- OS/GPU;
- 3–8 deterministic steps;
- expected vs actual;
- minimal `.blend`;
- short video for pointer interaction;
- crash log for native crash.

If reproduction is missing, label `needs-repro` rather than guessing.

## Release blocking

Treat these as release blockers when reproducible in the main declared workflow:

- Blender crash;
- keyframe value corruption;
- selection that unpredictably edits animation;
- broken Undo/Redo;
- install/enable failure;
- path becoming permanently stale;
- severe cross-platform regression.
