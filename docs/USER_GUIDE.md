# User Guide

## What Editable Motion Paths does

Editable Motion Paths displays the spatial trajectory produced by the Location F-Curves of an object or a pose bone, and lets you manipulate key positions and spatial tangents directly in the 3D View.

The F-Curves are the source of truth. The add-on does not create a hidden Curve controller or Follow Path constraint.

## First animation

1. Create or select an object.
2. At frame 1, insert a Location keyframe.
3. Move to another frame, move the object, insert another Location keyframe.
4. Open **3D View → Sidebar (`N`) → Motion Path**.
5. Make sure **Show Path** and **Editable** are enabled.

The status line under the buttons shows what the path belongs to, or why nothing is displayed.

You should see a path between animated positions, direction arrows and interactive key markers.

## Bones

Select bones in Pose Mode: each selected bone that moves gets a path, whatever moves it (its own keys, FK rotations
of its parents, the armature object, IK, constraints). The paths stay visible in Object and Edit Mode.

- **Active** shows the active bone; **Selected** shows every selected bone.
- Bones animated in **Location** (IK controls, root, hips) are editable: drag their keys.
- Other bones (FK, connected bones) are **view only**: their path can't be dragged, but you can add keys on it.
- **Bone Point** (Display section) chooses the head or the tail of the bone. The tail is best for hands and feet.
- In Object Mode the path of the armature object is the editable one; bone paths are shown with it.
- In Edit Mode Blender shows the rest pose: paths are view only, and a path is shown only if it was calculated before.

## Parents and constraints

When the target has a parent or constraints (always the case for bones), the add-on evaluates the parent motion once
and caches it. The path then matches the evaluated motion, and a dragged key lands where you drop it.

- **Refresh** (icon next to *Editable*) recalculates everything.
- **Auto Refresh** (Performance section) recalculates when the animation that moves the target changes, on any frame.
  Turn it off on very heavy rigs.
- Your scene never changes frame during the calculation, and unkeyed poses are kept.

## Adding and deleting keys

- **Hover a path**: a point appears on it, snapped to the nearest whole frame, with the frame number. **Click** to
  insert a key there. The motion does not change: the curve is split exactly where the key goes.
  - It keys the channels that are already animated (rotation for an FK bone, Location for an IK control...). A target
    without animation of its own gets a Location + Rotation key, like the I key.
  - Keys and handles have priority: there is no preview close to them.
  - A drag never adds a key, and nothing happens while you drag, play or scrub.
  - Turn it off, or change the distance and the color, in the **Editing** section.
- **Add Key at Current Frame** keys the current values of the active object or bone, like the I key.
- **Delete** removes the selected path keys.

## Motion capture and dense keys

When there is a key on almost every frame (Mixamo, motion capture, baked animation), editing key by key is not
practical. The path then shows **control points**: one key every 8 frames, drawn larger.

- Drag a **control point**: the path bends roundly through it, like a curve, up to the second control point on
  each side. The small details of the capture are kept.
- Select a control point to show its **Bezier handles**. Drag a handle to make the curve rounder, flatter or to
  change its direction. Longer handles give rounder curves.
- **Smooth**: `Alt + click` on a control point (or **Smooth Path** in the panel) replaces the path between its two
  neighbors by a clean curve through the control points. Use it to repair a zigzag. The control points do not move.
- **Draw the tangent**: `Alt + drag` on a control point sets the direction and roundness of the curve in one
  gesture, like pulling its handle. `Esc` cancels.
- The other keys stay visible, small and transparent. Click one to select it and drag it on its own.
- Select several control points with `Shift + click` to move a larger part of the path.
- `X`/`Y`/`Z`, `Ctrl` and Undo work as usual.
- **Switch** between control points and real keys at any time with `Shift + Alt + C` in the 3D View, or the
  button in the panel. Real keys mode is for moving single keys: with a key on every frame, handles would have no
  visible effect, so they are hidden. Use the control points to shape curves.
- Settings, in **Editing**: Control Points (on/off), Control Point Spacing, Dense Keys Opacity.

## Selecting a path key

Click a key marker once.

A click is selection only. The add-on uses a drag threshold so a small mouse movement should not accidentally move the key.

Clicking the selected key exposes its handles when handles are enabled.

## Moving a key

Drag a key marker in the 3D View.

