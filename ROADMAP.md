# Roadmap

This roadmap is intentionally conservative. The public prototype phase prioritizes evidence from real users over adding features quickly.

## Phase 1 - Public prototype (current)

Goals:

- publish source and installable ZIP on GitHub;
- collect interaction/stability feedback;
- test Windows and macOS thoroughly;
- begin Linux verification;
- build a reproducible issue database;
- identify performance limits with real animation scenes.

Exit criteria:

- no known reproducible Blender crash in the normal editing workflow;
- click/drag/handle interactions are predictable;
- Undo/Redo is reliable;
- release process is repeatable;
- QA matrix is run on every release candidate.

## Phase 2 - 1.0 candidate

Focus:

- regression fixes;
- performance profiling;
- parenting/constraint behavior documentation;
- longer animation ranges and dense keyframes;
- multi-object stress testing;
- polished documentation and examples.

Possible additions only if validated by feedback:

- box/lasso path-key selection;
- configurable handle visibility policy;
- improved snapping modes;
- better selected-object path management.

## Phase 3 - Animation coverage

Investigate:

- pose bones;
- animated parents;
- constraints;
- drivers;
- NLA;
- exact dependency-graph evaluated trajectories;
- multiple transform channels beyond Location.

These items may require a deeper architecture than the current lightweight F-Curve evaluator.

## Phase 4 - Evaluate upstream potential

Only after the prototype has meaningful users and stable behavior:

- summarize real user feedback;
- document UX decisions and alternatives;
- prepare performance results;
- prepare a small design proposal;
- discuss with Blender Animation & Rigging maintainers before attempting native implementation.

The GitHub prototype is not presented as an official Blender proposal at this stage.
