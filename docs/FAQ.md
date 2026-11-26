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

Alt-click is the fast toggle. Alt-drag is for control: the drag direction and length define the initial tangent instead of accepting an automatically shaped curve. It works the same way on the control points of dense keys.

## Does it support Auto Key?

Auto Key interaction is part of the prototype's intended workflow and should update the path as animation changes. Please report cases where the path only updates after transform confirmation.

## Can I change key sizes and colors?

Yes. Open the Appearance section of the panel, or the add-on preferences. Key/handle rendering is designed to be consistent across Windows and macOS HiDPI/Retina displays.

## Does it support pose bones?

Yes. Since 0.11 every selected bone that moves has a path, including FK bones and Rigify controls, in every mode.

Keys can be dragged on bones animated in Location (IK controls, root, hips). FK paths are view only, but you can click them to add keys.

## How do I add a key on the path?

Hover the path: a point appears, snapped to a frame. Click: the key is added there without changing the motion.

## Does it support constraints and animated parents?

Yes, since 0.10. The parent space is evaluated per frame, so the path matches the evaluated motion and a dragged key lands where you drop it. See Known Limitations for the details.

## Which languages are available?

English, and French when Blender's language is set to French. Translations live in `extension/translations.py`; contributions are welcome.

## My colors and sizes are gone after an update

Since 0.10 they are stored in the add-on preferences instead of each scene. Set them once and they follow you in every file.

## Where should I report a bug?

Use the GitHub Bug Report issue form. Attach a minimal `.blend`, short video and crash log when relevant.

## Where should I post an idea that is not fully specified?

Use GitHub Discussions rather than a bug issue.
