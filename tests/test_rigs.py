"""Headless tests: rig edge cases (IK, constraints, inherit options), sliding range, performance.

Run with:  pip install bpy==5.2.4  &&  python tests/test_rigs.py
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

import bpy
from mathutils import Vector

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


def truth(scene, target, frame):
    scene.frame_set(int(frame))
    obj = target.obj
    if target.bone:
        return (obj.matrix_world @ obj.pose.bones[target.bone].matrix).translation.copy()
    return obj.matrix_world.translation.copy()


def exact(scene, target, name, tol=1e-4):
    settings, prefs = scene.aemp_settings, M._prefs()
    M._update_space(bpy.context, [target], settings, prefs, force=True)
    data = M._build_path_cache(bpy.context, target)
    worst = max((w - truth(scene, target, f)).length for f, w in list(data["samples"]) + list(data["keys"]))
    scene.frame_set(1)
    check(f"{name}: path == evaluated motion", worst < tol, f"worst={worst} err={M._BAKE_INFO['error']}")
    return data


def edit_exact(scene, target, frame, name, tol=3e-4):
    data = M._build_path_cache(bpy.context, target)
    before = truth(scene, target, frame)
    delta = Vector((0.7, -0.4, 0.9))
    M._move_keys(target, {frame: M._snapshot_key(target, frame)}, {frame: data["handles"][frame]["mapping"]}, delta)
    err = (truth(scene, target, frame) - before - delta).length
    scene.frame_set(1)
    check(f"{name}: dragged key lands where asked", err < tol, f"err={err}")


def new_rig(scene, bones):
    """bones: [(name, head, tail, parent, kwargs)]"""
    arm = bpy.data.armatures.new("Arm")
    rig = bpy.data.objects.new("Rig", arm)
    scene.collection.objects.link(rig)
    bpy.context.view_layer.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    for name, head, tail, parent, kw in bones:
        eb = arm.edit_bones.new(name)
        eb.head, eb.tail = head, tail
        if parent:
            eb.parent = arm.edit_bones[parent]
        for k, v in kw.items():
            setattr(eb, k, v)
    bpy.ops.object.mode_set(mode='POSE')
    return rig


def key_loc(pb, keys):
    for f, l in keys:
        pb.location = l
        pb.keyframe_insert("location", frame=f)


def key_rot(pb, keys):
    pb.rotation_mode = 'XYZ'
    for f, r in keys:
        pb.rotation_euler = r
        pb.keyframe_insert("rotation_euler", frame=f)


LOC_KEYS = ((1, (0, 0, 0)), (12, (1, 2, 0.5)), (30, (-1, 1, 2)))
ROT_KEYS = ((1, (0, 0, 0)), (30, (0.8, -0.5, 2.0)))

# ---------------------------------------------------------------------------
print("\n== bone inherit options ==")
for label, kw in (
    ("inherit rotation off", {"use_inherit_rotation": False}),
    ("local location off", {"use_local_location": False}),
    ("inherit scale none", {"inherit_scale": 'NONE'}),
    ("inherit scale aligned", {"inherit_scale": 'ALIGNED'}),
):
    scene = reset()
    rig = new_rig(scene, [("root", (0, 0, 0), (0, 1, 0), None, {}),
                          ("ctrl", (1, 0, 1), (1.5, 0.3, 2), "root", kw)])
    key_rot(rig.pose.bones["root"], ROT_KEYS)
    for f, s in ((1, (1, 1, 1)), (30, (2, 0.5, 1.5))):
        rig.pose.bones["root"].scale = s
        rig.pose.bones["root"].keyframe_insert("scale", frame=f)
    key_loc(rig.pose.bones["ctrl"], LOC_KEYS)
    scene.frame_set(1)
    rig.data.bones.active = rig.data.bones["ctrl"]
    t = M._active_target(bpy.context)
    exact(scene, t, label)
    edit_exact(scene, t, 12.0, label)

# ---------------------------------------------------------------------------
print("\n== rig driven by constraints (parent follows another animated object) ==")
scene = reset()
driver_obj = bpy.data.objects.new("Driver", None)
scene.collection.objects.link(driver_obj)
for f, l, r in ((1, (0, 0, 0), (0, 0, 0)), (30, (3, 1, 0), (0.5, 0.2, 1.5))):
    driver_obj.location, driver_obj.rotation_euler = l, r
    driver_obj.keyframe_insert("location", frame=f); driver_obj.keyframe_insert("rotation_euler", frame=f)
rig = new_rig(scene, [("root", (0, 0, 0), (0, 1, 0), None, {}),
                      ("ctrl", (1, 0, 1), (1, 0, 2), "root", {})])
con = rig.pose.bones["root"].constraints.new('COPY_TRANSFORMS')
con.target = driver_obj
key_loc(rig.pose.bones["ctrl"], LOC_KEYS)
scene.frame_set(1)
rig.data.bones.active = rig.data.bones["ctrl"]
t = M._active_target(bpy.context)
exact(scene, t, "constrained parent bone")
edit_exact(scene, t, 12.0, "constrained parent bone")

print("\n== IK: the control drives a chain, the control path stays exact ==")
scene = reset()
rig = new_rig(scene, [("upper", (0, 0, 0), (0, 0, 1), None, {}),
                      ("lower", (0, 0, 1), (0, 0, 2), "upper", {"use_connect": True}),
                      ("ik", (0, 0.2, 2), (0, 0.2, 2.5), None, {})])
con = rig.pose.bones["lower"].constraints.new('IK')
con.target, con.subtarget, con.chain_count = rig, "ik", 2
key_loc(rig.pose.bones["ik"], LOC_KEYS)
scene.frame_set(1)
rig.data.bones.active = rig.data.bones["ik"]
t = M._active_target(bpy.context)
exact(scene, t, "IK control")
edit_exact(scene, t, 12.0, "IK control")

# ---------------------------------------------------------------------------
print("\n== objects: bone parent, constraint on an unparented object ==")
scene = reset()
rig = new_rig(scene, [("root", (0, 0, 0), (0, 1, 0), None, {})])
key_rot(rig.pose.bones["root"], ROT_KEYS)
key_loc(rig.pose.bones["root"], ((1, (0, 0, 0)), (30, (2, 0, 0))))
bpy.ops.object.mode_set(mode='OBJECT')
prop = bpy.data.objects.new("Prop", None)
scene.collection.objects.link(prop)
prop.parent, prop.parent_type, prop.parent_bone = rig, 'BONE', "root"
for f, l in LOC_KEYS:
    prop.location = l
    prop.keyframe_insert("location", frame=f)
rig.select_set(False)
bpy.context.view_layer.objects.active = prop
prop.select_set(True)
scene.frame_set(1)
t = M._active_target(bpy.context)
exact(scene, t, "object parented to a bone")
edit_exact(scene, t, 12.0, "object parented to a bone")

scene = reset()
target_obj = bpy.data.objects.new("Target", None)
cam = bpy.data.objects.new("Cam", None)
for o in (target_obj, cam):
    scene.collection.objects.link(o)
con = cam.constraints.new('TRACK_TO')
con.target = target_obj
for f, l in LOC_KEYS:
    cam.location = l
    cam.keyframe_insert("location", frame=f)
bpy.context.view_layer.objects.active = cam
cam.select_set(True)
scene.frame_set(1)
t = M._active_target(bpy.context)
check("constrained object is baked", M._needs_bake(t))
exact(scene, t, "object with a Track To constraint")
edit_exact(scene, t, 12.0, "object with a Track To constraint")

print("\n== partial channels + fractional key ==")
scene = reset()
ob = bpy.data.objects.new("Partial", None)
scene.collection.objects.link(ob)
ob.location = (0, 5, 0)
for f, x in ((1, 0.0), (10.5, 2.0), (20, 1.0)):
    ob.location.x = x
    ob.keyframe_insert("location", index=0, frame=f)
bpy.context.view_layer.objects.active = ob
scene.frame_set(1)
t = M._active_target(bpy.context)
data = M._build_path_cache(bpy.context, t)
check("fractional key kept", any(abs(f - 10.5) < 1e-4 for f, _ in data["keys"]))
check("un-animated channel keeps its value", all(abs(w.y - 5.0) < 1e-5 for _, w in data["samples"]))

# ---------------------------------------------------------------------------
print("\n== sliding range (Around Frame) re-uses baked frames ==")
scene = reset()
rig = new_rig(scene, [("root", (0, 0, 0), (0, 1, 0), None, {}), ("ctrl", (1, 0, 1), (1, 0, 2), "root", {})])
key_rot(rig.pose.bones["root"], ((1, (0, 0, 0)), (200, (0.8, -0.5, 6.0))))
key_loc(rig.pose.bones["ctrl"], ((1, (0, 0, 0)), (100, (1, 2, 0.5)), (200, (-1, 1, 2))))
rig.data.bones.active = rig.data.bones["ctrl"]
scene.frame_set(100)
settings, prefs = scene.aemp_settings, M._prefs()
settings.range_mode = 'WINDOW'
t = M._active_target(bpy.context)
M._update_space(bpy.context, [t], settings, prefs, force=True)
version = M._SPACE_VERSION
worst = 0.0
for frame in range(101, 121):
    scene.frame_set(frame)
    time.sleep(0.21)
    M._update_space(bpy.context, [t], settings, prefs)
    data = M._build_path_cache(bpy.context, t)
    check_frames = list(data["samples"])
    for f, w in check_frames[::8]:
        worst = max(worst, (w - truth(scene, t, f)).length)
    scene.frame_set(frame)
check("stepping 20 frames needs no new bake", M._SPACE_VERSION == version, f"{M._SPACE_VERSION - version} bakes")
check("sliding range stays exact", worst < 1e-4, f"worst={worst}")
scene.frame_set(190)
time.sleep(0.21)
M._update_space(bpy.context, [t], settings, prefs)
data = M._build_path_cache(bpy.context, t)
worst = max((w - truth(scene, t, f)).length for f, w in data["samples"])
check("jumping far re-bakes and stays exact", worst < 1e-4 and M._SPACE_VERSION > version, f"worst={worst}")

print("\n== performance: 400-bone rig, 250 frames ==")
scene = reset()
bones = [("root", (0, 0, 0), (0, 1, 0), None, {})]
for i in range(399):
    parent = "root" if i % 20 == 0 else f"b{i - 1}"
    bones.append((f"b{i}", (i * 0.01, 0, 1 + (i % 20) * 0.1), (i * 0.01, 0, 1.1 + (i % 20) * 0.1), parent, {}))
rig = new_rig(scene, bones)
key_rot(rig.pose.bones["root"], ((1, (0, 0, 0)), (250, (0.5, 0.2, 3.0))))
for i in range(0, 399, 3):
    key_rot(rig.pose.bones[f"b{i}"], ((1, (0, 0, 0)), (125, (0.3, 0.1, 0.2)), (250, (0, 0, 0))))
for i in range(0, 399, 40):
    key_loc(rig.pose.bones[f"b{i}"], ((1, (0, 0, 0)), (100, (1, 1, 0)), (250, (0, 2, 1))))
scene.frame_set(1)
rig.data.bones.active = rig.data.bones["b40"]
t = M._active_target(bpy.context)
settings, prefs = scene.aemp_settings, M._prefs()
start = time.perf_counter()
M._update_space(bpy.context, [t], settings, prefs, force=True)
bake_ms = (time.perf_counter() - start) * 1000
print(f"   bake: {M._BAKE_INFO['frames']} frames in {bake_ms:.0f} ms ({len(M._SPACE)} bones pre-warmed)")
check("bake of a 400-bone rig stays under 3 s", bake_ms < 3000, f"{bake_ms:.0f} ms")
M._build_path_cache(bpy.context, t)
start = time.perf_counter()
for _ in range(30):
    M._live_update_timer()
tick_ms = (time.perf_counter() - start) * 1000 / 30
print(f"   idle timer tick: {tick_ms:.2f} ms")
check("idle timer tick under 3 ms", tick_ms < 3.0, f"{tick_ms:.2f} ms")
start = time.perf_counter()
for _ in range(30):
    M._build_path_cache(bpy.context, t)
build_ms = (time.perf_counter() - start) * 1000 / 30
print(f"   path rebuild during a drag: {build_ms:.2f} ms")
check("path rebuild under 8 ms", build_ms < 8.0, f"{build_ms:.2f} ms")
rig.data.bones.active = rig.data.bones["b80"]
t2 = M._active_target(bpy.context)
start = time.perf_counter()
M._update_space(bpy.context, [t2], settings, prefs, force=False)
switch_ms = (time.perf_counter() - start) * 1000
print(f"   switching to another control: {switch_ms:.1f} ms")
check("switching controls needs no new bake", switch_ms < 50, f"{switch_ms:.1f} ms")
start = time.perf_counter()
token = M._mapping_token(t, M._live_mapping(t))
print(f"   animation fingerprint: {(time.perf_counter() - start) * 1000:.2f} ms")

# ---------------------------------------------------------------------------
print("\n== API checks ==")
icons = {i.identifier for i in bpy.types.UILayout.bl_rna.functions["label"].parameters["icon"].enum_items}
import inspect, re
used_icons = set(re.findall(r"icon='([A-Z_0-9]+)'", inspect.getsource(M)))
check("every icon exists in this Blender", used_icons <= icons, str(used_icons - icons))
try:
    bpy.context.preferences.view.language = 'fr_FR'
    bpy.context.preferences.view.use_translate_interface = True
    fr = bpy.app.translations.pgettext_iface("Show Path")
    fr_op = bpy.app.translations.pgettext_iface("Add Key on Path", "Operator")
    print("   French:", repr(fr), "|", repr(fr_op))
    check("French translation is picked up by Blender", fr == "Afficher la trajectoire" and fr_op == "Ajouter une clé sur la trajectoire")
    bpy.context.preferences.view.language = 'en_US'
    check("English stays English", bpy.app.translations.pgettext_iface("Show Path") == "Show Path")
except Exception as exc:
    print("   translation check skipped:", exc)

print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