This edits the Location F-Curve values at that key frame. The path updates from the modified animation data.

### Multi-selection

Use `Shift + click` to add or remove path keys from the current multi-selection. Dragging a selected key moves the selected set together.

## Corner and smooth behavior

### Quick toggle

`Alt + click` a path key to switch between:

- **Vector / corner:** a sharp spatial direction change;
- **Aligned / smooth:** a manual smooth tangent.

### Manual tangent drawing

If you want control over the initial smooth shape instead of accepting an automatic result:

1. Hold `Alt`.
2. Press on the path key.
3. Drag in the desired tangent direction.
4. Drag farther for a stronger/longer tangent.
5. Release.

This creates a manual aligned tangent from your gesture.

## Editing handles

Select a key, then drag one of its visible handles.

The add-on maps the dragged 3D spatial tangent back onto Blender's scalar X/Y/Z Location F-Curves.

Available conceptual handle modes:

- **Auto** - Blender computes smoothing automatically.
- **Aligned** - manual smooth tangent; both sides remain aligned.
- **Free** - left and right sides can be independent.
- **Vector** - directed toward neighboring keys for straight/corner behavior.

For direct spatial manipulation, procedural handle types may need to become a manual type so the user's dragged result can be preserved.

## Axis and plane constraints

While dragging a key or handle:

- `X` - constrain to X;
- `Y` - constrain to Y;
- `Z` - constrain to Z;
- `Shift + X` - constrain to YZ plane;
- `Shift + Y` - constrain to XZ plane;
- `Shift + Z` - constrain to XY plane.

Press the same constraint key again to return to free movement.

Choose **Global** or **Local** constraint space in the **Editing** section. Local uses the axes of the animated object or bone.

## Snap

Hold `Ctrl` while dragging to snap according to the configured Snap Increment.

## Direction arrows

Enable **Direction Arrows** to draw arrows along the path. Arrow spacing and size are configurable.

The arrows show temporal direction along the trajectory; they do not represent speed magnitude by themselves.

## Past and future

Enable **Past / Future Colors** to use separate path colors around the current frame.

This is a visual aid only and does not modify animation.

## Frame dots

Enable **Frame Dots** to draw a dot on every frame. Dots close together mean slow motion, dots far apart mean fast
motion: this is the classic way to read spacing.

## Frame numbers and key type letters

**Frame Numbers** displays the frame next to each key.

**Key Type Letters** indicate the spatial handle state:

- `V` - Vector;
- `S` - Aligned/smooth;
- `A` - Auto;
- `F` - Free;
- mixed state may be shown when X/Y/Z curves differ.

## Display multiple paths

Use **Active** / **Selected** to choose whether the overlay shows the active object or bone, or every selected one. Only the active path is editable.

For performance testing, prefer the active-object mode when a scene has many animated objects.

## X-Ray

Enable **X-Ray** when you want the path to remain visible through scene geometry.

Disable it when spatial occlusion is important for reading depth.

## Range modes

- **Keyframes** - sample from first to last relevant key.
- **Around Frame** - show a configurable window before and after the current frame.
- **Scene** - use scene start/end.

For very long animations, use a limited range or adaptive sampling.

## Adaptive sampling

The **Performance** section includes:

- Auto Refresh;
- Adaptive Sampling;
- Max Samples;
- Frame Step.

These settings trade path density against viewport cost. If performance drops on long timelines, first reduce the visible range or maximum sample count.

## Appearance

Appearance and behavior settings are saved in the add-on preferences: they apply to every file, and **Reset to Defaults** restores them. You can configure:

- path future color;
- path past color;
- smooth key color;
- corner key color;
- selected key color;
- handle color;
- handle-line color;
- label color;
- line width;
- key size;
- handle size;
- key outline and thickness;
- arrow size/spacing.

Key and handle sizes are screen-space oriented to remain readable across zoom levels and HiDPI/Retina displays.

## Undo / Redo

Normal edits should participate in Blender's Undo/Redo workflow. If you discover an operation that visually fails to follow Undo/Redo, report it as a bug with exact steps.

## Auto Key workflow

With Auto Key enabled, moving an animated object at an intermediate frame should update the path as the animation changes. The project specifically treats “path updates only after validation” as an important regression to test.

See [Testing](TESTING.md) for the full Auto Key test matrix.
