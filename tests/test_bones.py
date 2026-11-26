"""Headless tests: bones moved by rotation, by the object or by a Rigify rig; key insertion.

Run with:  pip install bpy==5.2.4  &&  python tests/test_bones.py
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

import math  # noqa: E402
import random  # noqa: E402
import time  # noqa: E402
from types import SimpleNamespace  # noqa: E402

import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

bpy.ops.extensions.package_install_files(filepath=ZIP, repo="user_default", enable_on_install=True)
M = sys.modules[[m for m in sys.modules if m.endswith("vino_editable_motion_paths")][0]]
FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.preferences.addon_enable(module=M.__name__)
    M._clear_cache()
    M._set_edit_selection(None)
    return bpy.context.scene


def truth(scene, target, frame, tail=False):
    scene.frame_set(int(frame))
    obj = target.obj
    if target.bone:
        pose_bone = obj.pose.bones[target.bone]
        return obj.matrix_world @ (pose_bone.tail if tail else pose_bone.head)
    return obj.matrix_world.translation.copy()


def exact(scene, target, name, tail=False, tol=1e-4):
    settings, prefs = scene.aemp_settings, M._prefs()
    M._update_space(bpy.context, [target], settings, prefs, force=True)
    data = M._build_path_cache(bpy.context, target)
    if data is None:
        check(f"{name}: path displayed", False, "no path")
        return None
    frame = scene.frame_current
    worst = max((w - truth(scene, target, f, tail)).length for f, w in list(data["samples"]) + list(data["keys"]))
    scene.frame_set(frame)
    check(f"{name}: path == evaluated motion ({len(data['samples'])} samples)", worst < tol, f"worst={worst}")
    return data


def pose_snapshot(scene, obj, frames):
    result = {}
    for frame in frames:
        scene.frame_set(frame)
        result[frame] = [(pb.matrix.copy()) for pb in obj.pose.bones] if obj.pose else [obj.matrix_world.copy()]
    return result


def pose_diff(first, second):
    worst = 0.0
    for frame in first:
        for a, b in zip(first[frame], second[frame]):
            worst = max(worst, max(abs(x - y) for ra, rb in zip(a, b) for x, y in zip(ra, rb)))
    return worst


# ---------------------------------------------------------------------------
print("\n== 1. metarig case: only the armature object is animated, FK bones connected ==")
scene = reset()
arm = bpy.data.armatures.new("Arm")
rig = bpy.data.objects.new("metarig", arm)
scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
spine = arm.edit_bones.new("spine"); spine.head = (0, 0, 1); spine.tail = (0, 0, 1.5)
chest = arm.edit_bones.new("chest"); chest.head = (0, 0, 1.5); chest.tail = (0, 0, 2); chest.parent = spine; chest.use_connect = True
upper = arm.edit_bones.new("upper_arm.R"); upper.head = (-0.2, 0, 1.9); upper.tail = (-0.6, 0, 1.9); upper.parent = chest
fore = arm.edit_bones.new("forearm.R"); fore.head = (-0.6, 0, 1.9); fore.tail = (-1.0, 0, 1.9); fore.parent = upper; fore.use_connect = True
hand = arm.edit_bones.new("hand.R"); hand.head = (-1.0, 0, 1.9); hand.tail = (-1.15, 0, 1.9); hand.parent = fore; hand.use_connect = True
bpy.ops.object.mode_set(mode='OBJECT')
for f, l in ((0, (0, 0, 0)), (39, (3, 2, 0))):
    rig.location = l
    rig.keyframe_insert("location", frame=f)
scene.frame_set(10)
bpy.ops.object.mode_set(mode='POSE')
for pb in rig.pose.bones:
    pb.select = pb.name == "hand.R"
arm.bones.active = arm.bones["hand.R"]
settings, prefs = scene.aemp_settings, M._prefs()

t = M._active_target(bpy.context)
check("pose mode: active target is hand.R", t.key == ("metarig", "hand.R"))
check("hand.R is displayed although it has no keys", M._is_displayable(t))
check("hand.R is not editable (no Location keys)", not M._is_editable(t))
check("frame range comes from the object keys", M._frame_bounds(bpy.context, t, settings) == (0, 39))
check("display targets in pose mode", [x.key for x in M._display_targets(bpy.context, settings)] == [t.key])
exact(scene, t, "hand.R moved by the object")
M._live_update_timer()
check("timer builds the path in pose mode", t.key in M._PATH_CACHE)

print("-- FK arm animation: rotations only --")
upper_pb = rig.pose.bones["upper_arm.R"]; fore_pb = rig.pose.bones["forearm.R"]
upper_pb.rotation_mode = fore_pb.rotation_mode = 'XYZ'
for f, a, b in ((0, 0.0, 0.0), (15, 0.9, -1.2), (30, -0.4, 0.6), (39, 0.2, 0.0)):
    upper_pb.rotation_euler = (0, a, 0.3 * a); fore_pb.rotation_euler = (b, 0, 0)
    upper_pb.keyframe_insert("rotation_euler", frame=f); fore_pb.keyframe_insert("rotation_euler", frame=f)
chest_pb = rig.pose.bones["chest"]
chest_pb.rotation_mode = 'QUATERNION'
for f, angle in ((0, 0.0), (20, 0.5), (39, -0.3)):
    from mathutils import Quaternion
    chest_pb.rotation_quaternion = Quaternion((0, 0, 1), angle)
    chest_pb.keyframe_insert("rotation_quaternion", frame=f)
scene.frame_set(10)
M._clear_cache()
exact(scene, t, "hand.R, FK arm + quaternion chest + object", tail=False)
prefs.path_point = 'TAIL'
exact(scene, t, "hand.R tail", tail=True)
prefs.path_point = 'HEAD'

print("-- object and edit mode --")
for pb in rig.pose.bones:
    pb.select = pb.name in {"hand.R", "forearm.R"}
bpy.ops.object.mode_set(mode='OBJECT')
settings.display_mode = 'SELECTED'
keys = [x.key for x in M._display_targets(bpy.context, settings)]
check("object mode: object path first (editable), then the selected bones",
      keys[0] == ("metarig", "") and set(keys[1:]) == {("metarig", "hand.R"), ("metarig", "forearm.R")}, str(keys))
check("object mode: the object path is editable", M._is_editable(M._active_target(bpy.context)))
settings.display_mode = 'ACTIVE'
keys = [x.key for x in M._display_targets(bpy.context, settings)]
check("object mode, Active: object + active bone", keys == [("metarig", ""), ("metarig", "hand.R")], str(keys))
M._clear_cache()
for _ in range(2):
    time.sleep(0.25)
    M._live_update_timer()
check("object mode: bone path built", ("metarig", "hand.R") in M._PATH_CACHE)
exact(scene, M._Target(rig, "hand.R"), "hand.R seen from object mode")
before = M._PATH_CACHE[("metarig", "hand.R")]["samples"][5][1].copy()
bpy.ops.object.mode_set(mode='EDIT')
for _ in range(3):
    time.sleep(0.25)
    M._live_update_timer()
data = M._PATH_CACHE.get(("metarig", "hand.R"))
check("edit mode: path still displayed", data is not None)
check("edit mode: path unchanged (rest pose ignored)", data is not None and (data["samples"][5][1] - before).length < 1e-5)
check("edit mode: not editable", not M._is_editable(M._Target(rig, "")))
check("edit mode: no evaluation scene left", len(bpy.data.scenes) == 1)
bpy.ops.object.mode_set(mode='POSE')

print("-- no active bone (Mixamo import): root bones are shown --")
bpy.ops.object.mode_set(mode='OBJECT')
settings.display_mode = 'ACTIVE'
active_bone = arm.bones.active
arm.bones.active = None
keys = [x.key for x in M._display_targets(bpy.context, settings)]
check("object mode, no active bone: object + root bone", keys == [("metarig", ""), ("metarig", "spine")], str(keys))
bpy.ops.object.mode_set(mode='POSE')
keys = [x.key for x in M._display_targets(bpy.context, settings)]
check("pose mode, no active bone: root bone", keys == [("metarig", "spine")], str(keys))
arm.bones.active = active_bone

print("-- staleness: a rotation key edited on another frame --")
scene.frame_set(10)
M._clear_cache()
M._update_space(bpy.context, [t], settings, prefs, force=True)
version = M._SPACE_VERSION
fc = next(c for c in M._transform_fcurves(M._Target(rig, "upper_arm.R")) if c.array_index == 1)
fc.keyframe_points[2].co.y += 0.8
fc.keyframe_points[2].handle_left.y += 0.8
fc.keyframe_points[2].handle_right.y += 0.8
fc.update()
M._RIG_INDEX.clear()
for _ in range(4):
    time.sleep(0.25)
    M._RIG_INDEX.clear()
    M._update_space(bpy.context, [t], settings, prefs)
check("change on frame 30 detected while standing on frame 10", M._SPACE_VERSION > version)
exact(scene, t, "hand.R after the edit")
version = M._SPACE_VERSION
for _ in range(4):
    time.sleep(0.25)
    M._RIG_INDEX.clear()
    M._update_space(bpy.context, [t], settings, prefs)
check("no re-evaluation when nothing changes", M._SPACE_VERSION == version)

# ---------------------------------------------------------------------------
print("\n== 2. key insertion keeps the motion ==")
frames = list(range(0, 40, 1))
snap = pose_snapshot(scene, rig, frames)
check("insert on the FK upper arm (rotation keys)", M._insert_key(M._Target(rig, "upper_arm.R"), 22))
M._RIG_INDEX.clear()
check("rotation key added on frame 22", 22.0 in M._own_key_frames(M._Target(rig, "upper_arm.R")))
check("insert on the quaternion chest", M._insert_key(M._Target(rig, "chest"), 7))
check("insert on a bone without animation (hand.R)", M._insert_key(M._Target(rig, "hand.R"), 12))
check("hand.R got Location + Rotation keys", {c.data_path.rsplit(".", 1)[1] for c in M._transform_fcurves(M._Target(rig, "hand.R"))}
      >= {"location", "rotation_quaternion"})
M._RIG_INDEX.clear()
worst = pose_diff(snap, pose_snapshot(scene, rig, frames))
check("every bone keeps exactly the same pose on every frame", worst < 1e-4, f"worst={worst}")
scene.frame_set(10)

print("-- all handle types and interpolations --")
random.seed(3)
for kind in ('AUTO_CLAMPED', 'AUTO', 'VECTOR', 'ALIGNED', 'FREE', 'LINEAR', 'CONSTANT', 'MIXED'):
    ob = bpy.data.objects.new(f"curve_{kind}", None)
    scene.collection.objects.link(ob)
    for f, z in ((1, 0.0), (9, 3.0), (14, -1.0), (30, 2.0)):
        ob.location.z = z
        ob.keyframe_insert("location", index=2, frame=f)
    curve = M._location_fcurves(M._Target(ob))[2]
    for i, kp in enumerate(curve.keyframe_points):
        if kind in {'LINEAR', 'CONSTANT'}:
            kp.interpolation = kind
        elif kind == 'MIXED':
            kp.handle_left_type, kp.handle_right_type = random.choice(
                [('AUTO', 'AUTO'), ('VECTOR', 'VECTOR'), ('FREE', 'VECTOR'), ('ALIGNED', 'ALIGNED')])
            kp.interpolation = 'BEZIER' if i != 2 else 'LINEAR'
        else:
            kp.handle_left_type = kp.handle_right_type = kind
        if kind in {'FREE', 'ALIGNED'}:
            kp.handle_right = (kp.co.x + 4.0, kp.co.y + 2.5)
            kp.handle_left = (kp.co.x - 1.0, kp.co.y - 1.5)
    curve.update()
    if kind == 'LINEAR':
        curve.extrapolation = 'LINEAR'
    before = [curve.evaluate(f / 8) for f in range(-10, 280)]
    for frame in (5, 11, 12.5, 20, 29, 35, -3):
        M._insert_preserving(curve, frame)
    after = [curve.evaluate(f / 8) for f in range(-10, 280)]
    worst = max(abs(a - b) for a, b in zip(before, after))
    check(f"{kind}: 7 keys inserted (inside and outside the range), curve unchanged",
          len(curve.keyframe_points) == 11 and worst < 1e-4,
          f"keys={len(curve.keyframe_points)} worst={worst}")
    # the curve must also survive Blender recalculating the handles later
    curve.update()
    after = [curve.evaluate(f / 8) for f in range(-10, 280)]
    worst = max(abs(a - b) for a, b in zip(before, after))
    check(f"{kind}: still unchanged after a handle recalculation", worst < 1e-4, f"worst={worst}")

# ---------------------------------------------------------------------------
print("\n== 3. Rigify: generated human rig ==")
scene = reset()
try:
    bpy.ops.preferences.addon_enable(module="rigify")
    bpy.ops.object.armature_human_metarig_add()
    metarig = bpy.context.active_object
    started = time.perf_counter()
    bpy.ops.pose.rigify_generate()
    rig = bpy.context.active_object
    print(f"   generated {rig.name}: {len(rig.pose.bones)} bones in {time.perf_counter() - started:.1f} s")
    ok = rig is not None and rig != metarig and rig.type == 'ARMATURE'
except Exception as exc:  # Rigify missing from this Blender build
    print("   Rigify not available:", exc)
    ok = False
check("Rigify rig generated", ok)
if ok:
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='POSE')
    pb = rig.pose.bones
    controls = {
        "hand_ik.R": [("location", (0, 0, 0)), ("location", (0.2, -0.3, 0.4)), ("location", (-0.1, 0.2, 0.1))],
        "torso": [("location", (0, 0, 0)), ("location", (0.0, 0.3, -0.1)), ("location", (0.1, 0.0, 0.0))],
    }
    for name, keys in controls.items():
        for (prop, value), frame in zip(keys, (1, 20, 40)):
            setattr(pb[name], prop, value)
            pb[name].keyframe_insert(prop, frame=frame)
    fk = pb["upper_arm_fk.L"]
    fk.rotation_mode = 'QUATERNION'
    from mathutils import Quaternion
    for frame, angle in ((1, 0.0), (20, 0.8), (40, -0.4)):
        fk.rotation_quaternion = Quaternion((1, 0, 0), angle)
        fk.keyframe_insert("rotation_quaternion", frame=frame)
    if "upper_arm_parent.L" in pb and "IK_FK" in pb["upper_arm_parent.L"]:
        pb["upper_arm_parent.L"]["IK_FK"] = 1.0  # left arm in FK
    scene.frame_set(1)
    settings, prefs = scene.aemp_settings, M._prefs()
    settings.display_mode = 'SELECTED'
    for bone in pb:
        bone.select = bone.name in {"hand_ik.R", "torso", "hand_fk.L", "head", "foot_ik.L"}
    rig.data.bones.active = rig.data.bones["hand_ik.R"]
    targets = M._display_targets(bpy.context, settings)
    shown = {x.bone for x in targets}
    check("Rigify: every selected moving control is displayed",
          {"hand_ik.R", "torso", "hand_fk.L", "head"} <= shown, str(shown))
    check("Rigify: IK hand is editable", M._is_editable(M._Target(rig, "hand_ik.R")))
    check("Rigify: FK hand is view only", not M._is_editable(M._Target(rig, "hand_fk.L")))
    started = time.perf_counter()
    M._update_space(bpy.context, targets, settings, prefs, force=True)
    print(f"   evaluation of {len(targets)} paths: {(time.perf_counter() - started) * 1000:.0f} ms, "
          f"error={M._BAKE_INFO['error']!r}")
    for target in targets:
        exact(scene, target, f"Rigify {target.bone}", tol=2e-4)
    # editing the IK control lands where asked
    t = M._Target(rig, "hand_ik.R")
    data = M._build_path_cache(bpy.context, t)
    before = truth(scene, t, 20)
    delta = Vector((0.1, -0.05, 0.12))
    M._move_keys(t, {20.0: M._snapshot_key(t, 20.0)}, {20.0: data["handles"][20.0]["mapping"]}, delta)
    err = (truth(scene, t, 20) - before - delta).length
    scene.frame_set(1)
    check("Rigify: dragged IK key lands where asked", err < 3e-4, f"err={err}")
    # inserting on the FK upper arm keeps the whole rig pose
    frames = list(range(1, 41, 3))
    snap = pose_snapshot(scene, rig, frames)
    M._insert_key(M._Target(rig, "upper_arm_fk.L"), 11)
    M._insert_key(M._Target(rig, "torso"), 27)
    worst = pose_diff(snap, pose_snapshot(scene, rig, frames))
    check("Rigify: inserting keys keeps every bone of the rig in place", worst < 1e-4, f"worst={worst}")
    scene.frame_set(1)
    # metarig (not animated) shows nothing
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.context.view_layer.objects.active = metarig
    rig.select_set(False)
    metarig.select_set(True)
    shown = [x.key for x in M._display_targets(bpy.context, settings)]
    check("Rigify: still metarig is not displayed", shown == [], str(shown))

print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
