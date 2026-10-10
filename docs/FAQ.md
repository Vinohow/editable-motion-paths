# FAQ

## Is this an official Blender feature?

No. Editable Motion Paths is an independent community prototype.

## What Blender version is supported?

The current manifest targets Blender 5.2.0 or newer.

## Why not use Blender's built-in Motion Paths only?

The prototype explores direct spatial editing: selecting, moving and reshaping Location animation keys from the path itself in the 3D View.

## Does it create a Curve object?

No. Blender Location F-Curves remain the source of truth.

## Why does moving a handle affect X, Y and Z curves?

Blender stores Location animation as separate scalar F-Curves. A 3D spatial tangent must be reconstructed from and written back to those component curves.

## What is the difference between corner and smooth?

A corner uses Vector-like spatial behavior for a sharp direction change. Smooth uses a manual aligned tangent so the trajectory can flow continuously through the key.

## Why use Alt-drag if Alt-click already makes the key smooth?

Alt-click is the fast toggle. Alt-drag is for control: the drag direction and length define the initial tangent instead of accepting an automatically shaped curve.

## Does it support Auto Key?

Auto Key interaction is part of the prototype's intended workflow and should update the path as animation changes. Please report cases where the path only updates after transform confirmation.

## Can I change key sizes and colors?

Yes. Open the Appearance section. Key/handle rendering is designed to be consistent across Windows and macOS HiDPI/Retina displays.

## Does it support pose bones?

Not as a declared supported feature yet.

## Does it support constraints and animated parents?

These cases need broader testing. The lightweight path evaluator may not exactly match every dependency-graph-driven world transform. See Known Limitations.

## Where should I report a bug?

Use the GitHub Bug Report issue form. Attach a minimal `.blend`, short video and crash log when relevant.

## Where should I post an idea that is not fully specified?

Use GitHub Discussions rather than a bug issue.
