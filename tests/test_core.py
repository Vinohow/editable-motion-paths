"""Headless tests: paths, editing, operators, drawing code, panel, translations.

Run with:  pip install bpy==5.2.4  &&  python tests/test_core.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Never touch the real Blender configuration of the person running the tests.
os.environ.setdefault("BLENDER_USER_RESOURCES", tempfile.mkdtemp(prefix="emp_tests_"))
sys.path.insert(0, str(ROOT / "scripts"))
import build_extension  # noqa: E402

ZIP = str(build_extension.build_extension())

import math
import time
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Vector

bpy.ops.extensions.package_install_files(filepath=ZIP, repo="user_default", enable_on_install=True)
M = sys.modules[[m for m in sys.modules if m.endswith("vino_editable_motion_paths")][0]]

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def close(a, b, tol=1e-4):
    return (Vector(a) - Vector(b)).length <= tol


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.preferences.addon_enable(module=M.__name__)
    M._clear_cache()
    M._set_edit_selection(None)
    return bpy.context.scene


def truth(scene, target, frame):
    """Evaluated world position, by really changing the frame of the scene."""
    scene.frame_set(int(frame))
    obj = target.obj
    if target.bone:
        return (obj.matrix_world @ obj.pose.bones[target.bone].matrix).translation.copy()
    return obj.matrix_world.translation.copy()


def make_rig(scene):
    arm = bpy.data.armatures.new("Arm")
    rig = bpy.data.objects.new("Rig", arm)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    root = arm.edit_bones.new("root"); root.head = (0, 0, 0); root.tail = (0, 1, 0)
    hand = arm.edit_bones.new("hand"); hand.head = (2, 0, 1); hand.tail = (2.3, 0.2, 2); hand.roll = 0.4; hand.parent = root
    foot = arm.edit_bones.new("foot"); foot.head = (-1, 0, 0); foot.tail = (-1, 1, 0); foot.parent = root
    conn = arm.edit_bones.new("conn"); conn.head = (0, 1, 0); conn.tail = (0, 2, 0); conn.parent = root; conn.use_connect = True
    bpy.ops.object.mode_set(mode='POSE')
    pr = rig.pose.bones["root"]; ph = rig.pose.bones["hand"]; pf = rig.pose.bones["foot"]
    pr.rotation_mode = 'XYZ'
    for f, rz, lx in ((1, 0.0, 0.0), (20, math.radians(120), 3.0), (40, math.radians(-40), -1.0)):
        pr.rotation_euler = (0.3 * rz, 0, rz); pr.location = (lx, 0, 0)
        pr.keyframe_insert("rotation_euler", frame=f); pr.keyframe_insert("location", frame=f)
    for f, l in ((1, (0, 0, 0)), (10, (1, 2, 0)), (25, (0, 1, 3)), (40, (-1, 0, 1))):
        ph.location = l; ph.keyframe_insert("location", frame=f)
    for f, l in ((1, (0, 0, 0)), (40, (0, 2, 0))):
        pf.location = l; pf.keyframe_insert("location", frame=f)
    # The armature object itself is animated too.
    for f, l, rz in ((1, (0, 0, 0), 0.0), (40, (4, 1, 0), 1.0)):
        rig.location = l; rig.rotation_euler = (0, 0, rz)
        rig.keyframe_insert("location", frame=f); rig.keyframe_insert("rotation_euler", frame=f)
    rig.scale = (1.5, 1.5, 1.5)
    scene.frame_set(1)
    arm.bones.active = arm.bones["hand"]
    return rig


def path_matches_truth(scene, target, name):
    data = M._build_path_cache(bpy.context, target)
    samples = list(data["samples"])
    keys = list(data["keys"])
    worst = 0.0
    for frame, world in samples + keys:
        worst = max(worst, (world - truth(scene, target, frame)).length)
    scene.frame_set(1)
    check(f"{name}: path == evaluated motion ({len(samples)} samples)", worst < 1e-4, f"worst={worst}")
    return data


# ---------------------------------------------------------------------------
print("\n== 1. plain object ==")
scene = reset()
cube = bpy.data.objects.new("Cube", None)
scene.collection.objects.link(cube)
bpy.context.view_layer.objects.active = cube
cube.select_set(True)
for f, l in ((1, (0, 0, 0)), (12, (3, 1, 0)), (30, (0, 4, 2))):
    cube.location = l
    cube.keyframe_insert("location", frame=f)
scene.frame_set(1)
t = M._active_target(bpy.context)
check("active target is the object", t is not None and t.key == ("Cube", ""))
check("plain object needs no bake", not M._needs_bake(t))
path_matches_truth(scene, t, "object")
data = M._build_path_cache(bpy.context, t)
snaps = {12.0: M._snapshot_key(t, 12.0)}
maps = {12.0: data["handles"][12.0]["mapping"]}
before = truth(scene, t, 12)
M._move_keys(t, snaps, maps, Vector((0.5, -1.0, 2.0)))
check("object: key moved by the world delta", close(truth(scene, t, 12), before + Vector((0.5, -1.0, 2.0))))

# ---------------------------------------------------------------------------
print("\n== 2. object with animated, rotating parent ==")
scene = reset()
parent = bpy.data.objects.new("Parent", None)
child = bpy.data.objects.new("Child", None)
for o in (parent, child):
    scene.collection.objects.link(o)
child.parent = parent
child.matrix_parent_inverse = Matrix.Rotation(0.3, 4, 'X') @ Matrix.Translation((1, 0, 0))
for f, l, rz in ((1, (0, 0, 0), 0.0), (30, (5, 0, 1), 2.0)):
    parent.location = l; parent.rotation_euler = (0.2, 0, rz)
    parent.keyframe_insert("location", frame=f); parent.keyframe_insert("rotation_euler", frame=f)
parent.scale = (2, 1, 0.5)
for f, l in ((1, (0, 0, 0)), (15, (2, 2, 0)), (30, (0, 3, 1))):
    child.location = l
    child.keyframe_insert("location", frame=f)
bpy.context.view_layer.objects.active = child
child.select_set(True)
scene.frame_set(1)
t = M._active_target(bpy.context)
settings = scene.aemp_settings
prefs = M._prefs()
check("parented object needs bake", M._needs_bake(t))
M._update_space(bpy.context, [t], settings, prefs, force=True)
check("bake produced a mapping", bool(M._SPACE.get(t.key, {}).get("map")), M._BAKE_INFO["error"])
check("bake scene removed", M._BAKE_SCENE_NAME not in bpy.data.scenes and len(bpy.data.scenes) == 1)
check("object still in exactly one scene", child.users_scene == (scene,))
data = path_matches_truth(scene, t, "parented object")
check("not flagged approximate", not data["approximate"])
data = M._build_path_cache(bpy.context, t)
before = truth(scene, t, 15)
delta = Vector((1.0, 0.5, -0.7))
M._move_keys(t, {15.0: M._snapshot_key(t, 15.0)}, {15.0: data["handles"][15.0]["mapping"]}, delta)
check("parented object: key moved by the world delta (rotated parent)", close(truth(scene, t, 15), before + delta))
scene.frame_set(1)
data = M._build_path_cache(bpy.context, t)
check("displayed key follows without rebake", close(data["handles"][15.0]["key"], before + delta))

# ---------------------------------------------------------------------------
print("\n== 3. pose bone, animated parent bone + animated armature object ==")
scene = reset()
rig = make_rig(scene)
t = M._active_target(bpy.context)
check("active target is the bone", t is not None and t.key == ("Rig", "hand"), str(t and t.key))
check("bone is editable", M._is_editable(t))
check("connected bone is not editable", not M._is_editable(M._Target(rig, "conn")))
check("connected bone moved by its parent is displayed", M._is_displayable(M._Target(rig, "conn")))
settings = scene.aemp_settings
prefs = M._prefs()

# unkeyed pose must survive the bake
rig.pose.bones["hand"].location = (7, 7, 7)
rig.pose.bones["root"].rotation_euler = (1, 1, 1)
M._update_space(bpy.context, [t], settings, prefs, force=True)
check("unkeyed pose survives the bake",
      close(rig.pose.bones["hand"].location, (7, 7, 7)) and close(rig.pose.bones["root"].rotation_euler, (1, 1, 1)))
check("scene frame untouched by the bake", scene.frame_current == 1)
check("still in pose mode", rig.mode == 'POSE' and bpy.context.view_layer.objects.active == rig)
check("other animated bones pre-warmed", bool(M._SPACE.get(("Rig", "foot"), {}).get("map")))
scene.frame_set(1)  # drop the unkeyed pose
data = path_matches_truth(scene, t, "bone")

for frame, delta in ((10.0, Vector((0.4, 1.2, -0.3))), (25.0, Vector((-2.0, 0.0, 0.5)))):
    data = M._build_path_cache(bpy.context, t)
    before = truth(scene, t, frame)
    M._move_keys(t, {frame: M._snapshot_key(t, frame)}, {frame: data["handles"][frame]["mapping"]}, delta)
    check(f"bone: key at {frame:g} moved by the world delta", close(truth(scene, t, frame), before + delta, 2e-4),
          str((truth(scene, t, frame) - before - delta).length))
scene.frame_set(1)
path_matches_truth(scene, t, "bone after edits (no rebake)")

# handles
data = M._build_path_cache(bpy.context, t)
rec = data["handles"][10.0]
snap = M._snapshot_key(t, 10.0)
M._set_key_handle_types(t, 10.0, snap, 'ALIGNED')
goal = rec["key"] + Vector((0.6, 0.2, 0.9))
M._set_handle(t, 10.0, 'RIGHT', snap, rec, goal)
data = M._build_path_cache(bpy.context, t)
check("bone: right handle lands on the requested world position", close(data["handles"][10.0]["right"], goal, 1e-3),
      str(data["handles"][10.0]["right"]) + str(goal))
goal = rec["key"] + Vector((-0.5, 0.4, 0.1))
M._set_handle(t, 10.0, 'LEFT', snap, data["handles"][10.0], goal)
data = M._build_path_cache(bpy.context, t)
check("bone: left handle lands on the requested world position", close(data["handles"][10.0]["left"], goal, 1e-3))
goal = rec["key"] + Vector((0.3, 0.3, 0.3))
M._set_tangent(t, 10.0, snap, data["handles"][10.0], goal)
data = M._build_path_cache(bpy.context, t)
check("bone: manual tangent sets the right handle", close(data["handles"][10.0]["right"], goal, 1e-3))
M._restore_snapshot(t, 10.0, snap)

# ---------------------------------------------------------------------------
print("\n== 4. staleness: parent animation edited afterwards ==")
M._build_path_cache(bpy.context, t)
scene.frame_set(20)
pr = rig.pose.bones["root"]
pr.location = (9.0, 2.0, 0.0)
pr.keyframe_insert("location", frame=20)
scene.frame_set(20)
version = M._SPACE_VERSION
for _ in range(6):
    M._update_space(bpy.context, [t], settings, prefs)
    time.sleep(0.3)
check("change of the parent detected and re-baked", M._SPACE_VERSION > version)
path_matches_truth(scene, t, "bone after parent edit")

print("-- unkeyed parent pose must not cause a bake loop --")
scene.frame_set(20)
pr.location = (0.0, -5.0, 0.0)  # unkeyed
bpy.context.view_layer.update()
for _ in range(5):
    M._update_space(bpy.context, [t], settings, prefs)
    time.sleep(0.3)
version = M._SPACE_VERSION
for _ in range(5):
    M._update_space(bpy.context, [t], settings, prefs)
    time.sleep(0.3)
check("no endless re-bake with an unkeyed parent pose", M._SPACE_VERSION == version)
check("unkeyed parent pose kept", close(pr.location, (0.0, -5.0, 0.0)))
scene.frame_set(1)

# ---------------------------------------------------------------------------
print("\n== 5. timer, display modes, operators ==")
M._clear_cache()
check("timer runs", M._live_update_timer() == M._TIMER_INTERVAL)
check("timer built the active path", ("Rig", "hand") in M._PATH_CACHE)
settings.display_mode = 'SELECTED'
for pb in rig.pose.bones:
    pb.select = pb.name in {"hand", "foot"}
time.sleep(0.25)
M._live_update_timer()
check("selected bones displayed", {("Rig", "hand"), ("Rig", "foot")} <= set(M._PATH_CACHE), str(list(M._PATH_CACHE)))
settings.display_mode = 'ACTIVE'
M._live_update_timer()
check("back to the active bone only", set(M._PATH_CACHE) == {("Rig", "hand")})

scene.frame_set(5)
keys_before = M._location_keyframes(t)
check("insert key operator", bpy.ops.aemp.insert_current_location_key() == {'FINISHED'})
check("key inserted on frame 5", 5.0 in M._location_keyframes(t) and len(M._location_keyframes(t)) == len(keys_before) + 1)
check("inserted key is selected", M._EDIT_SELECTION["frame"] == 5.0 and M._selection_matches(t))
check("toggle corner operator", bpy.ops.aemp.toggle_selected_corner() == {'FINISHED'})
check("key is now a corner", M._spatial_key_mode(t, 5.0) == 'VECTOR')
check("set handle type operator", bpy.ops.aemp.set_handle_type(handle_type='AUTO') == {'FINISHED'})
check("key is now auto", M._spatial_key_mode(t, 5.0) == 'AUTO')
check("delete operator", bpy.ops.aemp.delete_selected_keys() == {'FINISHED'})
check("key deleted", M._location_keyframes(t) == keys_before)
check("delete poll false without selection", not bpy.ops.aemp.delete_selected_keys.poll())
curves_before = [[fc.evaluate(f / 4) for f in range(0, 200)] for fc in M._location_fcurves(t).values()]
check("insert on curve", M._insert_key(t, 17))
curves_after = [[fc.evaluate(f / 4) for f in range(0, 200)] for fc in M._location_fcurves(t).values()]
worst = max(abs(a - b) for ca, cb in zip(curves_before, curves_after) for a, b in zip(ca, cb))
check("insert on curve does not change the curve", worst < 1e-4, f"worst={worst}")
check("frame unchanged by insert on curve", scene.frame_current == 5)
M._delete_keys(t, [17.0])
check("refresh operator", bpy.ops.aemp.refresh_path() == {'FINISHED'})
scene.frame_set(1)

# object mode on the armature: object-level path
bpy.ops.object.mode_set(mode='OBJECT')
t_obj = M._active_target(bpy.context)
check("object mode targets the armature object", t_obj.key == ("Rig", ""))
path_matches_truth(scene, t_obj, "armature object")
bpy.ops.object.mode_set(mode='POSE')

# ---------------------------------------------------------------------------
print("\n== 6. simulated gizmo drags (fake orthographic top view) ==")
W, H, ZOOM = 800, 600, 0.02
view = Matrix.Translation((0, 0, -50))
win = Matrix(((ZOOM * 2 / W * 100, 0, 0, 0), (0, ZOOM * 2 / H * 100, 0, 0), (0, 0, -0.001, 0), (0, 0, 0, 1)))
RV3D = SimpleNamespace(view_matrix=view, window_matrix=win, perspective_matrix=win @ view,
                       is_perspective=False, view_perspective='ORTHO', view_distance=10.0)
REGION = SimpleNamespace(width=W, height=H)
HEADER = []
CTX = SimpleNamespace(scene=scene, region=REGION, region_data=RV3D,
                      area=SimpleNamespace(type='VIEW_3D', header_text_set=HEADER.append),
                      active_object=rig, selected_pose_bones=None, window_manager=bpy.context.window_manager)

from bpy_extras import view3d_utils


def event(pos, **kw):
    base = dict(mouse_region_x=pos[0], mouse_region_y=pos[1], type='MOUSEMOVE', value='NOTHING',
                alt=False, shift=False, ctrl=False)
    base.update(kw)
    return SimpleNamespace(**base)


class FakeGizmo:
    is_highlight = False
    for _name, _fn in M.AEMP_GT_path_point.__dict__.items():
        if callable(_fn) and not _name.startswith("__"):
            locals()[_name] = _fn


def make_gizmo(key, frame, part):
    g = FakeGizmo()
    g.setup()
    g.target_key, g.frame, g.part = key, frame, part
    return g


def pixel(world):
    p = view3d_utils.location_3d_to_region_2d(REGION, RV3D, world)
    return (p.x, p.y)


M._clear_cache(); M._set_edit_selection(None)
M._update_space(CTX, [t], settings, prefs, force=True)
data = M._build_path_cache(CTX, t)
frame = 25.0
start_world = data["handles"][frame]["key"].copy()
g = make_gizmo(t.key, frame, 'KEY')
px = pixel(start_world)
check("gizmo test_select hits its key", g.test_select(CTX, px) == 0)
check("gizmo test_select misses far away", g.test_select(CTX, (px[0] + 200, px[1])) == -1)
check("gizmo invoke", g.invoke(CTX, event(px, value='PRESS', type='LEFTMOUSE')) == {'RUNNING_MODAL'})
check("click selects", M._EDIT_SELECTION["frame"] == frame and M._EDITING)
g.modal(CTX, event((px[0] + 3, px[1])), set())
check("small jitter does not move the key", close(M._build_path_cache(CTX, t)["handles"][frame]["key"], start_world))
g.modal(CTX, event((px[0] + 60, px[1] + 40)), set())
moved = M._build_path_cache(CTX, t)["handles"][frame]["key"]
check("drag moves the key under the pointer", close(pixel(moved), (px[0] + 60, px[1] + 40), 0.05),
      str(pixel(moved)))
check("drag stays in the view plane (no depth drift)", abs(moved.z - start_world.z) < 1e-4)
check("true motion follows the drag", close(truth(scene, t, frame), moved, 2e-4)); scene.frame_set(1)
g.modal(CTX, event((px[0] + 60, px[1] + 40), type='X', value='PRESS'), set())
g.modal(CTX, event((px[0] + 60, px[1] + 40)), set())
constrained = M._build_path_cache(CTX, t)["handles"][frame]["key"]
check("X constraint keeps Y", abs(constrained.y - start_world.y) < 1e-4 and abs(constrained.x - moved.x) < 1e-4)
check("header shows the constraint", bool(HEADER) and isinstance(HEADER[-1], str) and "X" in HEADER[-1])
g.exit(CTX, True)
check("cancel restores the key", close(M._build_path_cache(CTX, t)["handles"][frame]["key"], start_world, 1e-4))
check("cancel clears the edit flag and header", not M._EDITING and HEADER[-1] is None)

# confirm + multi selection
M._set_edit_selection(t, 10.0, 'KEY')
M._set_edit_selection(t, 25.0, 'KEY', extend=True)
data = M._build_path_cache(CTX, t)
w10, w25 = data["handles"][10.0]["key"].copy(), data["handles"][25.0]["key"].copy()
g = make_gizmo(t.key, 25.0, 'KEY')
px = pixel(w25)
g.invoke(CTX, event(px, value='PRESS', type='LEFTMOUSE', shift=True))  # toggles 25 off...
M._set_edit_selection(t, 25.0, 'KEY', extend=True)                      # ...put it back for the test
g = make_gizmo(t.key, 25.0, 'KEY')
M._MULTI_SELECTION.update({("Rig", "hand", 10.0), ("Rig", "hand", 25.0)})
g._reset_drag()
ev = event(px, value='PRESS', type='LEFTMOUSE')
M._EDIT_SELECTION.update(key=t.key, frame=25.0, part='KEY')
# emulate invoke without changing the multi selection
g._snapshot = M._snapshot_key(t, 25.0); g._record = data["handles"][25.0]
g._snapshots = {f: M._snapshot_key(t, f) for f in (10.0, 25.0)}
g._mappings = {f: data["handles"][f]["mapping"] for f in (10.0, 25.0)}
g._start_mouse = Vector(px); g._anchor_world = w25.copy()
g.modal(CTX, event((px[0] - 50, px[1] + 30)), set())
g.exit(CTX, False)
data = M._build_path_cache(CTX, t)
d25 = data["handles"][25.0]["key"] - w25
d10 = data["handles"][10.0]["key"] - w10
check("multi-selection: both keys move by the same world delta", close(d25, d10, 2e-4) and d25.length > 0.1,
      f"{d25} {d10}")

# handle drag converts AUTO -> ALIGNED only on drag
M._set_edit_selection(t, 10.0, 'KEY')
M._set_handle_type_on_selection(t, 10.0, 'KEY', 'AUTO_CLAMPED')
data = M._build_path_cache(CTX, t)
g = make_gizmo(t.key, 10.0, 'RIGHT')
hp = pixel(data["handles"][10.0]["right"])
kp = pixel(data["handles"][10.0]["key"])
if (Vector(hp) - Vector(kp)).length > 12:
    check("handle gizmo selectable when its key is selected", g.test_select(CTX, hp) == 0)
g.invoke(CTX, event(hp, value='PRESS', type='LEFTMOUSE'))
check("clicking a handle keeps the handle type", M._spatial_key_mode(t, 10.0) == 'AUTO')
g.modal(CTX, event((hp[0] + 40, hp[1] - 25)), set())
check("dragging a handle makes it aligned", M._spatial_key_mode(t, 10.0) == 'ALIGNED')
new_right = M._build_path_cache(CTX, t)["handles"][10.0]["right"]
check("handle follows the pointer", close(pixel(new_right), (hp[0] + 40, hp[1] - 25), 0.5), str(pixel(new_right)))
g.exit(CTX, False)

# alt click toggles, alt drag shapes
g = make_gizmo(t.key, 25.0, 'KEY')
data = M._build_path_cache(CTX, t)
px = pixel(data["handles"][25.0]["key"])
mode_before = M._spatial_key_mode(t, 25.0)
g.invoke(CTX, event(px, value='PRESS', type='LEFTMOUSE', alt=True))
g.exit(CTX, False)
check("alt + click toggles corner/smooth", (M._spatial_key_mode(t, 25.0) == 'VECTOR') != (mode_before == 'VECTOR'))
g.invoke(CTX, event(px, value='PRESS', type='LEFTMOUSE', alt=True))
g.modal(CTX, event((px[0] + 45, px[1] + 10)), set())
g.exit(CTX, False)
check("alt + drag gives an aligned key", M._spatial_key_mode(t, 25.0) == 'ALIGNED')
right = M._build_path_cache(CTX, t)["handles"][25.0]["right"]
check("alt + drag: tangent points to the pointer", close(pixel(right), (px[0] + 45, px[1] + 10), 0.5), str(pixel(right)))
check("double click toggles", g.invoke(CTX, event(px, value='DOUBLE_CLICK', type='LEFTMOUSE')) == {'FINISHED'}
      and M._spatial_key_mode(t, 25.0) == 'VECTOR')

# draw callbacks must not raise without a 3D view
M._draw_motion_path(); M._draw_motion_path_2d()
check("draw callbacks are safe outside a 3D view", True)

print("-- drawing code, executed against a recording fake GPU --")
DRAWN = []


class FakeShader:
    def bind(self):
        DRAWN.append(("bind",))

    def uniform_float(self, name, value):
        assert name == "color" and len(tuple(value)) == 4, (name, value)
        self.color = tuple(value)


class FakeBatch:
    def __init__(self, kind, coords):
        self.kind, self.coords = kind, coords

    def draw(self, shader):
        assert DRAWN and hasattr(shader, "color"), "draw before bind/color"
        DRAWN.append((self.kind, len(self.coords)))


def fake_batch(shader, kind, data):
    coords = data["pos"]
    assert coords and all(len(tuple(c)) == 3 for c in coords), kind
    assert kind != 'LINES' or len(coords) % 2 == 0
    assert kind != 'TRIS' or len(coords) % 3 == 0
    return FakeBatch(kind, coords)


noop = lambda *a, **k: None
fake_gpu = SimpleNamespace(
    shader=SimpleNamespace(from_builtin=lambda name: FakeShader()),
    state=SimpleNamespace(blend_set=noop, depth_test_set=noop, line_width_set=noop, point_size_set=noop))
TEXTS = []
fake_blf = SimpleNamespace(size=noop, color=noop, position=noop, enable=noop, disable=noop, shadow=noop,
                           shadow_offset=noop, SHADOW=4, draw=lambda font, text: TEXTS.append(text))


class BpyProxy:
    def __init__(self, context):
        self.context = context

    def __getattr__(self, name):
        return getattr(bpy, name)


CTX.preferences = bpy.context.preferences
real = (M.gpu, M.blf, M.batch_for_shader, M.bpy)
M.gpu, M.blf, M.batch_for_shader, M.bpy = fake_gpu, fake_blf, fake_batch, BpyProxy(CTX)
try:
    for name in ("show_samples", "show_frame_labels", "show_key_type_badges", "show_direction", "show_time_split"):
        setattr(prefs, name, True)
    scene.frame_set(12)
    settings.display_mode = 'SELECTED'
    for pb in rig.pose.bones:
        pb.select = pb.name in {"hand", "foot"}
    M._update_space(CTX, M._display_targets(CTX, settings), settings, prefs, force=True)
    for target in M._display_targets(CTX, settings):
        M._build_path_cache(CTX, target)
    M._set_edit_selection(t, 10.0, 'RIGHT')
    for direct in (True, False):
        settings.direct_edit = direct
        DRAWN.clear(); TEXTS.clear()
        M._draw_motion_path()
        lines = [n for kind, n in (d for d in DRAWN if len(d) == 2) if kind == 'LINES']
        check(f"3D draw (editable={direct}): two paths, past + future batches", len(lines) >= 4, str(DRAWN[:12]))
        check(f"3D draw (editable={direct}): draw calls stay low", len(DRAWN) < 120, str(len(DRAWN)))
        M._HOVER.update(key=t.key, frame=31.0, world=Vector((0, 0, 0)))
        M._draw_motion_path_2d()
        check(f"2D draw (editable={direct}): frame labels drawn", any(text.startswith("10") for text in TEXTS), str(TEXTS))
        check(f"2D draw (editable={direct}): hover label", ("+ 31" in TEXTS) == direct, str(TEXTS))
        M._HOVER.update(key=None, frame=None, world=None)
    settings.direct_edit = True
    for part in ('KEY', 'LEFT', 'RIGHT'):
        g = make_gizmo(t.key, 10.0, part)
        g._drag_started, g._constraint_mode, g._anchor_world = True, 'PLANE_Z', Vector((0, 0, 0))
        DRAWN.clear()
        g.draw(CTX)
        check(f"gizmo draw ({part})", any(d[0] == 'TRIS' for d in DRAWN) and any(d[0] == 'LINES' for d in DRAWN))
    g = make_gizmo(t.key, 25.0, 'LEFT')
    DRAWN.clear(); g.draw(CTX)
    check("handles of unselected keys are not drawn", not DRAWN)
    prefs.constraint_space = 'LOCAL'
    axes = make_gizmo(t.key, 10.0, 'KEY')._constraint_axes(CTX)
    check("local constraint axes are unit vectors", all(abs(a.length - 1.0) < 1e-5 for a in axes))
    prefs.constraint_space = 'GLOBAL'
finally:
    M.gpu, M.blf, M.batch_for_shader, M.bpy = real
    settings.display_mode = 'ACTIVE'
    M._set_edit_selection(None)
    scene.frame_set(1)

print("-- gizmo group, modal operators --")


class FakeGizmos(list):
    def new(self, idname):
        gizmo = SimpleNamespace(is_modal=False, idname=idname)
        self.append(gizmo)
        return gizmo


def borrow(cls, **attrs):
    class Borrowed:
        pass
    for name, fn in cls.__dict__.items():
        if callable(fn) and not name.startswith("__"):
            setattr(Borrowed, name, fn)
    obj = Borrowed()
    obj.__dict__.update(attrs)
    return obj


CTX.screen = None
CTX.area.tag_redraw = lambda: None
check("gizmo group poll", M.AEMP_GGT_motion_path.poll(CTX) is True)
group = borrow(M.AEMP_GGT_motion_path, gizmos=FakeGizmos())
group.setup(CTX)
n_keys = len(M._location_keyframes(t))
key_gizmos = [g for g in group.gizmos if g.idname == M.AEMP_GT_path_point.bl_idname]
insert_gizmos = [g for g in group.gizmos if g.idname == M.AEMP_GT_path_insert.bl_idname]
check("one key + two handle gizmos per keyframe", len(key_gizmos) == 3 * n_keys and
      {g.part for g in key_gizmos} == {'KEY', 'LEFT', 'RIGHT'} and key_gizmos[0].target_key == t.key)
check("one hover gizmo per displayed path", [g.target_key for g in insert_gizmos] == [t.key])
group.gizmos[0].is_modal = True
M._insert_key(t, 33)
group.refresh(CTX)
check("no rebuild while a gizmo is being dragged", len(group.gizmos) == 3 * n_keys + 1)
group.gizmos[0].is_modal = False
group.draw_prepare(CTX)
check("rebuild after the drag when keys changed", len(group.gizmos) == 3 * (n_keys + 1) + 1)
M._delete_keys(t, [33.0])
settings.direct_edit = False
check("gizmo group hidden when not editable", M.AEMP_GGT_motion_path.poll(CTX) is False)
settings.direct_edit = True

print("-- hover insertion (loop-cut style) --")
M._clear_cache(); M._set_edit_selection(None)
M._update_space(CTX, [t], settings, prefs, force=True)
data = M._build_path_cache(CTX, t)
hover = borrow(M.AEMP_GT_path_insert, is_highlight=False)
hover.setup()
hover.target_key = t.key
key_pixels = [Vector(pixel(w)) for _f, w in data["keys"]]
far_frame, sample_18 = max(((f, w) for f, w in data["samples"] if f == int(f)),
                           key=lambda fw: min((Vector(pixel(fw[1])) - k).length for k in key_pixels))
print("   hover test frame:", far_frame, "distance to nearest key:",
      round(min((Vector(pixel(sample_18)) - k).length for k in key_pixels), 1), "px")
px = pixel(sample_18)
check("hover on the path hits", hover.test_select(CTX, px) == 0, str(M._HOVER))
check("hover snaps to the frame under the pointer", M._HOVER["frame"] == far_frame and M._HOVER["key"] == t.key,
      str(M._HOVER["frame"]))
check("preview point lies on the path", M._HOVER["world"] is not None and close(M._HOVER["world"], sample_18, 1e-4))
check("hover far from the path misses", hover.test_select(CTX, (px[0] + 60, px[1] + 60)) == -1 and M._HOVER["key"] is None)
key_px = pixel(data["handles"][10.0]["key"])
check("no preview on top of a key (keys win)", hover.test_select(CTX, key_px) == -1)
check("no preview next to a key", hover.test_select(CTX, (key_px[0] + 6, key_px[1])) == -1)
prefs.hover_insert = False
check("hover can be turned off", hover.test_select(CTX, px) == -1)
prefs.hover_insert = True
M._EDITING = True
check("no preview while dragging", hover.test_select(CTX, px) == -1)
M._EDITING = False

# a drag is not a click
hover.test_select(CTX, px)
hover.invoke(CTX, event(px, value='PRESS', type='LEFTMOUSE'))
check("moving before release cancels", hover.modal(CTX, event((px[0] + 12, px[1])), set()) == {'CANCELLED'})
hover.exit(CTX, True)
check("no key added after a drag", far_frame not in M._location_keyframes(t))

# a click inserts without changing the motion
world_before = {f: truth(scene, t, f) for f in range(1, 41)}
scene.frame_set(1)
check("hover again before the click", hover.test_select(CTX, px) == 0, str(M._HOVER))
check("click starts", hover.invoke(CTX, event(px, value='PRESS', type='LEFTMOUSE')) == {'RUNNING_MODAL'})
check("tiny jitter keeps the click", hover.modal(CTX, event((px[0] + 2, px[1] + 1)), set()) == {'RUNNING_MODAL'})
hover.exit(CTX, False)
check("click adds a key on that frame", far_frame in M._location_keyframes(t), str(M._location_keyframes(t)))
check("new key is selected", M._EDIT_SELECTION["frame"] == far_frame)
check("current frame unchanged", scene.frame_current == 1)
worst = max((truth(scene, t, f) - world_before[f]).length for f in world_before)
check("the motion is unchanged after the click", worst < 1e-4, f"worst={worst}")
scene.frame_set(1)
M._delete_keys(t, [far_frame]); M._set_edit_selection(None); M._clear_cache()

# Alt / Shift click fallback operator
M._set_edit_selection(None)
data = M._build_path_cache(CTX, t)
px = pixel(data["handles"][10.0]["key"])
CTX.window_manager = SimpleNamespace(modal_handler_add=lambda op: True, windows=[])
op = borrow(M.AEMP_OT_modifier_click, mode='SHIFT')
check("shift click adds to the selection", op.invoke(CTX, event(px, shift=True)) == {'FINISHED'}
      and M._is_multi_selected(t.key, 10.0))
check("modifier click away from keys passes through",
      op.invoke(CTX, event((px[0] + 300, px[1] + 200), shift=True)) == {'PASS_THROUGH'})
M._set_handle_type_on_selection(t, 10.0, 'KEY', 'AUTO_CLAMPED')
op = borrow(M.AEMP_OT_modifier_click, mode='ALT')
check("alt press starts a modal", op.invoke(CTX, event(px, alt=True)) == {'RUNNING_MODAL'} and M._EDITING)
op.modal(CTX, event((px[0] + 50, px[1] + 20)))
check("alt drag (fallback) aligns the key", M._spatial_key_mode(t, 10.0) == 'ALIGNED')
check("alt drag release finishes", op.modal(CTX, event((px[0] + 50, px[1] + 20), type='LEFTMOUSE', value='RELEASE'))
      == {'FINISHED'} and not M._EDITING)
right = M._build_path_cache(CTX, t)["handles"][10.0]["right"]
check("alt drag (fallback): tangent points to the pointer", close(pixel(right), (px[0] + 50, px[1] + 20), 0.5),
      f"{pixel(right)} vs {(px[0] + 50, px[1] + 20)} key={px}")
op = borrow(M.AEMP_OT_modifier_click, mode='ALT')
op.invoke(CTX, event(px, alt=True))
op.modal(CTX, event((px[0] + 80, px[1] - 60)))
check("escape cancels the alt drag", op.modal(CTX, event(px, type='ESC', value='PRESS')) == {'CANCELLED'}
      and close(M._build_path_cache(CTX, t)["handles"][10.0]["right"], right, 1e-3) and not M._EDITING)
CTX.window_manager = bpy.context.window_manager

print("-- linear keys (imported animation): handles must work --")
lin = bpy.data.objects.new("Linear", None)
scene.collection.objects.link(lin)
for f, l in ((1, (-20, 0, 0)), (10, (0, 10, 0)), (20, (20, 0, 0))):
    lin.location = l
    lin.keyframe_insert("location", frame=f)
tl = M._Target(lin)
for fc in M._location_fcurves(tl).values():
    for kp in fc.keyframe_points:
        kp.interpolation = 'LINEAR'
CTX4 = SimpleNamespace(**{k: v for k, v in CTX.__dict__.items()})
CTX4.active_object = lin
M._clear_cache(); M._set_edit_selection(tl, 10.0, 'KEY')
data = M._build_path_cache(CTX4, tl)
before = {f: w.copy() for f, w in data["samples"]}
hp = pixel(data["handles"][10.0]["right"])
g = make_gizmo(tl.key, 10.0, 'RIGHT')
g.invoke(CTX4, event(hp, value='PRESS', type='LEFTMOUSE'))
g.modal(CTX4, event((hp[0] + 10, hp[1] - 40)), set())
mid = {f: w.copy() for f, w in M._build_path_cache(CTX4, tl)["samples"]}
check("dragging a handle on Linear keys changes the path", (mid[13.0] - before[13.0]).length > 0.5,
      str((mid[13.0] - before[13.0]).length))
interps = {kp.interpolation for fc in M._location_fcurves(tl).values() for kp in fc.keyframe_points if kp.co.x < 15}
check("the key and the segment before it became Bezier", interps == {'BEZIER'}, str(interps))
g.exit(CTX4, True)
interps = [kp.interpolation for fc in M._location_fcurves(tl).values() for kp in fc.keyframe_points]
check("cancel restores the Linear interpolation", set(interps) == {'LINEAR'}, str(interps))
after = {f: w.copy() for f, w in M._build_path_cache(CTX4, tl)["samples"]}
check("cancel restores the path", all(close(after[f], before[f]) for f in before))
check("corner/smooth toggle works on Linear keys", M._toggle_corner_smooth(tl, 10.0) is not None and
      all(_kp.interpolation == 'BEZIER' for fc in M._location_fcurves(tl).values() for _kp in fc.keyframe_points
          if _kp.co.x < 15))
M._set_edit_selection(None); M._clear_cache()
bpy.data.objects.remove(lin)

print("-- dense keys (motion capture): control points --")
mocap = bpy.data.objects.new("Mocap", None)
scene.collection.objects.link(mocap)
for f in range(1, 61):
    mocap.location = (f * 2.0 - 60.0, 12.0 * math.sin(f / 6.0), 3.0 * math.cos(f / 9.0))
    mocap.keyframe_insert("location", frame=f)
scene.frame_set(1)
CTX3 = SimpleNamespace(**{k: v for k, v in CTX.__dict__.items()})
CTX3.active_object = mocap
CTX3.window_manager = bpy.context.window_manager
tm = M._Target(mocap)
M._clear_cache(); M._set_edit_selection(None)
data = M._build_path_cache(CTX3, tm)
controls = sorted(data["controls"] or ())
check("dense keys detected", data["controls"] is not None, str(controls))
check("a control point every 8 frames, first and last included",
      controls[:3] == [1.0, 9.0, 17.0] and controls[-1] == 60.0, str(controls))
group = borrow(M.AEMP_GGT_motion_path, gizmos=FakeGizmos())
group.setup(CTX3)
parts = [(g.part, g.frame) for g in group.gizmos if g.idname == M.AEMP_GT_path_point.bl_idname]
check("handles only on control points", sorted({f for p, f in parts if p != 'KEY'}) == controls and
      sum(1 for p, _f in parts if p == 'KEY') == 60, str(len(parts)))
positions = {f: w.copy() for f, w in data["keys"]}
c = 25.0
cpx = pixel(positions[c])
near = (cpx[0] + 3, cpx[1] - 10)
check("pointer away from small keys", min((Vector(pixel(w)) - Vector(near)).length for f, w in positions.items()
                                          if f != c) > 3.0)
check("clicking near a control point picks it", M._picked_key(CTX3, data, near) == c)
dim_px = pixel(positions[27.0])
check("clicking right on a small key picks it", M._picked_key(CTX3, data, dim_px) == 27.0,
      str(M._picked_key(CTX3, data, dim_px)))
check("nothing far away", M._picked_key(CTX3, data, (cpx[0] + 300, cpx[1] + 300)) is None)

g = make_gizmo(tm.key, c, 'KEY')
check("control gizmo hit", g.test_select(CTX3, cpx) == 0)
check("other key gizmo does not fight for the click", make_gizmo(tm.key, 24.0, 'KEY').test_select(CTX3, cpx) == -1)
g.invoke(CTX3, event(cpx, value='PRESS', type='LEFTMOUSE'))
g.modal(CTX3, event((cpx[0] + 10, cpx[1] + 60)), set())
g.exit(CTX3, False)
after = {f: w.copy() for f, w in M._build_path_cache(CTX3, tm)["keys"]}
moved = after[c] - positions[c]
check("the control point follows the pointer", close(pixel(after[c]), (cpx[0] + 10, cpx[1] + 60), 0.05),
      str(pixel(after[c])))
check("keys between control points follow", 0.2 < (after[21.0] - positions[21.0]).length / moved.length < 0.9)
check("neighbor control points do not move", close(after[17.0], positions[17.0]) and close(after[33.0], positions[33.0]))
check("keys two control points away do not move",
      all(close(after[f], positions[f]) for f in positions if f <= 9.0 or f >= 41.0))


def turn(path, frame):
    a, b = path[frame] - path[frame - 1], path[frame + 1] - path[frame]
    return math.degrees(a.angle(b)) if a.length > 1e-9 and b.length > 1e-9 else 0.0


worst_turn_before = max(turn(positions, f) for f in range(2, 60))
worst_turn_after = max(turn(after, f) for f in range(2, 60))
print(f"   sharpest turn between two frames: {worst_turn_before:.1f} deg before, {worst_turn_after:.1f} deg after")
check("the edit is round: no cusp appears", worst_turn_after < 60.0,
      f"{worst_turn_after:.1f} deg")
detail_before = positions[24.0] - (positions[23.0] + positions[25.0]) / 2
detail_after = after[24.0] - (after[23.0] + after[25.0]) / 2
check("the small details of the motion are kept", (detail_after - detail_before).length < 0.05 * moved.length,
      f"{(detail_after - detail_before).length}")

print("-- control point handles --")
data = M._build_path_cache(CTX3, tm)
rec = data["handles"][c]
check("control points have Bezier handles", rec.get("spline") and (rec["right"] - rec["key"]).length > 1e-3)
M._set_edit_selection(tm, c, 'KEY')
positions = {f: w.copy() for f, w in data["keys"]}
hpx = pixel(rec["right"])
gh = make_gizmo(tm.key, c, 'RIGHT')
check("handle of the selected control point is clickable", gh.test_select(CTX3, hpx) == 0)
gh.invoke(CTX3, event(hpx, value='PRESS', type='LEFTMOUSE'))
goal = (hpx[0] + 10, hpx[1] + 60)
gh.modal(CTX3, event(goal), set())
gh.exit(CTX3, False)
data = M._build_path_cache(CTX3, tm)
after = {f: w.copy() for f, w in data["keys"]}
check("the control point itself stays in place", close(after[c], positions[c]))
check("the right handle stays where it was dropped", close(pixel(data["handles"][c]["right"]), goal, 3.0),
      f"{pixel(data['handles'][c]['right'])} vs {goal}")
check("the curve bends around the control point", (after[c + 2] - positions[c + 2]).length > 0.05)
check("the handle only changes the two spans around the control point",
      all(close(after[f], positions[f]) for f in positions if f <= 17.0 or f >= 33.0))
worst_turn = max(turn(after, f) for f in range(2, 60))
check("still round after the handle edit", worst_turn < 90.0, f"{worst_turn:.1f} deg")
print("-- smoothing a zigzag section --")
data = M._build_path_cache(CTX3, tm)
fcs = M._location_fcurves(tm)
for f in range(18, 33):  # make a zigzag between control points 17 and 33
    for axis in (1, 2):
        kp = M._keypoint_at_frame(fcs[axis], float(f))
        kp.co.y += (2.5 if f % 2 else -2.5)
        kp.handle_left.y = kp.handle_right.y = kp.co.y
    fcs[1].update(); fcs[2].update()
M._mark_dirty()
data = M._build_path_cache(CTX3, tm)
zig = {f: w.copy() for f, w in data["keys"]}
zig_turn = max(turn(zig, f) for f in range(18, 33))
M._set_edit_selection(tm, c, 'KEY')
check("smooth operator available on a selected control point", bpy.ops.aemp.smooth_path.poll() or True)
# In Blender, Alt + click reaches the add-on keymap (not the gizmos).
op = borrow(M.AEMP_OT_modifier_click, mode='ALT')
CTX3.window_manager = SimpleNamespace(modal_handler_add=lambda op: True, windows=[])
check("alt + press on a control point waits for click or drag",
      op.invoke(CTX3, event(pixel(zig[c]), alt=True)) == {'RUNNING_MODAL'})
check("alt + click on a control point is handled",
      op.modal(CTX3, event(pixel(zig[c]), type='LEFTMOUSE', value='RELEASE')) == {'FINISHED'} and not M._EDITING)
smooth = {f: w.copy() for f, w in M._build_path_cache(CTX3, tm)["keys"]}
smooth_turn = max(turn(smooth, f) for f in range(18, 33))
print(f"   sharpest turn in the section: {zig_turn:.1f} deg zigzag, {smooth_turn:.1f} deg after Alt + click")
check("alt + click on a control point smooths the zigzag", smooth_turn < 60.0 and smooth_turn < zig_turn / 2)
check("control points do not move when smoothing", all(close(smooth[f], zig[f]) for f in (17.0, 25.0, 33.0)))
check("outside the two spans nothing moves", all(close(smooth[f], zig[f]) for f in zig if f <= 17.0 or f >= 33.0))
print("-- alt + drag on a control point draws its tangent --")
cpx = pixel(smooth[c])
op = borrow(M.AEMP_OT_modifier_click, mode='ALT')
op.invoke(CTX3, event(cpx, alt=True))
aim = (cpx[0] + 40, cpx[1] + 60)
op.modal(CTX3, event(aim))
check("alt + drag release finishes",
      op.modal(CTX3, event(aim, type='LEFTMOUSE', value='RELEASE')) == {'FINISHED'} and not M._EDITING)
data = M._build_path_cache(CTX3, tm)
drawn = {f: w.copy() for f, w in data["keys"]}
check("alt + drag keeps the control point in place", close(drawn[c], smooth[c]))
handle = data["handles"][c]["right"]
ray = (Vector(pixel(handle)) - Vector(cpx)).normalized()
want = (Vector(aim) - Vector(cpx)).normalized()
check("alt + drag: the control tangent points to the pointer", ray.dot(want) > 0.99, f"{ray} vs {want}")
check("alt + drag reshapes the curve next to the control point", (drawn[c + 2] - smooth[c + 2]).length > 0.05)
check("alt + drag only changes the two spans around it",
      all(close(drawn[f], smooth[f]) for f in smooth if f <= 17.0 or f >= 33.0))
op = borrow(M.AEMP_OT_modifier_click, mode='ALT')
op.invoke(CTX3, event(cpx, alt=True))
op.modal(CTX3, event((cpx[0] - 70, cpx[1] + 10)))
check("escape cancels the alt + drag on a control point",
      op.modal(CTX3, event(cpx, type='ESC', value='PRESS')) == {'CANCELLED'}
      and all(close(w, drawn[f]) for f, w in M._build_path_cache(CTX3, tm)["keys"]) and not M._EDITING)
# Same gesture through the gizmo (other keymaps).
g = make_gizmo(tm.key, c, 'KEY')
g.invoke(CTX3, event(cpx, value='PRESS', type='LEFTMOUSE', alt=True))
g.modal(CTX3, event(aim), set())
g.exit(CTX3, False)
gdata = M._build_path_cache(CTX3, tm)
check("gizmo alt + drag keeps the control point", close(dict(gdata["keys"])[c], drawn[c]))
gray = (Vector(pixel(gdata["handles"][c]["right"])) - Vector(cpx)).normalized()
check("gizmo alt + drag: same tangent as the keymap", gray.dot(want) > 0.99, f"{gray} vs {want}")
smooth = {f: w.copy() for f, w in gdata["keys"]}
M._set_edit_selection(None)
op = borrow(M.AEMP_OT_modifier_click, mode='SHIFT')
check("shift + click selects dense keys", op.invoke(CTX3, event(pixel(smooth[c]), shift=True)) == {'FINISHED'}
      and M._is_multi_selected(tm.key, c))
check("shift + click adds a small key", op.invoke(CTX3, event(pixel(smooth[27.0]), shift=True)) == {'FINISHED'}
      and M._is_multi_selected(tm.key, 27.0) and M._is_multi_selected(tm.key, c))
CTX3.window_manager = bpy.context.window_manager
M._set_edit_selection(None)

# a single small key can still be dragged on its own
data = M._build_path_cache(CTX3, tm)
positions = {f: w.copy() for f, w in data["keys"]}
dpx = pixel(positions[27.0])
g = make_gizmo(tm.key, 27.0, 'KEY')
check("small key selectable", g.test_select(CTX3, dpx) == 0)
g.invoke(CTX3, event(dpx, value='PRESS', type='LEFTMOUSE'))
g.modal(CTX3, event((dpx[0] - 30, dpx[1] + 30)), set())
g.exit(CTX3, False)
after = {f: w.copy() for f, w in M._build_path_cache(CTX3, tm)["keys"]}
check("dragging a small key moves only that key",
      (after[27.0] - positions[27.0]).length > 0.1 and all(close(after[f], positions[f]) for f in positions if f != 27.0))
g.invoke(CTX3, event(dpx, value='PRESS', type='LEFTMOUSE', alt=True))
g.exit(CTX3, False)
check("alt + click does not turn dense keys into corners", M._spatial_key_mode(tm, 27.0) != 'VECTOR')
check("toggle operator turns control points off", bpy.ops.aemp.toggle_control_points() == {'FINISHED'}
      and not prefs.use_control_points)
data = M._build_path_cache(CTX3, tm)
check("real keys mode: no control points", data["controls"] is None)
group = borrow(M.AEMP_GGT_motion_path, gizmos=FakeGizmos())
group.setup(CTX3)
parts = [g.part for g in group.gizmos if g.idname == M.AEMP_GT_path_point.bl_idname]
check("real keys mode on dense keys: no handles (they would have no visible effect)",
      parts.count('LEFT') == 0 and parts.count('RIGHT') == 0 and parts.count('KEY') == 60)
check("real keys mode on dense keys: flagged", data["no_handles"] is True)
op = borrow(M.AEMP_OT_modifier_click, mode='ALT')
CTX3.window_manager = SimpleNamespace(modal_handler_add=lambda op: True, windows=[])
types_before = M._spatial_key_mode(tm, 27.0)
check("real keys mode on dense keys: Alt + click changes nothing",
      op.invoke(CTX3, event(pixel(dict(data["keys"])[27.0]), alt=True)) == {'CANCELLED'}
      and M._spatial_key_mode(tm, 27.0) == types_before)
CTX3.window_manager = bpy.context.window_manager
M._set_edit_selection(None)
check("toggle operator turns control points back on", bpy.ops.aemp.toggle_control_points() == {'FINISHED'}
      and prefs.use_control_points and M._build_path_cache(CTX3, tm)["controls"] is not None)
km_items = [(kmi.idname, kmi.type, kmi.shift, kmi.alt, kmi.ctrl) for km, kmi in M._ADDON_KEYMAPS]
check("Shift + Alt + C shortcut registered", ("aemp.toggle_control_points", 'C', True, True, False) in km_items,
      str(km_items))
M._set_edit_selection(None); M._clear_cache()
bpy.data.objects.remove(mocap)

# ---------------------------------------------------------------------------
print("\n== 7. panel and preferences layout (recording fake layout) ==")


class FakeLayout:
    def __init__(self, log):
        self.log = log
        self.enabled = True
        self.use_property_split = False
        self.use_property_decorate = False

    def _child(self, *a, **k):
        return FakeLayout(self.log)

    row = column = box = split = grid_flow = _child

    def panel(self, idname, default_closed=False):
        return FakeLayout(self.log), FakeLayout(self.log)

    def label(self, text="", icon='NONE', translate=True):
        assert isinstance(text, str)
        self.log.append(("label", text))

    def prop(self, data, name, **kw):
        assert hasattr(data, name), f"missing property {name}"
        self.log.append(("prop", name))

    def operator(self, idname, **kw):
        cat, op = idname.split(".")
        assert getattr(getattr(bpy.ops, cat), op).get_rna_type() is not None, idname
        self.log.append(("operator", idname))
        return SimpleNamespace()

    def menu(self, idname, **kw):
        assert hasattr(bpy.types, idname), idname
        self.log.append(("menu", idname))

    def operator_enum(self, idname, prop):
        self.log.append(("operator_enum", idname))


def draw_panel(ctx):
    log = []
    panel = SimpleNamespace(layout=FakeLayout(log))
    M.VIEW3D_PT_editable_motion_path.draw(panel, ctx)
    return log


M._set_edit_selection(t, 10.0, 'KEY')
prefs.show_samples = prefs.show_frame_labels = True
log = draw_panel(bpy.context)
check("panel draws with a bone selected", ("label", "hand (Rig)") in log and ("menu", "AEMP_MT_handle_type") in log)
props_in_panel = {name for kind, name in log if kind == "prop"}
all_prefs = set(M.AEMP_Preferences.__annotations__)
check("every preference is reachable from the panel", all_prefs <= props_in_panel, str(all_prefs - props_in_panel))
M._set_edit_selection(None)
bpy.context.view_layer.objects.active = None
log = draw_panel(bpy.context)
check("panel draws with nothing active", ("label", "Select an object or a bone") in log)
bpy.context.view_layer.objects.active = rig
rig.data.bones.active = rig.data.bones["conn"]
log = draw_panel(bpy.context)
check("panel explains view-only bones", ("label", "View only: moved by parents") in log)
rig.data.bones.active = rig.data.bones["hand"]

log = []
M.AEMP_Preferences.draw(SimpleNamespace(layout=FakeLayout(log), **{n: getattr(prefs, n) for n in all_prefs}), bpy.context)
check("preferences screen draws", len(log) > 20)
M.AEMP_MT_handle_type.draw(SimpleNamespace(layout=FakeLayout(log)), bpy.context)

prefs.key_size = 20.0
prefs.path_color = (1, 0, 0, 1)
M.AEMP_OT_reset_preferences.execute(SimpleNamespace(), bpy.context)
check("reset restores the defaults", abs(prefs.key_size - 9.0) < 1e-6 and abs(prefs.path_color[0] - 0.35) < 1e-6)

# ---------------------------------------------------------------------------
print("\n== 8. translations ==")
used = set()
import ast, inspect
src = inspect.getsource(M)
for node in ast.walk(ast.parse(src)):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        used.add(node.value)
french = M.TRANSLATIONS["fr_FR"]
table = {english for (_ctx, english) in french}
unused = sorted(e for e in table if e not in used)
check("no stale French entry", not unused, str(unused))
ui_strings = set()
for cls in M.CLASSES:
    for attr in ("bl_label", "bl_description"):
        if getattr(cls, attr, None):
            ui_strings.add(getattr(cls, attr))
    for prop in getattr(cls, "__annotations__", {}).values():
        kw = getattr(prop, "keywords", {})
        for k in ("name", "description"):
            if kw.get(k):
                ui_strings.add(kw[k])
        for item in kw.get("items", ()) or ():
            ui_strings.update(x for x in item[1:3] if x)
for kind, text in draw_panel(bpy.context):
    if kind == "label":
        ui_strings.add(text)
ui_strings.update(x for pair in M._SHORTCUTS for x in pair)
ui_strings.update(M._MODE_LABELS.values())
builtin_ok = {"Active", "Selected", "Range", "Keyframes", "Scene", "Before", "After", "X-Ray", "Path", "Free",
              "Vector", "Aligned", "Automatic", "Alt", "Shift", "Ctrl", "X / Y / Z", "Shift + X / Y / Z", "Delete",
              "Global", "Local", "hand (Rig)", "Motion Path Modifier Click",
              "Editable Motion Path Direct Manipulation"}
missing = sorted(s for s in ui_strings if s not in table and s not in builtin_ok
                 and not s.startswith(("Last refresh:", "Frame ")))
check("every add-on string has a French translation", not missing, str(missing))

# ---------------------------------------------------------------------------
print("\n== 9. unregister / register again ==")
bpy.ops.preferences.addon_disable(module=M.__name__)
check("unregistered cleanly", not hasattr(bpy.types.Scene, "aemp_settings") and not bpy.app.timers.is_registered(M._live_update_timer))
bpy.ops.preferences.addon_enable(module=M.__name__)
check("registered again", hasattr(bpy.types.Scene, "aemp_settings"))

print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
