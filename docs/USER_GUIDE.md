# User Guide

## What Editable Motion Paths does

Editable Motion Paths displays the spatial trajectory produced by an object's Location F-Curves and lets you manipulate key positions and spatial tangents directly in the 3D View.

The F-Curves are the source of truth. The add-on does not create a hidden Curve controller or Follow Path constraint.

## First animation

1. Create or select an object.
2. At frame 1, insert a Location keyframe.
3. Move to another frame, move the object, insert another Location keyframe.
4. Open **3D View → Sidebar (`N`) → Motion Path**.
5. Enable **Trajectory** and **Editable**.

You should see a path between animated positions, direction arrows and interactive key markers.

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

Choose **Global** or **Local** constraint space in Advanced settings.

## Snap

Hold `Ctrl` while dragging to snap according to the configured Snap Increment.

## Direction arrows

Enable **Animation Direction** to draw arrows along the path. Arrow spacing and size are configurable.

The arrows show temporal direction along the trajectory; they do not represent speed magnitude by themselves.

## Past and future

Enable **Distinguish Past / Future** to use separate path colors around the current frame.

This is a visual aid only and does not modify animation.

## Frame labels and key badges

Optional viewport labels can display frame numbers.

Key-type badges indicate the spatial handle state:

- `V` - Vector;
- `S` - Aligned/smooth;
- `A` - Auto;
- `F` - Free;
- mixed state may be shown when X/Y/Z curves differ.

## Display multiple paths

Use **Trajectories** to choose whether the overlay is focused on the active object or selected objects.

For performance testing, prefer the active-object mode when a scene has many animated objects.

## X-Ray

Enable **X-Ray** when you want the path to remain visible through scene geometry.

Disable it when spatial occlusion is important for reading depth.

## Range modes

- **Between Keys** - sample from first to last relevant key.
- **Around Current Frame** - show a configurable window before and after the current frame.
- **Scene** - use scene start/end.

For very long animations, use a limited range or adaptive sampling.

## Adaptive sampling

Advanced settings include:

- Minimum Step;
- Adaptive Sampling;
- Max Samples.

These settings trade path density against viewport cost. If performance drops on long timelines, first reduce the visible range or maximum sample count.

## Appearance

You can configure:

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
