# SPDX-License-Identifier: GPL-3.0-or-later
"""Editable Motion Paths: edit Location motion paths directly in the 3D View.

Works on objects and on pose bones. F-Curves stay the only source of truth:
the add-on never creates hidden curve objects or constraints.
"""

import math
import time
from array import array
from bisect import bisect_left, bisect_right
from types import SimpleNamespace

import blf
import bpy
import gpu
from bpy.app.handlers import persistent
from bpy.app.translations import pgettext_iface as iface_
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    PointerProperty,
)
from bpy.types import AddonPreferences, Gizmo, GizmoGroup, Menu, Operator, Panel, PropertyGroup
from bpy_extras import view3d_utils
from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from .translations import TRANSLATIONS

# -----------------------------------------------------------------------------
# Runtime state
# -----------------------------------------------------------------------------

_ADDON_ID = __package__ or __name__

_DRAW_HANDLE = None
_DRAW_HANDLE_2D = None
_ADDON_KEYMAPS = []
_TIMER_INTERVAL = 0.033  # ~30 Hz: cheap F-Curve evaluation only.

# Path display cache: target key -> path data. Target keys are name based
# ((object name, bone name)) so caches survive undo/redo.
_PATH_CACHE = {}
_CACHE_SIGNATURES = {}
_CACHE_DIRTY = True
_IS_BUILDING = False

# Parent-space cache ("space"): for targets whose parent space can change over
# time (bones, parented or constrained objects) we store, per frame, the affine
# map from the animated local Location to the evaluated world position.
#   target key -> {"map": {frame: (A, b)}, "frames": [sorted], ...}
_SPACE = {}
_SPACE_VERSION = 0
_IS_BAKING = False
_LAST_BAKE_TIME = 0.0
_BAKE_INFO = {"frames": 0, "ms": 0.0, "error": ""}
_BAKE_DEBOUNCE = 0.2
_BAKE_SCENE_NAME = ".editable_motion_paths_bake"
_MAX_PREWARM_BONES = 64
_MAX_DISPLAYED_BONES = 64

# Per-object index of the animation (keyed frames, checksums), rebuilt lazily
# and dropped at every timer tick and after every edit.
_RIG_INDEX = {}

# Point of the path under the mouse (hover insertion), shared with the 2D draw.
_HOVER = {"key": None, "frame": None, "world": None}

# True while one of our own gizmos/operators is dragging.
_EDITING = False
_TIMER_ERROR_SHOWN = False

# Current viewport-edit selection. Runtime UI state only; animation data
# remains entirely in Blender F-Curves.
_EDIT_SELECTION = {"key": None, "frame": None, "part": "NONE"}  # part: NONE, KEY, LEFT, RIGHT
_MULTI_SELECTION = set()  # {(object name, bone name, frame)}

_UNIT_AXES = (Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0)))
_BUSY_OPERATOR_PREFIXES = (
    "TRANSFORM_OT_", "VIEW3D_OT_", "GIZMOGROUP_OT_", "POSE_OT_", "ANIM_OT_", "GRAPH_OT_", "AEMP_OT_",
)


def _tag_redraw_all_view3d():
    wm = bpy.context.window_manager
    if not wm:
        return
    for win in wm.windows:
        screen = win.screen
        if not screen:
            continue
        for area in screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# -----------------------------------------------------------------------------
# Targets: an object, or one pose bone of an armature
# -----------------------------------------------------------------------------

class _Target:
    """What a motion path belongs to. Short lived: never keep one across events."""

    __slots__ = ("obj", "bone")

    def __init__(self, obj, bone=""):
        self.obj = obj
        self.bone = bone or ""

    @property
    def key(self):
        return (self.obj.name, self.bone)

    @property
    def pose_bone(self):
        if not self.bone or self.obj.pose is None:
            return None
        return self.obj.pose.bones.get(self.bone)

    @property
    def data_path(self):
        if self.bone:
            return 'pose.bones["%s"].location' % bpy.utils.escape_identifier(self.bone)
        return "location"

    @property
    def location(self):
        """Live local Location (unkeyed changes included)."""
        pose_bone = self.pose_bone
        if pose_bone is not None:
            return Vector(pose_bone.location)
        return Vector(self.obj.location)

    @property
    def label(self):
        return f"{self.bone} ({self.obj.name})" if self.bone else self.obj.name

    @property
    def prefix(self):
        """Prefix of the F-Curve data paths of this target."""
        if self.bone:
            return 'pose.bones["%s"].' % bpy.utils.escape_identifier(self.bone)
        return ""

    @property
    def rotation_path(self):
        owner = self.pose_bone or self.obj
        mode = owner.rotation_mode
        if mode == 'QUATERNION':
            return "rotation_quaternion"
        if mode == 'AXIS_ANGLE':
            return "rotation_axis_angle"
        return "rotation_euler"

    @property
    def is_connected_bone(self):
        """Connected bones ignore their Location: there is nothing to edit."""
        pose_bone = self.pose_bone
        return bool(pose_bone and pose_bone.parent and pose_bone.bone.use_connect)

    def is_valid(self):
        try:
            if self.obj is None or self.obj.name not in bpy.data.objects:
                return False
            return not self.bone or self.pose_bone is not None
        except ReferenceError:
            return False

    def keyframe_insert(self, frame, data_path="location"):
        pose_bone = self.pose_bone
        if pose_bone is not None:
            return pose_bone.keyframe_insert(data_path=data_path, frame=frame, group=self.bone)
        return self.obj.keyframe_insert(data_path=data_path, frame=frame, group="Object Transforms")


def _target_from_key(key):
    if not key:
        return None
    obj = bpy.data.objects.get(key[0])
    if obj is None:
        return None
    target = _Target(obj, key[1])
    return target if target.is_valid() else None


def _active_object(context):
    return getattr(context, "active_object", None)


def _in_pose_mode(obj):
    return obj is not None and obj.type == 'ARMATURE' and obj.mode == 'POSE'


def _active_target(context):
    obj = _active_object(context)
    if obj is None:
        return None
    if _in_pose_mode(obj):
        bone = obj.data.bones.active
        if bone is None or obj.pose.bones.get(bone.name) is None:
            return None
        return _Target(obj, bone.name)
    return _Target(obj)


def _selected_bones(obj):
    """Selected pose bones of an armature, in every mode (selection is kept on the pose bones)."""
    if obj is None or obj.type != 'ARMATURE' or obj.pose is None:
        return []
    return [pb.name for pb in obj.pose.bones if getattr(pb, "select", False)]


def _selected_objects(context):
    try:
        return list(context.selected_objects or ())
    except AttributeError:
        return []


# -----------------------------------------------------------------------------
# Animation access (layered Actions / slots)
# -----------------------------------------------------------------------------

def _channelbag(obj):
    animation_data = obj.animation_data
    if animation_data is None or animation_data.action is None or animation_data.action_slot is None:
        return None
    return animdata_get_channelbag_for_assigned_slot(animation_data)


def _location_fcurves(target):
    """Return {axis: F-Curve} for the target's Location channels."""
    channelbag = _channelbag(target.obj)
    if channelbag is None:
        return {}
    data_path = target.data_path
    result = {}
    for axis in range(3):
        fcurve = channelbag.fcurves.find(data_path, index=axis)
        if fcurve is not None:
            result[axis] = fcurve
    return result


def _location_keyframes(target, curves=None):
    frames = set()
    for fcurve in (curves if curves is not None else _location_fcurves(target)).values():
        for keyframe in fcurve.keyframe_points:
            frames.add(float(keyframe.co.x))
    return sorted(frames)


_TRANSFORM_PROPS = ("location", "rotation_euler", "rotation_quaternion", "rotation_axis_angle", "scale")
_BONE_PATH_START = 'pose.bones["'


def _split_path(data_path):
    """('bone name' or '', property) for a transform F-Curve path, or None."""
    if data_path in _TRANSFORM_PROPS:
        return "", data_path
    if data_path.startswith(_BONE_PATH_START) and '"].' in data_path:
        head, prop = data_path.rsplit('"].', 1)
        if prop in _TRANSFORM_PROPS:
            return head[len(_BONE_PATH_START):].replace('\\"', '"').replace('\\\\', '\\'), prop
    return None


def _rig_index(obj):
    """Index of the animation of ``obj``: keyed frames per owner and checksums per path."""
    index = _RIG_INDEX.get(obj.name)
    if index is not None:
        return index
    frames = {}
    sums = {}
    total = [0, 0.0]
    channelbag = _channelbag(obj)
    if channelbag is not None:
        for fcurve in channelbag.fcurves:
            size = len(fcurve.keyframe_points)
            if not size:
                continue
            buffer = array('f', bytes(8 * size))
            fcurve.keyframe_points.foreach_get("co", buffer)
            handles = array('f', bytes(8 * size))
            fcurve.keyframe_points.foreach_get("handle_right", handles)
            checksum = sum(buffer) + 0.5 * sum(handles) + (0.25 if fcurve.mute else 0.0)
            path = fcurve.data_path
            count, value = sums.get(path, (0, 0.0))
            sums[path] = (count + size, value + checksum)
            total[0] += size
            total[1] += checksum
            split = _split_path(path)
            if split is not None:
                frames.setdefault(split[0], set()).update(buffer[0::2])
    index = _RIG_INDEX[obj.name] = {"frames": frames, "sums": sums, "total": tuple(total)}
    return index


def _own_key_frames(target):
    """Frames keyed on any transform channel of the target itself."""
    return sorted(_rig_index(target.obj)["frames"].get(target.bone, ()))


def _driving_frames(target):
    """Frames keyed on anything that moves the target: itself, parent bones, objects."""
    frames = set()
    obj = target.obj
    frames.update(_rig_index(obj)["frames"].get(target.bone, ()))
    pose_bone = target.pose_bone
    if pose_bone is not None:
        index = _rig_index(obj)["frames"]
        parent = pose_bone.parent
        while parent is not None:
            frames.update(index.get(parent.name, ()))
            parent = parent.parent
        frames.update(index.get("", ()))
    depth = 0
    parent_obj = obj.parent
    while parent_obj is not None and depth < 8:
        for owner_frames in _rig_index(parent_obj)["frames"].values():
            frames.update(owner_frames)
        parent_obj = parent_obj.parent
        depth += 1
    return sorted(frames)


def _has_constraints(target):
    pose_bone = target.pose_bone
    while pose_bone is not None:
        if any(not c.mute for c in pose_bone.constraints):
            return True
        pose_bone = pose_bone.parent
    obj = target.obj
    depth = 0
    while obj is not None and depth < 8:
        if any(not c.mute for c in obj.constraints):
            return True
        obj = obj.parent
        depth += 1
    return False


def _target_checksum(target):
    """Fingerprint of everything that moves the target, except its own Location keys.

    Its own Location keys are excluded because editing them does not change the
    parent space: dragging a key must not trigger a new evaluation.
    """
    count = 0
    value = 0.0
    obj = target.obj
    depth = 0
    while obj is not None and depth < 8:
        index = _rig_index(obj)
        count += index["total"][0]
        value += index["total"][1]
        obj = obj.parent
        depth += 1
    own_count, own_value = _rig_index(target.obj)["sums"].get(target.data_path, (0, 0.0))
    return count - own_count, round(value - own_value, 4)


def _is_editable(target):
    """Keys of the path can be dragged: the target has Location keys."""
    if target is None or not target.is_valid() or target.is_connected_bone or target.obj.mode == 'EDIT':
        return False
    return bool(_location_fcurves(target))


def _is_displayable(target):
    """The target moves: it has a path to show."""
    if target is None or not target.is_valid():
        return False
    if not target.is_connected_bone and _location_fcurves(target):
        return True
    if not _needs_bake(target):
        return False
    return bool(_driving_frames(target)) or _has_constraints(target)




def _keypoint_at_frame(fcurve, frame, epsilon=0.001):
    for keyframe in fcurve.keyframe_points:
        if abs(float(keyframe.co.x) - float(frame)) <= epsilon:
            return keyframe
    return None


def _eval_location(target, curves, frame):
    """Local Location at ``frame``. Channels without an F-Curve keep their live value."""
    location = target.location
    for axis in range(3):
        fcurve = curves.get(axis)
        if fcurve is not None:
            location[axis] = fcurve.evaluate(frame)
    return location


def _anim_checksum(obj):
    """Cheap fingerprint of the animation driving ``obj`` and its parents."""
    count = 0
    total = 0.0
    depth = 0
    while obj is not None and depth < 8:
        channelbag = _channelbag(obj)
        if channelbag is not None:
            for fcurve in channelbag.fcurves:
                size = len(fcurve.keyframe_points)
                if not size:
                    continue
                buffer = array('f', bytes(8 * size))
                fcurve.keyframe_points.foreach_get("co", buffer)
                count += size
                total += sum(buffer)
        obj = obj.parent
        depth += 1
    return count, round(total, 4)


# -----------------------------------------------------------------------------
# Selection state
# -----------------------------------------------------------------------------

def _deselect_location_keys(target):
    for fcurve in _location_fcurves(target).values():
        for keyframe in fcurve.keyframe_points:
            keyframe.select_control_point = False
            keyframe.select_left_handle = False
            keyframe.select_right_handle = False


def _select_location_key_at_frame(target, frame, part='KEY', clear=True):
    if clear:
        _deselect_location_keys(target)
    for fcurve in _location_fcurves(target).values():
        keyframe = _keypoint_at_frame(fcurve, frame)
        if keyframe is None:
            continue
        if part == 'KEY':
            keyframe.select_control_point = True
        elif part == 'LEFT':
            keyframe.select_left_handle = True
        elif part == 'RIGHT':
            keyframe.select_right_handle = True


def _set_edit_selection(target, frame=None, part='NONE', extend=False, toggle=False):
    global _MULTI_SELECTION
    key = target.key if target else None
    frame_value = float(frame) if frame is not None else None

    if target is None or frame_value is None:
        _MULTI_SELECTION.clear()
    elif part == 'KEY':
        token = (key[0], key[1], frame_value)
        if toggle:
            if token in _MULTI_SELECTION:
                _MULTI_SELECTION.remove(token)
            else:
                _MULTI_SELECTION.add(token)
        elif extend:
            _MULTI_SELECTION.add(token)
        else:
            _MULTI_SELECTION = {token}
    elif not extend:
        # Handles remain a single active edit target.
        _MULTI_SELECTION = {(key[0], key[1], frame_value)}

    _EDIT_SELECTION["key"] = key
    _EDIT_SELECTION["frame"] = frame_value
    _EDIT_SELECTION["part"] = part
    if target and frame_value is not None:
        _select_location_key_at_frame(target, frame_value, part, clear=not extend)
    _tag_redraw_all_view3d()


def _is_multi_selected(key, frame):
    return (key[0], key[1], float(frame)) in _MULTI_SELECTION


def _selected_frames(target):
    key = target.key
    return sorted(frame for name, bone, frame in _MULTI_SELECTION if (name, bone) == key)


def _selection_matches(target):
    return bool(target and _EDIT_SELECTION["key"] == target.key and _EDIT_SELECTION["frame"] is not None)


def _display_targets(context, settings):
    """Paths to show: the active target first, then the others.

    Armatures show the paths of their selected bones in every mode; in Object
    and Edit Mode the object path is shown too when the object moves.
    """
    result = []
    seen = set()

    def add(target):
        if target.key not in seen and _is_displayable(target):
            seen.add(target.key)
            result.append(target)

    active = _active_target(context)
    if active is not None:
        add(active)
    active_obj = _active_object(context)
    owners = [active_obj] if active_obj is not None else []
    if settings.display_mode == 'SELECTED':
        owners += [o for o in _selected_objects(context) if o != active_obj]
    for obj in owners:
        if obj.type == 'ARMATURE' and obj.pose is not None:
            names = _selected_bones(obj)
            if settings.display_mode == 'ACTIVE' and obj == active_obj:
                active_bone = obj.data.bones.active
                if active_bone is None:
                    # No active bone (typical after an import): show the root
                    # bones, which carry the global motion of the character.
                    names = [b.name for b in obj.data.bones if b.parent is None]
                else:
                    names = [active_bone.name] if active_bone.name in names else []
            for name in names[:_MAX_DISPLAYED_BONES]:
                add(_Target(obj, name))
        if not _in_pose_mode(obj):
            add(_Target(obj))
    return result


# -----------------------------------------------------------------------------
# Parent space: mapping local Location -> evaluated world position
# -----------------------------------------------------------------------------

def _probe(obj, bone, tail=False):
    """Return (A, world, local) for an object or one of its pose bones.

    ``A`` is the 3x3 linear map from a change of local Location to the matching
    change of world position. ``world`` is the evaluated world position (bone
    head or tail, or object origin) and ``local`` the Location it was evaluated
    with. A Location change moves the whole bone, so ``A`` is the same for the
    head and the tail. Works on original and on evaluated data-blocks.
    """
    if bone:
        pose_bone = obj.pose.bones.get(bone) if obj.pose else None
        if pose_bone is None:
            return None
        rest = pose_bone.bone
        parent = pose_bone.parent
        if parent is not None:
            def to_pose(matrix):
                return rest.convert_local_to_pose(
                    matrix, rest.matrix_local,
                    parent_matrix=parent.matrix, parent_matrix_local=parent.bone.matrix_local)
        else:
            def to_pose(matrix):
                return rest.convert_local_to_pose(matrix, rest.matrix_local)
        origin = to_pose(Matrix.Identity(4)).translation
        columns = [to_pose(Matrix.Translation(axis)).translation - origin for axis in _UNIT_AXES]
        pose_linear = Matrix(columns).transposed()
        matrix_world = obj.matrix_world
        return (
            matrix_world.to_3x3() @ pose_linear,
            matrix_world @ (Vector(pose_bone.tail) if tail else pose_bone.matrix.translation),
            Vector(pose_bone.location),
        )

    parent = obj.parent
    if parent is None:
        linear = Matrix.Identity(3)
    elif obj.parent_type == 'BONE' and parent.pose and obj.parent_bone in parent.pose.bones:
        parent_bone = parent.pose.bones[obj.parent_bone]
        linear = (parent.matrix_world @ parent_bone.matrix @ obj.matrix_parent_inverse).to_3x3()
    elif obj.parent_type in {'OBJECT', 'ARMATURE', 'LATTICE'}:
        linear = (parent.matrix_world @ obj.matrix_parent_inverse).to_3x3()
    else:
        linear = (obj.matrix_world @ obj.matrix_basis.inverted_safe()).to_3x3()
    return linear, obj.matrix_world.translation.copy(), Vector(obj.location)


def _use_tail(target):
    return bool(target.bone) and _prefs().path_point == 'TAIL'


def _live_mapping(target):
    """Mapping (A, b) from the current evaluated state: world = A @ local + b."""
    probe = _probe(target.obj, target.bone, _use_tail(target))
    if probe is None:
        return Matrix.Identity(3), Vector((0.0, 0.0, 0.0))
    linear, world, local = probe
    return linear, world - linear @ local


def _local_to_world(local, mapping):
    linear, offset = mapping
    return offset + (linear @ Vector(local))


def _world_to_local(world, mapping):
    linear, offset = mapping
    return linear.inverted_safe() @ (Vector(world) - offset)


def _needs_bake(target):
    """Static, unparented objects are exact without baking their parent space."""
    if target.bone:
        return True
    obj = target.obj
    if obj.parent is not None:
        return True
    return any(not constraint.mute for constraint in obj.constraints)


def _space_entry(key):
    entry = _SPACE.get(key)
    if entry is None:
        entry = _SPACE[key] = {
            "map": {}, "frames": [], "strikes": 0, "bad": None, "next_check": 0.0,
            "failed": False, "stale": False,
        }
    return entry


def _space_map(key, frame):
    """Baked mapping at ``frame`` (nearest baked frame when not exact), or None."""
    entry = _SPACE.get(key)
    if not entry or not entry["map"]:
        return None
    mapping = entry["map"].get(frame)
    if mapping is not None:
        return mapping
    frames = entry["frames"]
    index = bisect_left(frames, frame)
    nearest = min(frames[max(0, index - 1):index + 1], key=lambda f: abs(f - frame))
    return entry["map"][nearest]


def _clear_space(keys=None):
    global _SPACE_VERSION
    if keys is None:
        _SPACE.clear()
    else:
        owners = {key[0] for key in keys}
        for key in [k for k in _SPACE if k[0] in owners]:
            _SPACE.pop(key, None)
    _SPACE_VERSION += 1


def _maps_differ(first, second):
    linear_a, offset_a = first
    linear_b, offset_b = second
    scale = max(1.0, max(abs(v) for row in linear_a for v in row))
    for row_a, row_b in zip(linear_a, linear_b):
        for value_a, value_b in zip(row_a, row_b):
            if abs(value_a - value_b) > 1.0e-4 * scale:
                return True
    return (offset_a - offset_b).length > 1.0e-4 * max(1.0, offset_a.length)


def _mapping_token(target, mapping):
    linear, offset = mapping
    return (
        tuple(round(v, 4) for row in linear for v in row),
        tuple(round(v, 4) for v in offset),
        _anim_checksum(target.obj),
    )


def _prewarm_targets(targets):
    """Add the other Location-animated bones of the same armatures.

    Evaluating the rig is the expensive part of a bake; reading a few more bones
    is nearly free and makes switching between controls instant.
    """
    result = {target.key: target for target in targets}
    for obj in {target.obj for target in targets if target.bone}:
        channelbag = _channelbag(obj)
        if channelbag is None or obj.pose is None:
            continue
        added = 0
        for fcurve in channelbag.fcurves:
            path = fcurve.data_path
            if not (path.startswith('pose.bones["') and path.endswith('"].location')):
                continue
            try:
                pose_bone = obj.path_resolve(path[:-len(".location")])
            except ValueError:
                continue
            target = _Target(obj, pose_bone.name)
            if target.key in result or target.is_connected_bone:
                continue
            result[target.key] = target
            added += 1
            if added >= _MAX_PREWARM_BONES:
                break
    return list(result.values())


def _bake_space(targets, frames):
    """Evaluate the parent space of ``targets`` at ``frames``.

    The evaluation happens in a temporary scene with its own dependency graph,
    so the user's scene never changes frame and unkeyed poses are not lost.
    """
    global _IS_BAKING, _SPACE_VERSION, _LAST_BAKE_TIME
    targets = [t for t in targets if t.is_valid()]
    frames = sorted(set(frames))
    if not targets or not frames or _IS_BAKING:
        return False

    started = time.perf_counter()
    curves = {target.key: _location_fcurves(target) for target in targets}
    tails = {target.key: _use_tail(target) for target in targets}
    owners = []
    for target in targets:
        if target.obj not in owners:
            owners.append(target.obj)

    _IS_BAKING = True
    _BAKE_INFO["error"] = ""
    results = {target.key: {} for target in targets}
    bake_scene = None
    try:
        bake_scene = bpy.data.scenes.new(_BAKE_SCENE_NAME)
        for obj in owners:
            bake_scene.collection.objects.link(obj)
        view_layer = bake_scene.view_layers[0]
        for frame in frames:
            whole = int(math.floor(frame))
            bake_scene.frame_set(whole, subframe=frame - whole)
            depsgraph = view_layer.depsgraph
            for target in targets:
                probe = _probe(target.obj.evaluated_get(depsgraph), target.bone, tails[target.key])
                if probe is None:
                    continue
                linear, world, _local = probe
                local = _eval_location(target, curves[target.key], frame)
                results[target.key][frame] = (linear.copy(), world - linear @ local)
    except Exception as exc:  # Never let a bake failure break the viewport.
        _BAKE_INFO["error"] = str(exc)
        results = None
    finally:
        if bake_scene is not None:
            try:
                bpy.data.scenes.remove(bake_scene)
            except (ReferenceError, RuntimeError):
                pass
        _IS_BAKING = False
        _LAST_BAKE_TIME = time.monotonic()

    if results is None:
        for target in targets:
            _space_entry(target.key)["failed"] = True
        return False

    for target in targets:
        entry = _space_entry(target.key)
        entry["map"].update(results[target.key])
        entry["frames"] = sorted(entry["map"])
        entry["strikes"] = 0
        entry["failed"] = False
        entry["stale"] = False
        entry["anim"] = _target_checksum(target)
    _SPACE_VERSION += 1
    _BAKE_INFO["frames"] = len(frames)
    _BAKE_INFO["ms"] = (time.perf_counter() - started) * 1000.0
    return True


def _is_busy():
    """True while baking would get in the user's way."""
    global _EDITING
    if _IS_BAKING:
        return True
    wm = bpy.context.window_manager
    if not wm:
        return True
    if _EDITING:
        if any(len(getattr(win, "modal_operators", ())) for win in wm.windows):
            return True
        _EDITING = False  # The drag ended without telling us.
    try:
        if bpy.app.is_job_running('RENDER'):
            return True
    except (AttributeError, TypeError, ValueError):
        pass
    for win in wm.windows:
        screen = win.screen
        if screen and (screen.is_animation_playing or getattr(screen, "is_scrubbing", False)):
            return True
        for operator in getattr(win, "modal_operators", ()):
            if operator.bl_idname.startswith(_BUSY_OPERATOR_PREFIXES):
                return True
    return False


def _needed_frames(context, target, settings, prefs, padded=False):
    """Frames whose parent space is needed to display ``target``.

    ``padded`` widens a sliding range, so stepping through frames does not
    trigger a new bake at every frame.
    """
    sampled = _sample_frames(context, target, settings, prefs)
    if sampled is None:
        return set()
    start, end, frames = sampled
    needed = set(frames)
    needed.update(_marker_frames(target, start, end))
    if padded and settings.range_mode == 'WINDOW':
        step = _sample_step(start, end, prefs)
        pad = max(24, settings.frames_before + settings.frames_after)
        first = int(math.ceil((start - pad) / step)) * step
        needed.update(float(f) for f in range(first, end + pad + 1, step))
    return needed


def _update_space(context, targets, settings, prefs, force=False):
    """Keep the parent-space cache of the displayed targets valid."""
    # Edit Mode shows the rest pose: nothing can be evaluated, the last
    # evaluation is kept.
    bake_targets = [t for t in targets if _needs_bake(t) and t.obj.mode != 'EDIT']
    if not bake_targets:
        return
    scene = context.scene
    frame = float(scene.frame_current) + float(scene.frame_subframe)
    now = time.monotonic()
    busy = _is_busy()

    # 1. Detect a parent space that changed since the bake, by comparing the
    #    baked mapping of the current frame with the live one.
    if not busy and not force:
        stale = []
        for target in bake_targets:
            entry = _SPACE.get(target.key)
            if not entry or not entry["map"]:
                continue
            # Keys changed anywhere in the animation that moves the target.
            if entry.get("anim") is not None and _target_checksum(target) != entry["anim"]:
                if prefs.auto_update:
                    stale.append(target.key)
                elif not entry["stale"]:
                    entry["stale"] = True
                    _tag_redraw_all_view3d()
                continue
            if frame not in entry["map"]:
                continue
            live = _live_mapping(target)
            if not _maps_differ(entry["map"][frame], live):
                entry["strikes"] = 0
                entry["bad"] = None
                continue
            if now < entry["next_check"]:
                continue
            entry["next_check"] = now + 0.25
            token = _mapping_token(target, live)
            if token == entry["bad"]:
                continue  # Known difference (e.g. an unkeyed pose): nothing new to bake.
            entry["strikes"] += 1
            if entry["strikes"] >= 2:
                if prefs.auto_update:
                    stale.append(target.key)
                elif not entry["stale"]:
                    entry["stale"] = True
                    _tag_redraw_all_view3d()
        if stale:
            _clear_space(stale)

    # 2. Bake what is missing.
    missing = set()
    for target in bake_targets:
        entry = _SPACE.get(target.key)
        if entry and entry["failed"] and not force:
            continue
        baked = set(entry["map"]) if entry else set()
        if _needed_frames(context, target, settings, prefs) - baked:
            missing.update(_needed_frames(context, target, settings, prefs, padded=True) - baked)
    if not missing:
        return
    if not force and (busy or not prefs.auto_update or now - _LAST_BAKE_TIME < _BAKE_DEBOUNCE):
        return
    if not _bake_space(_prewarm_targets(bake_targets), missing):
        return

    # 3. A difference that survives a fresh bake cannot be fixed by baking
    #    (typically an unkeyed pose on a parent). Remember it to avoid loops.
    for target in bake_targets:
        entry = _SPACE.get(target.key)
        if not entry or frame not in entry["map"]:
            continue
        live = _live_mapping(target)
        entry["bad"] = _mapping_token(target, live) if _maps_differ(entry["map"][frame], live) else None


# -----------------------------------------------------------------------------
# Fast path evaluation (never changes the scene frame)
# -----------------------------------------------------------------------------

def _frame_bounds(context, target, settings):
    scene = context.scene
    if settings.range_mode == 'SCENE':
        return scene.frame_start, scene.frame_end
    if settings.range_mode == 'WINDOW':
        return (
            int(scene.frame_current - settings.frames_before),
            int(scene.frame_current + settings.frames_after),
        )
    keys = _location_keyframes(target) if not target.is_connected_bone else []
    if len(keys) < 2:
        keys = _driving_frames(target)
    if len(keys) < 2:
        if _has_constraints(target):
            return scene.frame_start, scene.frame_end
        return None
    return int(math.floor(min(keys))), int(math.ceil(max(keys)))


def _marker_frames(target, start, end):
    """Frames shown as key markers on the path."""
    if _location_fcurves(target) and not target.is_connected_bone:
        frames = _location_keyframes(target)
    else:
        frames = _own_key_frames(target)
    return [f for f in frames if start - 1.0e-4 <= f <= end + 1.0e-4]


def _is_dense(frames, prefs, ignore_setting=False):
    """Keys on (almost) every frame, as in motion capture or baked animation."""
    if (not prefs.use_control_points and not ignore_setting) or len(frames) < 8:
        return False
    gaps = sorted(b - a for a, b in zip(frames[:-1], frames[1:]))
    return gaps[len(gaps) // 2] <= 2.0 + 1.0e-6


def _control_frames(frames, spacing):
    """Keys used as control points: the first, the last and one every ``spacing`` frames."""
    if not frames:
        return []
    controls = [frames[0]]
    for frame in frames[1:-1]:
        if frame - controls[-1] >= spacing - 1.0e-6 and frames[-1] - frame >= spacing * 0.5:
            controls.append(frame)
    if frames[-1] != controls[-1]:
        controls.append(frames[-1])
    return controls


def _hermite(p0, p1, m0, m1, span, t):
    t2 = t * t
    t3 = t2 * t
    return ((2 * t3 - 3 * t2 + 1) * p0 + (t3 - 2 * t2 + t) * span * m0 +
            (-2 * t3 + 3 * t2) * p1 + (t3 - t2) * span * m1)


def _spline_tangents(frames, points, overrides=None):
    """Catmull-Rom tangents (per frame) of the control curve, with optional manual ones."""
    count = len(points)
    tangents = []
    for i in range(count):
        if overrides and i in overrides:
            tangents.append(overrides[i].copy())
        elif count < 2:
            tangents.append(Vector((0.0, 0.0, 0.0)))
        else:
            a, b = max(i - 1, 0), min(i + 1, count - 1)
            tangents.append((points[b] - points[a]) / (frames[b] - frames[a]))
    return tangents


def _spline_at(frames, points, tangents, frame):
    index = max(0, min(len(frames) - 2, bisect_right(frames, frame) - 1))
    span = frames[index + 1] - frames[index]
    t = (frame - frames[index]) / span
    return _hermite(points[index], points[index + 1], tangents[index], tangents[index + 1], span, t)


def _path_tangent(world, frame):
    """Tangent (per frame) of the path itself at a key, from its neighbors.

    Uses one-sided differences that are exact on a cubic curve on each side,
    so a tangent set with a handle reads back exactly.
    """
    after3 = [world.get(frame + d) for d in (1.0, 2.0, 3.0)]
    before3 = [world.get(frame - d) for d in (1.0, 2.0, 3.0)]
    center = world[frame]
    sides = []
    if all(p is not None for p in after3):
        sides.append((-11.0 * center + 18.0 * after3[0] - 9.0 * after3[1] + 2.0 * after3[2]) / 6.0)
    if all(p is not None for p in before3):
        sides.append((11.0 * center - 18.0 * before3[0] + 9.0 * before3[1] - 2.0 * before3[2]) / 6.0)
    if sides:
        return sum(sides, Vector((0.0, 0.0, 0.0))) / len(sides)
    before = world.get(frame - 1.0)
    after = world.get(frame + 1.0)
    if before is not None and after is not None:
        return (after - before) / 2.0
    if after is not None:
        return after - world[frame]
    if before is not None:
        return world[frame] - before
    return Vector((0.0, 0.0, 0.0))


def _spline_handles(frames, points, index, tangents):
    """Bezier handles of control point ``index`` (aligned, a third of each span)."""
    tangent = tangents[index]
    left_span = frames[index] - frames[index - 1] if index > 0 else frames[index + 1] - frames[index]
    right_span = frames[index + 1] - frames[index] if index < len(frames) - 1 else left_span
    return points[index] - tangent * left_span / 3.0, points[index] + tangent * right_span / 3.0


def _spline_deltas(frames, before, after, key_frames, tangents, overrides=None):
    """World offset of each key when the control curve goes from ``before`` to ``after``.

    The path is read as a smooth curve through the control points (with the
    path's own tangents) plus the small details of the animation. Only the
    smooth curve changes, so the edit is round and the details are kept.
    Moving a point also turns the tangents of its neighbors toward it, like a
    Catmull-Rom spline, so the curve bends smoothly.
    """
    old_tangents = tangents
    rounded_before = _spline_tangents(frames, before)
    rounded_after = _spline_tangents(frames, after)
    new_tangents = [t + (a - b) for t, a, b in zip(tangents, rounded_after, rounded_before)]
    for index, tangent in (overrides or {}).items():
        new_tangents[index] = tangent.copy()
    deltas = {}
    for frame in key_frames:
        if frames[0] <= frame <= frames[-1]:
            deltas[frame] = _spline_at(frames, after, new_tangents, frame) - \
                _spline_at(frames, before, old_tangents, frame)
    return deltas


def _smooth_sections(target, data, control_frames):
    """Replace the path around control points by a clean curve through the control points.

    Each selected control point smooths the two spans around it. The control
    points themselves do not move.
    """
    controls = data.get("controls")
    if not controls:
        return False
    frames = sorted(controls)
    world = {f: w.copy() for f, w in data["keys"]}
    points = [world[f] for f in frames]
    tangents = _spline_tangents(frames, points)
    deltas = {}
    for control in control_frames:
        if control not in controls:
            continue
        index = frames.index(control)
        low = frames[max(0, index - 1)]
        high = frames[min(len(frames) - 1, index + 1)]
        for frame in world:
            if low <= frame <= high:
                deltas[frame] = _spline_at(frames, points, tangents, frame) - world[frame]
    if not deltas:
        return False
    snapshots = {}
    mappings = {}
    for frame in deltas:
        record = _handle_at(data, frame)
        snapshot = _snapshot_key(target, frame)
        if record and snapshot:
            snapshots[frame] = snapshot
            mappings[frame] = record["mapping"]
    _move_keys(target, snapshots, mappings, Vector((0.0, 0.0, 0.0)), deltas=deltas)
    return True


_PROJECTION = {"signature": None, "points": []}


def _projected_keys(context, data):
    """Screen positions of the keys of a path, cached for the current view."""
    region, rv3d = context.region, context.region_data
    signature = (id(data), len(data["keys"]), region.width, region.height,
                 tuple(round(v, 6) for row in rv3d.perspective_matrix for v in row))
    if _PROJECTION["signature"] != signature:
        _PROJECTION["signature"] = signature
        _PROJECTION["points"] = [
            (frame, view3d_utils.location_3d_to_region_2d(region, rv3d, world)) for frame, world in data["keys"]]
    return _PROJECTION["points"]


def _picked_key(context, data, location):
    """Frame of the key under the pointer, or None.

    Control points win over the other keys, and among keys of the same kind
    the nearest one wins: dense keys never fight over a click.
    """
    prefs = _prefs()
    mouse = Vector(location)
    controls = data.get("controls")
    best_control = best_key = None
    for frame, point in _projected_keys(context, data):
        if point is None:
            continue
        distance = (point - mouse).length
        if controls is not None and frame in controls:
            if distance <= float(prefs.pick_radius) and (best_control is None or distance < best_control[0]):
                best_control = (distance, frame)
        else:
            radius = float(prefs.pick_radius) if controls is None else max(6.0, prefs.key_size * 0.5 + 3.0)
            if distance <= radius and (best_key is None or distance < best_key[0]):
                best_key = (distance, frame)
    if best_control is not None and best_key is not None and best_key[0] <= 3.0 \
            and best_key[0] + 2.0 < best_control[0]:
        return best_key[1]  # Right on a small key, clearly away from the control point.
    best = best_control or best_key
    return best[1] if best else None


def _sample_step(start, end, prefs):
    step = max(1, int(prefs.sample_step))
    if prefs.adaptive_sampling and end > start:
        step = max(step, int(math.ceil((end - start + 1) / max(2, int(prefs.max_samples)))))
    return step


def _sample_frames(context, target, settings, prefs):
    """Return (start, end, [frames]) or None."""
    bounds = _frame_bounds(context, target, settings)
    if bounds is None:
        return None
    start, end = bounds
    if end < start:
        start, end = end, start
    step = _sample_step(start, end, prefs)
    # Samples sit on a fixed grid so a sliding range re-uses baked frames.
    first = int(math.ceil(start / step)) * step
    frames = [float(f) for f in range(first, end + 1, step)]
    if not frames or frames[0] != float(start):
        frames.insert(0, float(start))
    if frames[-1] != float(end):
        frames.append(float(end))
    return start, end, frames


def _smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _live_transform_delta(context, target, curves, keyframes):
    """Display-only key displacement while Auto Key + G runs.

    Blender may not commit the new F-Curve value until the transform is
    confirmed, so the displayed path is deformed around the current frame using
    the live Location. Nothing is written to the animation here.
    """
    scene = context.scene
    tool_settings = getattr(scene, "tool_settings", None)
    if not tool_settings or not getattr(tool_settings, "use_keyframe_insert_auto", False):
        return None

    frame = float(scene.frame_current)
    delta = target.location - _eval_location(target, curves, frame)
    if delta.length_squared < 1.0e-12:
        return None

    prev_frame = None
    next_frame = None
    for key_frame in keyframes:
        if key_frame < frame - 0.001:
            prev_frame = key_frame
        elif key_frame > frame + 0.001:
            next_frame = key_frame
            break
    return frame, delta, prev_frame, next_frame


def _apply_live_delta(frame, location, live):
    if live is None:
        return location
    key_frame, delta, prev_frame, next_frame = live
    weight = 0.0
    if abs(frame - key_frame) <= 0.001:
        weight = 1.0
    elif frame < key_frame and prev_frame is not None and frame >= prev_frame:
        span = key_frame - prev_frame
        weight = _smoothstep((frame - prev_frame) / span) if span else 0.0
    elif frame > key_frame and next_frame is not None and frame <= next_frame:
        span = next_frame - key_frame
        weight = 1.0 - _smoothstep((frame - key_frame) / span) if span else 0.0
    return location + delta * weight


def _key_mode(curves, frame):
    types = []
    for fcurve in curves.values():
        keyframe = _keypoint_at_frame(fcurve, frame)
        if keyframe is not None:
            types.extend((keyframe.handle_left_type, keyframe.handle_right_type))
    if not types:
        return 'NONE'
    if all(t == 'VECTOR' for t in types):
        return 'VECTOR'
    if all(t in {'AUTO', 'AUTO_CLAMPED'} for t in types):
        return 'AUTO'
    if all(t == 'ALIGNED' for t in types):
        return 'ALIGNED'
    if all(t == 'FREE' for t in types):
        return 'FREE'
    return 'MIXED'


def _spatial_key_mode(target, frame):
    return _key_mode(_location_fcurves(target), frame)


def _handle_record(target, curves, frame, mapping):
    """Build *spatial* tangent handles from the three temporal F-Curves.

    Blender stores a Bezier handle per scalar F-Curve in (time, value) space.
    The true spatial tangent is rebuilt from dy/dt of every axis and shown at
    one shared visual time distance. Editing performs the inverse mapping, so
    the temporal handle X positions are preserved.
    """
    key_local = _eval_location(target, curves, frame)
    left_slopes = Vector((0.0, 0.0, 0.0))
    right_slopes = Vector((0.0, 0.0, 0.0))
    left_dts = []
    right_dts = []

    for axis in range(3):
        fcurve = curves.get(axis)
        if fcurve is None:
            continue
        keyframe = _keypoint_at_frame(fcurve, frame)
        if keyframe is None:
            continue
        key_local[axis] = keyframe.co.y
        left_dt = max(1.0e-6, float(keyframe.co.x - keyframe.handle_left.x))
        right_dt = max(1.0e-6, float(keyframe.handle_right.x - keyframe.co.x))
        left_dts.append(left_dt)
        right_dts.append(right_dt)
        left_slopes[axis] = (float(keyframe.co.y) - float(keyframe.handle_left.y)) / left_dt
        right_slopes[axis] = (float(keyframe.handle_right.y) - float(keyframe.co.y)) / right_dt

    visual_left_dt = max(0.05, sum(left_dts) / len(left_dts) if left_dts else 1.0)
    visual_right_dt = max(0.05, sum(right_dts) / len(right_dts) if right_dts else 1.0)

    return {
        "frame": float(frame),
        "mapping": mapping,
        "mode": _key_mode(curves, frame),
        "key": _local_to_world(key_local, mapping),
        "left": _local_to_world(key_local - left_slopes * visual_left_dt, mapping),
        "right": _local_to_world(key_local + right_slopes * visual_right_dt, mapping),
        "left_visual_dt": visual_left_dt,
        "right_visual_dt": visual_right_dt,
    }


def _settings_signature(scene, settings, prefs):
    return (
        settings.range_mode, settings.frames_before, settings.frames_after,
        prefs.sample_step, prefs.adaptive_sampling, prefs.max_samples,
        scene.frame_start, scene.frame_end, scene.frame_current,
    )


def _animation_signature(context, target, settings, prefs):
    if not _is_displayable(target):
        return None
    curves = _location_fcurves(target)
    curve_sig = []
    for axis, fcurve in curves.items():
        points = tuple(
            (
                tuple(round(float(v), 7) for v in kp.co),
                tuple(round(float(v), 7) for v in kp.handle_left),
                tuple(round(float(v), 7) for v in kp.handle_right),
                kp.interpolation,
                kp.handle_left_type,
                kp.handle_right_type,
            )
            for kp in fcurve.keyframe_points
        )
        curve_sig.append((axis, points, fcurve.mute))

    # The live Location lets an in-progress G transform refresh the preview.
    live_sig = tuple(round(float(v), 6) for v in target.location)
    entry = _SPACE.get(target.key)
    if _needs_bake(target) and entry and entry["map"]:
        space_sig = _SPACE_VERSION
    else:
        linear, offset = _live_mapping(target)
        space_sig = (
            tuple(round(v, 6) for row in linear for v in row),
            tuple(round(v, 6) for v in offset),
        )
    return (tuple(curve_sig), live_sig, space_sig, _settings_signature(context.scene, settings, prefs),
            _is_editable(target), target.obj.mode, tuple(_own_key_frames(target)))


def _build_path_cache(context, target):
    """Build a complete replacement cache and swap it atomically."""
    global _IS_BUILDING
    if target is None or not target.is_valid():
        return None
    key = target.key
    if _IS_BUILDING:
        return _PATH_CACHE.get(key)

    settings = context.scene.aemp_settings
    prefs = _prefs()
    sampled = _sample_frames(context, target, settings, prefs)
    if sampled is None:
        _PATH_CACHE.pop(key, None)
        _CACHE_SIGNATURES.pop(key, None)
        _tag_redraw_all_view3d()
        return None
    start, end, frames = sampled

    curves = _location_fcurves(target)
    editable = _is_editable(target)
    keyframes = _location_keyframes(target, curves) if editable else []
    live = _live_transform_delta(context, target, curves, keyframes) if editable else None

    baked = _needs_bake(target)
    has_map = bool((_SPACE.get(key) or {}).get("map"))
    if baked and not has_map and target.obj.mode == 'EDIT':
        # The rest pose shown in Edit Mode says nothing about the animation.
        _PATH_CACHE.pop(key, None)
        _CACHE_SIGNATURES.pop(key, None)
        return None
    static_mapping = _live_mapping(target)
    approximate = baked and not has_map

    def mapping_at(frame):
        if baked:
            mapping = _space_map(key, frame)
            if mapping is not None:
                return mapping
        return static_mapping

    _IS_BUILDING = True
    try:
        samples = []
        for frame in frames:
            location = _apply_live_delta(frame, _eval_location(target, curves, frame), live)
            samples.append((frame, _local_to_world(location, mapping_at(frame))))

        key_positions = []
        handles = {}
        if not editable:
            for frame in _marker_frames(target, start, end):
                location = _eval_location(target, curves, frame)
                key_positions.append((frame, _local_to_world(location, mapping_at(frame))))
        for frame in keyframes:
            mapping = mapping_at(frame)
            location = _apply_live_delta(frame, _eval_location(target, curves, frame), live)
            key_positions.append((frame, _local_to_world(location, mapping)))
            record = _handle_record(target, curves, frame, mapping)
            # A live transform moves the displayed key and its handles together.
            if live is not None and abs(frame - live[0]) <= 0.001:
                world_delta = mapping[0] @ live[1]
                for part in ("key", "left", "right"):
                    record[part] = record[part] + world_delta
            handles[frame] = record

        key_frames = [frame for frame, _world in key_positions]
        controls = None
        if _is_dense(key_frames, prefs):
            control_list = _control_frames(key_frames, prefs.control_spacing)
            controls = set(control_list)
            if editable and len(control_list) >= 2:
                world = dict(key_positions)
                points = [world[frame] for frame in control_list]
                tangents = [_path_tangent(world, frame) for frame in control_list]
                for index, frame in enumerate(control_list):
                    record = handles.get(frame)
                    if record is not None:
                        record["left"], record["right"] = _spline_handles(control_list, points, index, tangents)
                        record["spline"] = True
        data = {
            "key": key,
            "samples": samples,
            "keys": key_positions,
            "handles": handles,
            "start": start,
            "end": end,
            "approximate": approximate,
            "editable": editable,
            "controls": controls,
            # A key on every frame without control points: handles have no visible effect.
            "no_handles": controls is None and _is_dense(key_frames, prefs, ignore_setting=True),
        }
        # Atomic swap: the draw callback never sees a half-built path.
        _PATH_CACHE[key] = data
        _CACHE_SIGNATURES[key] = _animation_signature(context, target, settings, prefs)
    finally:
        _IS_BUILDING = False

    _tag_redraw_all_view3d()
    return data


def _get_cache(context, target, build_if_missing=True):
    if target is None:
        return None
    data = _PATH_CACHE.get(target.key)
    if data is None and build_if_missing:
        data = _build_path_cache(context, target)
    return data


def _handle_at(data, frame):
    if not data:
        return None
    handles = data.get("handles", {})
    record = handles.get(float(frame))
    if record is None:
        for candidate_frame, candidate in handles.items():
            if abs(float(candidate_frame) - float(frame)) <= 0.001:
                return candidate
    return record


def _mark_dirty(*_args):
    global _CACHE_DIRTY
    _CACHE_DIRTY = True
    _RIG_INDEX.clear()
    _tag_redraw_all_view3d()


def _clear_cache(*_args):
    global _CACHE_DIRTY
    _CACHE_DIRTY = True
    _RIG_INDEX.clear()
    _PATH_CACHE.clear()
    _CACHE_SIGNATURES.clear()
    _clear_space()
    _tag_redraw_all_view3d()


@persistent
def _on_undo_redo(_dummy):
    # Keep the last valid pixels until the next cheap rebuild, avoiding flashes.
    _mark_dirty()


@persistent
def _on_load(_dummy):
    _clear_cache()
    _set_edit_selection(None)


@persistent
def _on_depsgraph(_scene, _depsgraph):
    # The timer compares compact signatures and only rebuilds what changed.
    if not _IS_BUILDING and not _IS_BAKING:
        _tag_redraw_all_view3d()


def _live_update_timer():
    global _CACHE_DIRTY
    if _DRAW_HANDLE is None:
        return None
    if _IS_BUILDING or _IS_BAKING:
        return _TIMER_INTERVAL

    try:
        context = bpy.context
        scene = context.scene
        if not scene or not hasattr(scene, 'aemp_settings'):
            return _TIMER_INTERVAL
        settings = scene.aemp_settings
        if not settings.show_path:
            return _TIMER_INTERVAL
        prefs = _prefs()
        _RIG_INDEX.clear()

        visible = _display_targets(context, settings)
        _update_space(context, visible, settings, prefs)

        visible_keys = set()
        for target in visible:
            key = target.key
            visible_keys.add(key)
            signature = _animation_signature(context, target, settings, prefs)
            if signature is None:
                _PATH_CACHE.pop(key, None)
                _CACHE_SIGNATURES.pop(key, None)
                continue
            if _CACHE_DIRTY or signature != _CACHE_SIGNATURES.get(key) or key not in _PATH_CACHE:
                _build_path_cache(context, target)

        # Drop caches of paths that are no longer displayed.
        for key in list(_PATH_CACHE.keys()):
            if key not in visible_keys:
                _PATH_CACHE.pop(key, None)
                _CACHE_SIGNATURES.pop(key, None)
        _CACHE_DIRTY = False
    except (ReferenceError, RuntimeError, AttributeError):
        pass
    except Exception:  # A timer that raises is removed by Blender: never let it die.
        global _TIMER_ERROR_SHOWN
        if not _TIMER_ERROR_SHOWN:
            _TIMER_ERROR_SHOWN = True
            import traceback
            traceback.print_exc()
    return _TIMER_INTERVAL


# -----------------------------------------------------------------------------
# Drawing
# -----------------------------------------------------------------------------

def _draw_points(shader, coords, size, color):
    if not coords:
        return
    gpu.state.point_size_set(size)
    batch = batch_for_shader(shader, 'POINTS', {"pos": coords})
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw_lines(shader, coords, color):
    if not coords:
        return
    shader.uniform_float("color", color)
    batch_for_shader(shader, 'LINES', {"pos": coords}).draw(shader)


def _screen_disc_vertices(context, pos, radius_px, segments=20):
    """Return world-space triangles for a screen-space disc.

    Point-size rendering is backend dependent (notably Metal/macOS). A small
    camera-facing disc built from projected pixel coordinates gives predictable
    key size and color on every backend.
    """
    region = getattr(context, 'region', None)
    rv3d = getattr(context, 'region_data', None)
    if region is None or rv3d is None:
        return []
    center_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, pos)
    if center_2d is None:
        return []
    radius_px = max(1.0, float(radius_px))
    segments = max(8, int(segments))
    ring = []
    for i in range(segments):
        angle = (2.0 * math.pi * i) / segments
        point = center_2d + Vector((math.cos(angle) * radius_px, math.sin(angle) * radius_px))
        ring.append(view3d_utils.region_2d_to_location_3d(region, rv3d, point, pos))
    verts = []
    for i, first in enumerate(ring):
        verts.extend((pos, first, ring[(i + 1) % len(ring)]))
    return verts


def _draw_screen_disc(context, shader, pos, diameter_px, color):
    verts = _screen_disc_vertices(context, pos, max(1.0, float(diameter_px)) * 0.5)
    if not verts:
        return
    shader.bind()
    shader.uniform_float('color', color)
    batch_for_shader(shader, 'TRIS', {'pos': verts}).draw(shader)


def _draw_motion_path():
    context = bpy.context
    if context.area is None or context.area.type != 'VIEW_3D':
        return
    scene = context.scene
    settings = getattr(scene, "aemp_settings", None)
    if settings is None or not settings.show_path:
        return
    prefs = _prefs()
    active = _active_target(context)
    active_key = active.key if active else None

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    for target in _display_targets(context, settings):
        key = target.key
        data = _PATH_CACHE.get(key)
        if not data:
            continue
        samples = data.get("samples", [])
        if len(samples) < 2:
            continue

        gpu.state.depth_test_set('NONE' if prefs.xray else 'LESS_EQUAL')
        gpu.state.line_width_set(prefs.line_width)
        shader.bind()

        # Past/future split around the current frame: two batches in total.
        past = []
        future = []
        split = prefs.show_time_split
        current = scene.frame_current
        for (frame_a, pos_a), (frame_b, pos_b) in zip(samples[:-1], samples[1:]):
            (past if split and max(frame_a, frame_b) <= current else future).extend((pos_a, pos_b))
        _draw_lines(shader, past, tuple(prefs.past_color))
        _draw_lines(shader, future, tuple(prefs.path_color))

        if prefs.show_samples and len(samples) > 2:
            sample_color = tuple(prefs.path_color[:3]) + (min(prefs.path_color[3], 0.60),)
            _draw_points(shader, [co for _, co in samples[1:-1]], prefs.sample_size, sample_color)

        # Interactive key/handle points are owned by the gizmos when direct
        # editing is enabled for the active target.
        gizmo_owned = settings.direct_edit and key == active_key
        gpu.state.depth_test_set('NONE' if (prefs.xray or settings.direct_edit) else 'LESS_EQUAL')
        if not gizmo_owned:
            controls = data.get("controls")
            for frame, pos in data.get("keys", []):
                if _is_multi_selected(key, frame):
                    color = tuple(prefs.selected_key_color)
                    size = prefs.key_size + 3.0
                elif controls is not None and frame not in controls:
                    color = tuple(prefs.key_color[:3]) + (prefs.dense_key_opacity,)
                    _draw_screen_disc(context, shader, pos, prefs.key_size * 0.5, color)
                    continue
                else:
                    record = data.get("handles", {}).get(frame)
                    is_corner = bool(record) and record["mode"] == 'VECTOR'
                    color = tuple(prefs.corner_key_color if is_corner else prefs.key_color)
                    size = prefs.key_size
                if prefs.key_outline:
                    _draw_screen_disc(
                        context, shader, pos, size + prefs.key_outline_size * 2.0, (0.02, 0.02, 0.02, 0.90))
                _draw_screen_disc(context, shader, pos, size, color)

        if key == active_key and prefs.show_handles and _selection_matches(target) and not data.get("no_handles"):
            record = _handle_at(data, _EDIT_SELECTION["frame"])
            if record:
                key_pos, left, right = record["key"], record["left"], record["right"]
                gpu.state.line_width_set(1.0)
                shader.bind()
                _draw_lines(shader, [left, key_pos, key_pos, right], tuple(prefs.handle_line_color))
                if not gizmo_owned:
                    _draw_screen_disc(context, shader, left, prefs.handle_size, tuple(prefs.handle_color))
                    _draw_screen_disc(context, shader, right, prefs.handle_size, tuple(prefs.handle_color))

    gpu.state.line_width_set(1.0)
    gpu.state.point_size_set(1.0)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


_KEY_BADGES = {'VECTOR': 'V', 'ALIGNED': 'S', 'AUTO': 'A', 'FREE': 'F', 'MIXED': 'M'}


def _draw_motion_path_2d():
    context = bpy.context
    if context.area is None or context.area.type != 'VIEW_3D':
        return
    settings = getattr(context.scene, "aemp_settings", None)
    if settings is None or not settings.show_path:
        return
    prefs = _prefs()

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    for target in _display_targets(context, settings):
        data = _PATH_CACHE.get(target.key)
        if not data:
            continue
        samples = data.get("samples", [])

        if prefs.show_direction and len(samples) >= 3:
            spacing = max(2, int(prefs.arrow_spacing))
            size = float(prefs.arrow_size)
            coords = []
            for i in range(spacing, len(samples) - 1, spacing):
                p0 = _screen_point(context, samples[i - 1][1])
                p1 = _screen_point(context, samples[i][1])
                p2 = _screen_point(context, samples[i + 1][1])
                if p0 is None or p1 is None or p2 is None:
                    continue
                tangent = p2 - p0
                if tangent.length < 1.0e-5:
                    continue
                tangent.normalize()
                side = Vector((-tangent.y, tangent.x))
                back = p1 - tangent * size
                left = back + side * (size * 0.55)
                right = back - side * (size * 0.55)
                coords.extend([(p1.x, p1.y, 0.0), (left.x, left.y, 0.0), (p1.x, p1.y, 0.0), (right.x, right.y, 0.0)])
            if coords:
                gpu.state.blend_set('ALPHA')
                gpu.state.line_width_set(max(1.0, prefs.line_width))
                shader.bind()
                _draw_lines(shader, coords, tuple(prefs.path_color))

        if prefs.show_frame_labels or prefs.show_key_type_badges:
            font_id = 0
            blf.size(font_id, int(prefs.label_size))
            blf.color(font_id, *prefs.label_color)
            handles = data.get("handles", {})
            for frame, pos in data.get("keys", []):
                point = _screen_point(context, pos)
                if point is None:
                    continue
                parts = []
                if prefs.show_frame_labels:
                    parts.append(str(int(round(frame))) if abs(frame - round(frame)) < 0.001 else f"{frame:g}")
                if prefs.show_key_type_badges:
                    record = handles.get(frame)
                    parts.append(_KEY_BADGES.get(record["mode"], '') if record else '')
                text = "  ".join(part for part in parts if part)
                if not text:
                    continue
                blf.position(font_id, point.x + 8.0, point.y + 8.0, 0)
                blf.draw(font_id, text)

    # Hover insertion: frame number next to the preview point.
    if _HOVER["key"] is not None and _HOVER["world"] is not None and settings.direct_edit:
        point = _screen_point(context, _HOVER["world"])
        if point is not None:
            font_id = 0
            blf.size(font_id, int(prefs.label_size))
            blf.color(font_id, *prefs.hover_color)
            blf.enable(font_id, blf.SHADOW)
            blf.shadow(font_id, 3, 0.0, 0.0, 0.0, 0.9)
            blf.shadow_offset(font_id, 1, -1)
            blf.position(font_id, point.x + 10.0, point.y + 10.0, 0)
            blf.draw(font_id, "+ " + str(int(_HOVER["frame"])))
            blf.disable(font_id, blf.SHADOW)

    gpu.state.line_width_set(1.0)
    gpu.state.blend_set('NONE')


# -----------------------------------------------------------------------------
# Picking
# -----------------------------------------------------------------------------

def _screen_point(context, co3d, region=None, rv3d=None):
    region = region or context.region
    rv3d = rv3d or context.region_data
    if region is None or rv3d is None:
        return None
    return view3d_utils.location_3d_to_region_2d(region, rv3d, co3d)


# -----------------------------------------------------------------------------
# Key editing helpers (pure F-Curve edits, no RNA reference kept across events)
# -----------------------------------------------------------------------------

def _snapshot_key(target, frame):
    """Snapshot scalar key data as plain Python values.

    References to data owned by RNA containers can become invalid when the data
    is updated or on undo/redo, so each F-Curve/key is reacquired on every event.
    """
    snapshot = []
    for axis, fcurve in _location_fcurves(target).items():
        keyframe = _keypoint_at_frame(fcurve, frame)
        if keyframe is None:
            continue
        snapshot.append({
            "axis": int(axis),
            "co": tuple(keyframe.co),
            "left": tuple(keyframe.handle_left),
            "right": tuple(keyframe.handle_right),
            "left_type": str(keyframe.handle_left_type),
            "right_type": str(keyframe.handle_right_type),
        })
    return snapshot


def _key_for_axis(curves, axis, frame):
    fcurve = curves.get(int(axis))
    if fcurve is None:
        return None, None
    return fcurve, _keypoint_at_frame(fcurve, frame)


def _update_curves(fcurves):
    seen = []
    for fcurve in fcurves:
        if fcurve not in seen:
            seen.append(fcurve)
            fcurve.update()


def _restore_snapshot(target, frame, snapshot):
    curves = _location_fcurves(target)
    touched = []
    for item in snapshot:
        fcurve, keyframe = _key_for_axis(curves, item["axis"], frame)
        if keyframe is None:
            continue
        keyframe.co = item["co"]
        keyframe.handle_left = item["left"]
        keyframe.handle_right = item["right"]
        keyframe.handle_left_type = item["left_type"]
        keyframe.handle_right_type = item["right_type"]
        touched.append(fcurve)
    _update_curves(touched)


def _move_keys(target, snapshots, mappings, world_delta, snap_increment=0.0, deltas=None):
    """Move keys by a world-space delta. ``snapshots``: {frame: snapshot}.

    ``deltas`` ({frame: world offset}) gives each key its own offset instead.
    """
    curves = _location_fcurves(target)
    touched = []
    for frame, snapshot in snapshots.items():
        offset = deltas.get(frame, Vector((0.0, 0.0, 0.0))) if deltas is not None else world_delta
        local_delta = mappings[frame][0].inverted_safe() @ offset
        if snap_increment > 0.0:
            local_delta = Vector(tuple(round(v / snap_increment) * snap_increment for v in local_delta))
        for item in snapshot:
            fcurve, keyframe = _key_for_axis(curves, item["axis"], frame)
            if keyframe is None:
                continue
            delta = local_delta[item["axis"]]
            keyframe.co.y = item["co"][1] + delta
            keyframe.handle_left.y = item["left"][1] + delta
            keyframe.handle_right.y = item["right"][1] + delta
            touched.append(fcurve)
    _update_curves(touched)


def _set_key_handle_types(target, frame, snapshot, handle_type, only_types=None, side=None):
    curves = _location_fcurves(target)
    touched = []
    for item in snapshot:
        fcurve, keyframe = _key_for_axis(curves, item["axis"], frame)
        if keyframe is None:
            continue
        if only_types is not None:
            current = keyframe.handle_left_type if side == 'LEFT' else keyframe.handle_right_type
            if current not in only_types:
                continue
        keyframe.handle_left_type = handle_type
        keyframe.handle_right_type = handle_type
        touched.append(fcurve)
    _update_curves(touched)


def _set_tangent(target, frame, snapshot, record, desired_world):
    """Shape both handles of a key so its right tangent points to ``desired_world``."""
    curves = _location_fcurves(target)
    key_local = _eval_location(target, curves, frame)
    # One slope (value per frame) for both sides keeps the handles aligned in
    # time, so Blender does not re-align them afterwards.
    slope = (_world_to_local(desired_world, record["mapping"]) - key_local) / \
        max(1.0e-6, float(record["right_visual_dt"]))
    touched = []
    for item in snapshot:
        fcurve, keyframe = _key_for_axis(curves, item["axis"], frame)
        if keyframe is None:
            continue
        axis = item["axis"]
        left_dt = max(1.0e-6, float(keyframe.co.x - keyframe.handle_left.x))
        right_dt = max(1.0e-6, float(keyframe.handle_right.x - keyframe.co.x))
        keyframe.handle_left.y = float(keyframe.co.y) - slope[axis] * left_dt
        keyframe.handle_right.y = float(keyframe.co.y) + slope[axis] * right_dt
        touched.append(fcurve)
    _update_curves(touched)


def _set_handle(target, frame, part, snapshot, record, desired_world):
    """Move one spatial handle (``part``: LEFT or RIGHT) to ``desired_world``."""
    curves = _location_fcurves(target)
    key_local = _eval_location(target, curves, frame)
    desired_local = _world_to_local(desired_world, record["mapping"])
    visual_dt = max(1.0e-6, float(record["left_visual_dt" if part == 'LEFT' else "right_visual_dt"]))
    if part == 'LEFT':
        slope = (key_local - desired_local) / visual_dt
    else:
        slope = (desired_local - key_local) / visual_dt
    touched = []
    for item in snapshot:
        fcurve, keyframe = _key_for_axis(curves, item["axis"], frame)
        if keyframe is None:
            continue
        axis = item["axis"]
        # The dragged handle leads: Blender aligns the opposite one to it.
        keyframe.select_left_handle = part == 'LEFT'
        keyframe.select_right_handle = part == 'RIGHT'
        if part == 'LEFT':
            dt = max(1.0e-6, float(keyframe.co.x - keyframe.handle_left.x))
            keyframe.handle_left.y = float(keyframe.co.y) - slope[axis] * dt
        else:
            dt = max(1.0e-6, float(keyframe.handle_right.x - keyframe.co.x))
            keyframe.handle_right.y = float(keyframe.co.y) + slope[axis] * dt
        touched.append(fcurve)
    _update_curves(touched)


def _ensure_bezier(target, frame):
    """Switch the two segments around a key to Bezier, so that its handles shape the path.

    Imported animation (Mixamo, FBX...) often uses Linear interpolation, where
    Blender ignores the handles. Returns what changed, to restore it on cancel.
    """
    changed = []
    touched = []
    for axis, fcurve in _location_fcurves(target).items():
        previous = key = None
        for keyframe in fcurve.keyframe_points:
            x = float(keyframe.co.x)
            if abs(x - frame) <= 0.001:
                key = keyframe
            elif x < frame and (previous is None or x > previous.co.x):
                previous = keyframe
        for keyframe in (previous, key):
            if keyframe is not None and keyframe.interpolation != 'BEZIER':
                changed.append((axis, float(keyframe.co.x), keyframe.interpolation))
                keyframe.interpolation = 'BEZIER'
                touched.append(fcurve)
    _update_curves(touched)
    return changed


def _restore_interpolation(target, changed):
    curves = _location_fcurves(target)
    touched = []
    for axis, frame, interpolation in changed:
        fcurve, keyframe = _key_for_axis(curves, axis, frame)
        if keyframe is not None:
            keyframe.interpolation = interpolation
            touched.append(fcurve)
    _update_curves(touched)


def _toggle_corner_smooth(target, frame):
    _ensure_bezier(target, frame)
    curves = _location_fcurves(target)
    new_type = 'ALIGNED' if _key_mode(curves, frame) == 'VECTOR' else 'VECTOR'
    touched = []
    for fcurve in curves.values():
        keyframe = _keypoint_at_frame(fcurve, frame)
        if keyframe is None:
            continue
        keyframe.handle_left_type = new_type
        keyframe.handle_right_type = new_type
        touched.append(fcurve)
    _update_curves(touched)
    if touched:
        _mark_dirty()
    return new_type if touched else None


def _set_handle_type_on_selection(target, frame, part, handle_type):
    _ensure_bezier(target, frame)
    touched = []
    for fcurve in _location_fcurves(target).values():
        keyframe = _keypoint_at_frame(fcurve, frame)
        if keyframe is None:
            continue
        if part in {'KEY', 'LEFT'}:
            keyframe.handle_left_type = handle_type
        if part in {'KEY', 'RIGHT'}:
            keyframe.handle_right_type = handle_type
        touched.append(fcurve)
    _update_curves(touched)
    if touched:
        _mark_dirty()
    return bool(touched)


def _transform_fcurves(target):
    """F-Curves of every transform channel of the target itself."""
    channelbag = _channelbag(target.obj)
    if channelbag is None:
        return []
    prefix = target.prefix
    result = []
    for fcurve in channelbag.fcurves:
        path = fcurve.data_path
        if path.startswith(prefix) and path[len(prefix):] in _TRANSFORM_PROPS and not fcurve.lock:
            result.append(fcurve)
    return result


def _freeze_handles(keyframe):
    """Turn computed handle types into manual ones, keeping their current position.

    Automatic and Vector handles depend on the neighboring keys: a new key next
    to them would move them and change the curve.
    """
    left = tuple(keyframe.handle_left)
    right = tuple(keyframe.handle_right)
    for side in ("handle_left_type", "handle_right_type"):
        kind = getattr(keyframe, side)
        if kind in {'AUTO', 'AUTO_CLAMPED'}:
            setattr(keyframe, side, 'ALIGNED')
        elif kind == 'VECTOR':
            setattr(keyframe, side, 'FREE')
    keyframe.handle_left = left
    keyframe.handle_right = right


def _bezier_segment(previous, following):
    """Control points of a Bezier segment, with the time correction Blender applies."""
    p0 = Vector(previous.co)
    p1 = Vector(previous.handle_right)
    p2 = Vector(following.handle_left)
    p3 = Vector(following.co)
    span = p3.x - p0.x
    left = max(0.0, p1.x - p0.x)
    right = max(0.0, p3.x - p2.x)
    if left + right > span > 0.0:
        factor = span / (left + right)
        p1 = p0 + (p1 - p0) * factor
        p2 = p3 + (p2 - p3) * factor
    return p0, p1, p2, p3


def _bezier_split_parameter(p0, p1, p2, p3, frame):
    low, high = 0.0, 1.0
    for _ in range(60):
        middle = 0.5 * (low + high)
        u = 1.0 - middle
        x = u * u * u * p0.x + 3 * u * u * middle * p1.x + 3 * u * middle * middle * p2.x + \
            middle * middle * middle * p3.x
        if x < frame:
            low = middle
        else:
            high = middle
    return 0.5 * (low + high)


def _insert_preserving(fcurve, frame):
    """Insert a key on ``fcurve`` at ``frame`` without changing the curve.

    A Bezier segment is split with de Casteljau's algorithm, so the two halves
    trace exactly the same curve as before.
    """
    points = fcurve.keyframe_points
    if any(abs(kp.co.x - frame) < 1.0e-3 for kp in points):
        return False
    previous_frame = following_frame = None
    for kp in points:
        x = float(kp.co.x)
        if x < frame and (previous_frame is None or x > previous_frame):
            previous_frame = x
        elif x > frame and (following_frame is None or x < following_frame):
            following_frame = x
    value = fcurve.evaluate(frame)

    def key_at(x):
        return _keypoint_at_frame(fcurve, x) if x is not None else None

    for x in (previous_frame, following_frame):
        if x is not None:
            _freeze_handles(key_at(x))
    previous = key_at(previous_frame)
    following = key_at(following_frame)
    split = None
    if previous is not None and following is not None and previous.interpolation == 'BEZIER':
        p0, p1, p2, p3 = _bezier_segment(previous, following)
        t = _bezier_split_parameter(p0, p1, p2, p3, frame)
        q0, q1, q2 = p0.lerp(p1, t), p1.lerp(p2, t), p2.lerp(p3, t)
        r0, r1 = q0.lerp(q1, t), q1.lerp(q2, t)
        split = (q0, r0, r0.lerp(r1, t), r1, q2)
    interpolation = previous.interpolation if previous is not None else (
        following.interpolation if following is not None else 'BEZIER')
    # Outside the keyed range the curve follows its extrapolation: a constant or
    # straight segment reproduces it exactly.
    outside = 'LINEAR' if fcurve.extrapolation == 'LINEAR' else 'CONSTANT'
    if previous is not None and following is None:
        previous.interpolation = outside
        interpolation = outside
    elif previous is None and following is not None:
        interpolation = outside

    new_key = points.insert(frame, value, options={'FAST'})
    new_key.interpolation = interpolation
    new_key.handle_left_type = 'ALIGNED'
    new_key.handle_right_type = 'ALIGNED'
    if split is not None:
        q0, r0, middle, r1, q2 = split
        # Inserting may reallocate the key array: fetch every key again.
        previous = key_at(previous_frame)
        following = key_at(following_frame)
        new_key = key_at(frame)
        previous.handle_right = q0
        new_key.co = (frame, middle.y)
        new_key.handle_left = r0
        new_key.handle_right = r1
        following.handle_left = q2
    else:
        new_key = key_at(frame)
        new_key.handle_left = (frame - 1.0, value)
        new_key.handle_right = (frame + 1.0, value)
    fcurve.update()
    return True


def _insert_key(target, frame):
    """Insert a key at ``frame`` on every animated channel of the target, without changing the motion.

    A target without animation of its own gets a Location and Rotation key
    with its current values, like the I key.
    """
    curves = _transform_fcurves(target)
    if curves:
        inserted = [_insert_preserving(fcurve, frame) for fcurve in curves]
        return any(inserted)
    target.keyframe_insert(frame, "location")
    target.keyframe_insert(frame, target.rotation_path)
    return True


def _insert_current(target, frame):
    """Key the current values of the target (like the I key), on its animated channels."""
    owner = target.pose_bone or target.obj
    prefix = target.prefix
    props = []
    for fcurve in _transform_fcurves(target):
        prop = fcurve.data_path[len(prefix):]
        if prop not in props:
            props.append(prop)
    if not props:
        props = ["location", target.rotation_path]
    for prop in props:
        if hasattr(owner, prop):
            target.keyframe_insert(frame, prop)
    return True


def _delete_keys(target, frames):
    removed = 0
    touched = []
    for fcurve in _location_fcurves(target).values():
        for frame in frames:
            keyframe = _keypoint_at_frame(fcurve, frame)
            if keyframe is not None:
                fcurve.keyframe_points.remove(keyframe)
                removed += 1
                touched.append(fcurve)
    _update_curves(touched)
    return removed


_MODE_LABELS = {
    'VECTOR': "Corner", 'ALIGNED': "Smooth", 'AUTO': "Auto", 'FREE': "Free", 'MIXED': "Mixed", 'NONE': "Key",
}


# -----------------------------------------------------------------------------
# Operators
# -----------------------------------------------------------------------------

def _refresh_after_edit(context, target):
    _mark_dirty()
    _CACHE_SIGNATURES.pop(target.key, None)
    _build_path_cache(context, target)
    _tag_redraw_all_view3d()


class AEMP_OT_refresh_path(Operator):
    bl_idname = "aemp.refresh_path"
    bl_label = "Refresh Motion Paths"
    bl_description = "Recalculate the displayed motion paths, including the motion of parents and constraints"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.aemp_settings
        targets = _display_targets(context, settings)
        if not targets:
            self.report({'WARNING'}, iface_("Select an animated object or bone"))
            return {'CANCELLED'}
        _clear_space([target.key for target in targets])
        _update_space(context, targets, settings, _prefs(), force=True)
        if _BAKE_INFO["error"]:
            self.report({'WARNING'}, iface_("Could not evaluate the parent motion: the path may be approximate"))
        for target in targets:
            _build_path_cache(context, target)
        _tag_redraw_all_view3d()
        return {'FINISHED'}


class AEMP_OT_insert_key(Operator):
    bl_idname = "aemp.insert_current_location_key"
    bl_label = "Add Key at Current Frame"
    bl_description = "Key the current position of the active object or bone on the current frame"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        target = _active_target(context)
        return target is not None and target.is_valid() and target.obj.mode != 'EDIT'

    def execute(self, context):
        target = _active_target(context)
        if target is None:
            return {'CANCELLED'}
        frame = context.scene.frame_current
        _insert_current(target, frame)
        _refresh_after_edit(context, target)
        if _is_editable(target):
            _set_edit_selection(target, frame, 'KEY')
        return {'FINISHED'}


class AEMP_OT_delete_keys(Operator):
    bl_idname = "aemp.delete_selected_keys"
    bl_label = "Delete Selected Keys"
    bl_description = "Delete the Location keyframes selected on the motion path"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _selection_matches(_active_target(context))

    def execute(self, context):
        target = _active_target(context)
        if not _selection_matches(target):
            return {'CANCELLED'}
        frames = _selected_frames(target) or [_EDIT_SELECTION["frame"]]
        if not _delete_keys(target, frames):
            return {'CANCELLED'}
        _set_edit_selection(None)
        _refresh_after_edit(context, target)
        return {'FINISHED'}


class AEMP_OT_set_handle_type(Operator):
    bl_idname = "aemp.set_handle_type"
    bl_label = "Set Handle Type"
    bl_description = "Change how the path bends through the selected key"
    bl_options = {'REGISTER', 'UNDO'}

    handle_type: EnumProperty(
        name="Handle Type",
        items=[
            ('AUTO', "Automatic", "Smooth curve calculated by Blender"),
            ('ALIGNED', "Aligned", "Manual tangents kept aligned for a smooth transition"),
            ('FREE', "Free", "Each tangent is independent"),
            ('VECTOR', "Vector", "Straight segments and a sharp corner"),
        ],
    )

    @classmethod
    def poll(cls, context):
        return _selection_matches(_active_target(context))

    def execute(self, context):
        target = _active_target(context)
        if not _selection_matches(target):
            return {'CANCELLED'}
        if not _set_handle_type_on_selection(
                target, _EDIT_SELECTION["frame"], _EDIT_SELECTION["part"], self.handle_type):
            return {'CANCELLED'}
        _refresh_after_edit(context, target)
        return {'FINISHED'}


class AEMP_MT_handle_type(Menu):
    bl_label = "Handle Type"
    bl_idname = "AEMP_MT_handle_type"

    def draw(self, context):
        self.layout.operator_enum("aemp.set_handle_type", "handle_type")


class AEMP_OT_smooth_path(Operator):
    bl_idname = "aemp.smooth_path"
    bl_label = "Smooth Path"
    bl_description = ("Replace the path around the selected control points by a clean curve "
                      "through the control points (Alt + click on a control point does the same)")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        target = _active_target(context)
        if not _selection_matches(target):
            return False
        data = _PATH_CACHE.get(target.key) or {}
        controls = data.get("controls")
        return bool(controls) and any(f in controls for f in _selected_frames(target) or [_EDIT_SELECTION["frame"]])

    def execute(self, context):
        target = _active_target(context)
        data = _build_path_cache(context, target)
        frames = _selected_frames(target) or [_EDIT_SELECTION["frame"]]
        if not data or not _smooth_sections(target, data, frames):
            return {'CANCELLED'}
        _refresh_after_edit(context, target)
        return {'FINISHED'}


class AEMP_OT_toggle_control_points(Operator):
    bl_idname = "aemp.toggle_control_points"
    bl_label = "Control Points On / Off"
    bl_description = ("Switch dense keys (motion capture) between control points and real keys. "
                      "Shortcut: Shift + Alt + C in the 3D View")
    bl_options = {'REGISTER'}

    def execute(self, context):
        prefs = _prefs()
        if not isinstance(prefs, AddonPreferences):
            return {'CANCELLED'}
        prefs.use_control_points = not prefs.use_control_points
        _set_edit_selection(None)
        self.report({'INFO'}, iface_("Control points: on") if prefs.use_control_points
                    else iface_("Control points: off (real keys)"))
        _tag_redraw_all_view3d()
        return {'FINISHED'}


class AEMP_OT_toggle_selected_corner(Operator):
    bl_idname = "aemp.toggle_selected_corner"
    bl_label = "Corner / Smooth"
    bl_description = "Switch the selected key between a sharp corner and a smooth curve"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _selection_matches(_active_target(context))

    def execute(self, context):
        target = _active_target(context)
        if not _selection_matches(target):
            return {'CANCELLED'}
        if _toggle_corner_smooth(target, _EDIT_SELECTION["frame"]) is None:
            return {'CANCELLED'}
        _refresh_after_edit(context, target)
        return {'FINISHED'}


class AEMP_OT_modifier_click(Operator):
    """Alt / Shift click on a path key (fallback when the gizmo does not catch it)"""
    bl_idname = "aemp.modifier_click"
    bl_label = "Motion Path Modifier Click"
    bl_options = {'UNDO', 'INTERNAL'}

    mode: EnumProperty(items=[('ALT', "Alt", ""), ('SHIFT', "Shift", "")], default='ALT')

    def _pick_key(self, context, event):
        settings = getattr(context.scene, 'aemp_settings', None)
        target = _active_target(context)
        if not settings or not settings.show_path or not settings.direct_edit:
            return None
        if not _is_editable(target):
            return None
        # Always work from a fresh path: the cached one can be a tick late.
        data = _build_path_cache(context, target)
        if not data or context.region is None or context.region_data is None:
            return None
        if data.get("controls") is not None:
            # Dense keys: nearest key, control points first.
            frame = _picked_key(context, data, (event.mouse_region_x, event.mouse_region_y))
            if frame is None:
                return None
            return target, float(frame), dict(data["keys"])[frame].copy(), data
        prefs = _prefs()
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        best = None
        for frame, pos in data.get('keys', []):
            point = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, pos)
            if point is None:
                continue
            distance = (mouse - point).length
            if best is None or distance < best[0]:
                best = (distance, float(frame), pos.copy())
        if best is None or best[0] > max(float(prefs.pick_radius), float(prefs.key_size) + 6.0):
            return None
        return target, best[1], best[2], data

    def invoke(self, context, event):
        global _EDITING
        if context.area is None or context.area.type != 'VIEW_3D':
            return {'PASS_THROUGH'}
        hit = self._pick_key(context, event)
        if hit is None:
            return {'PASS_THROUGH'}
        target, frame, world_pos, data = hit

        if self.mode == 'SHIFT':
            _set_edit_selection(target, frame, 'KEY', extend=True, toggle=True)
            return {'FINISHED'}

        controls = data.get("controls")
        if data.get("no_handles"):
            _set_edit_selection(target, frame, 'KEY')
            return {'CANCELLED'}  # Dense real keys: no tangent to edit.
        self._spline = None
        self._snapshots = {}
        self._mappings = {}
        if controls is not None:
            # Dense keys: Alt + click on a control point smooths the path around it,
            # Alt + drag draws its tangent, like its handle.
            _set_edit_selection(target, frame, 'KEY')
            if frame not in controls:
                return {'CANCELLED'}
            self._spline = _make_spline(data, controls, [float(frame)], handle=True)
            for key in self._spline["keys"]:
                record = _handle_at(data, key)
                snapshot = _snapshot_key(target, key)
                if record and snapshot:
                    self._snapshots[float(key)] = snapshot
                    self._mappings[float(key)] = record["mapping"]

        self.target_key = target.key
        self.frame = float(frame)
        self._start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._key_world = world_pos.copy()
        self._snapshot = _snapshot_key(target, frame)
        self._drag_started = False
        self._interpolation = []
        _set_edit_selection(target, frame, 'KEY')
        _EDITING = True
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _end(self, context):
        global _EDITING
        _EDITING = False
        if context.area is not None:
            context.area.header_text_set(None)

    def modal(self, context, event):
        target = _target_from_key(getattr(self, 'target_key', None))
        if target is None:
            self._end(context)
            return {'CANCELLED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            if self._spline is not None:
                for key, snapshot in self._snapshots.items():
                    _restore_snapshot(target, key, snapshot)
                _refresh_after_edit(context, target)
            elif self._snapshot:
                _restore_snapshot(target, self.frame, self._snapshot)
                _restore_interpolation(target, getattr(self, "_interpolation", []))
                _refresh_after_edit(context, target)
            self._end(context)
            return {'CANCELLED'}

        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        if event.type == 'MOUSEMOVE':
            if self._spline is not None:
                if not self._drag_started and (mouse - self._start_mouse).length >= 7.0:
                    self._drag_started = True
                    if context.area is not None:
                        context.area.header_text_set(
                            iface_("Manual tangent  |  Release to confirm  |  Esc to cancel"))
                if self._drag_started and context.region is not None and context.region_data is not None:
                    desired = view3d_utils.region_2d_to_location_3d(
                        context.region, context.region_data, mouse, self._key_world)
                    _move_keys(target, self._snapshots, self._mappings, Vector((0.0, 0.0, 0.0)),
                               deltas=_spline_tangent_deltas(self._spline, desired))
                    _refresh_after_edit(context, target)
                return {'RUNNING_MODAL'}
            if not self._drag_started and (mouse - self._start_mouse).length >= 7.0:
                self._drag_started = True
                self._interpolation = _ensure_bezier(target, self.frame)
                _set_key_handle_types(target, self.frame, self._snapshot, 'ALIGNED')
                _build_path_cache(context, target)
                if context.area is not None:
                    context.area.header_text_set(
                        iface_("Manual tangent  |  Release to confirm  |  Esc to cancel"))
            if self._drag_started and context.region is not None and context.region_data is not None:
                record = _handle_at(_get_cache(context, target), self.frame)
                if record:
                    desired = view3d_utils.region_2d_to_location_3d(
                        context.region, context.region_data, mouse, self._key_world)
                    _set_tangent(target, self.frame, self._snapshot, record, desired)
                    _refresh_after_edit(context, target)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if self._spline is not None:
                if not self._drag_started:
                    _smooth_sections(target, _build_path_cache(context, target), [self.frame])
            elif not self._drag_started:
                _toggle_corner_smooth(target, self.frame)
            _set_edit_selection(target, self.frame, 'KEY')
            _refresh_after_edit(context, target)
            self._end(context)
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


class AEMP_OT_reset_preferences(Operator):
    bl_idname = "aemp.reset_preferences"
    bl_label = "Reset to Defaults"
    bl_description = "Reset every Editable Motion Paths preference (colors, sizes, behavior) to its default value"
    bl_options = {'REGISTER', 'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        prefs = _prefs()
        if not isinstance(prefs, AddonPreferences):
            return {'CANCELLED'}
        for prop in prefs.bl_rna.properties:
            if prop.identifier in {"rna_type", "bl_idname"} or prop.is_readonly:
                continue
            prefs.property_unset(prop.identifier)
        _mark_dirty()
        return {'FINISHED'}


# -----------------------------------------------------------------------------
# Native direct-edit gizmos
# -----------------------------------------------------------------------------

def _make_spline(data, controls, moved, handle=False):
    """Control curve state for an edit of the control points in `moved`."""
    key_frames = [f for f, _w in data["keys"]]
    world = {f: w.copy() for f, w in data["keys"]}
    frames = sorted(controls)
    indices = [frames.index(f) for f in moved]
    reach = 1 if handle else 2  # Catmull-Rom: a point bends two spans on each side.
    low = frames[max(0, min(indices) - reach)]
    high = frames[min(len(frames) - 1, max(indices) + reach)]
    return {
        "frames": frames,
        "points": [world[f] for f in frames],
        "tangents": [_path_tangent(world, f) for f in frames],
        "indices": indices,
        "keys": [f for f in key_frames if low <= f <= high],
    }


def _spline_tangent_deltas(spline, desired, side='RIGHT'):
    """Deltas that make the control curve leave its point toward `desired`."""
    frames, before = spline["frames"], spline["points"]
    index = spline["indices"][0]
    if len(frames) < 2:
        return {}
    if side == 'RIGHT':
        span = frames[index + 1] - frames[index] if index < len(frames) - 1 else frames[index] - frames[index - 1]
        tangent = (desired - before[index]) * 3.0 / span
    else:
        span = frames[index] - frames[index - 1] if index > 0 else frames[index + 1] - frames[index]
        tangent = (before[index] - desired) * 3.0 / span
    return _spline_deltas(frames, before, before, spline["keys"], spline["tangents"], {index: tangent})


class AEMP_GT_path_point(Gizmo):
    """One motion-path key or spatial handle.

    Blender itself owns hover, click capture and gizmo lifetime, so ordinary
    selection and navigation stay available: there is no permanent modal mode.
    """
    bl_idname = "AEMP_GT_path_point"

    def setup(self):
        self.target_key = ("", "")
        self.frame = 0.0
        self.part = 'KEY'  # KEY / LEFT / RIGHT
        self._reset_drag()
        self.use_undo = True
        # Custom gizmos have no RNA property tooltip; leaving it enabled can
        # make Blender query missing button data.
        self.use_tooltip = False
        self.use_select_background = True
        self.use_event_handle_all = True

    def _reset_drag(self):
        self._snapshot = []
        self._snapshots = {}
        self._mappings = {}
        self._record = None
        self._start_mouse = None
        self._anchor_world = None
        self._drag_started = False
        self._pending_handle_convert = False
        self._constraint_mode = 'FREE'  # FREE, X, Y, Z, PLANE_X, PLANE_Y, PLANE_Z
        self._alt_shape = False
        self._spline = None
        self._extra = ()
        self._alt_smooth = False
        self._interpolation = []

    def _target(self):
        return _target_from_key(self.target_key)

    def _record_now(self, context, target=None):
        target = target or self._target()
        if target is None:
            return None
        return _handle_at(_get_cache(context, target, build_if_missing=True), self.frame)

    def _world_pos(self, context):
        record = self._record_now(context)
        if record is None:
            return None
        return record["key" if self.part == 'KEY' else self.part.lower()].copy()

    def _is_active_selection(self):
        return (_EDIT_SELECTION["key"] == self.target_key and _EDIT_SELECTION["frame"] is not None and
                abs(float(_EDIT_SELECTION["frame"]) - float(self.frame)) <= 0.001)

    def _constraint_axes(self, context):
        """World-space X/Y/Z unit axes for the chosen constraint space."""
        target = self._target()
        if _prefs().constraint_space == 'LOCAL' and target is not None:
            pose_bone = target.pose_bone
            matrix = target.obj.matrix_world @ pose_bone.matrix if pose_bone else target.obj.matrix_world
            basis = matrix.to_3x3().normalized()
            return [Vector(basis.col[i]).normalized() for i in range(3)]
        return [axis.copy() for axis in _UNIT_AXES]

    def _apply_constraint(self, context, delta):
        mode = self._constraint_mode
        if mode == 'FREE':
            return delta
        axis = self._constraint_axes(context)['XYZ'.index(mode[-1])]
        along = axis * delta.dot(axis)
        return (delta - along) if mode.startswith('PLANE_') else along

    def _update_header(self, context):
        if not self._drag_started or context.area is None:
            return
        space = iface_("Local") if _prefs().constraint_space == 'LOCAL' else iface_("Global")
        mode = self._constraint_mode
        if mode == 'FREE':
            constraint = iface_("Free")
        elif mode.startswith('PLANE_'):
            constraint = iface_("Plane {}").format({'X': 'YZ', 'Y': 'XZ', 'Z': 'XY'}[mode[-1]])
        else:
            constraint = iface_("Axis {}").format(mode)
        part = iface_("Handle") if self.part in {'LEFT', 'RIGHT'} else iface_("Key")
        hint = iface_("X/Y/Z: axis  |  Shift + X/Y/Z: plane  |  Same key again: free  |  Ctrl: snap")
        context.area.header_text_set(f"{part}: {constraint} ({space})  |  {hint}")

    def _draw_constraint_guide(self, context):
        if not self._drag_started or self._constraint_mode == 'FREE' or self._anchor_world is None:
            return
        if not _prefs().show_constraint_guide:
            return
        axes = self._constraint_axes(context)
        mode = self._constraint_mode
        excluded = 'XYZ'.index(mode[-1])
        indices = [i for i in range(3) if i != excluded] if mode.startswith('PLANE_') else [excluded]
        colors = [(0.95, 0.20, 0.20, 0.95), (0.25, 0.85, 0.30, 0.95), (0.25, 0.50, 1.00, 0.95)]
        rv3d = context.region_data
        length = max(1.0, float(getattr(rv3d, 'view_distance', 10.0)) * 1.5) if rv3d else 10.0
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.line_width_set(2.0)
        shader.bind()
        for i in indices:
            _draw_lines(shader, [self._anchor_world - axes[i] * length, self._anchor_world + axes[i] * length],
                        colors[i])
        gpu.state.line_width_set(1.0)

    def draw(self, context):
        if self.part != 'KEY' and not self._is_active_selection():
            return
        record = self._record_now(context)
        if record is None:
            return
        pos = record["key" if self.part == 'KEY' else self.part.lower()]
        prefs = _prefs()
        size = prefs.key_size if self.part == 'KEY' else prefs.handle_size
        selected = _is_multi_selected(self.target_key, self.frame)
        controls = (_PATH_CACHE.get(self.target_key) or {}).get("controls")

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        if controls is not None and self.frame not in controls and not selected and not self.is_highlight:
            # Dense keys: small and transparent, the control points stand out.
            color = tuple(prefs.key_color[:3]) + (prefs.dense_key_opacity,)
            _draw_screen_disc(context, shader, pos, size * 0.5, color)
            gpu.state.blend_set('NONE')
            return
        if controls is not None and self.frame in controls:
            size += 2.0
        extra = 4.0 if selected and _EDIT_SELECTION["part"] == self.part else 0.0
        if self.is_highlight:
            color = (1.0, 1.0, 1.0, 1.0)
        elif self.part == 'KEY':
            if selected:
                color = tuple(prefs.selected_key_color)
            elif record["mode"] == 'VECTOR':
                color = tuple(prefs.corner_key_color)
            else:
                color = tuple(prefs.key_color)
        else:
            color = tuple(prefs.handle_color)
        if self.part == 'KEY' and prefs.key_outline:
            _draw_screen_disc(
                context, shader, pos, size + prefs.key_outline_size * 2.0 + extra, (0.02, 0.02, 0.02, 0.90))
        _draw_screen_disc(context, shader, pos, size + extra, color)
        self._draw_constraint_guide(context)
        gpu.state.blend_set('NONE')

    def test_select(self, context, location):
        settings = context.scene.aemp_settings
        if not settings.show_path or not settings.direct_edit:
            return -1
        prefs = _prefs()
        if self.part != 'KEY' and (not prefs.show_handles or not self._is_active_selection()):
            return -1
        record = self._record_now(context)
        if record is None or context.region is None or context.region_data is None:
            return -1
        if self.part == 'KEY':
            data = _PATH_CACHE.get(self.target_key)
            if not data:
                return -1
            picked = _picked_key(context, data, location)
            return 0 if picked is not None and abs(picked - float(self.frame)) <= 0.001 else -1
        pos = record[self.part.lower()]
        point = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, pos)
        if point is None:
            return -1
        distance = (Vector(location) - point).length
        radius = float(prefs.pick_radius)
        if self.part != 'KEY':
            # The key always wins in its visual core, so a short handle never
            # steals a click meant for the key.
            key_point = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, record["key"])
            if key_point is not None and (Vector(location) - key_point).length <= max(7.0, prefs.key_size * 0.85):
                return -1
            radius = max(radius, float(prefs.handle_size) + 6.0)
        return 0 if distance <= radius else -1

    def invoke(self, context, event):
        global _EDITING
        target = self._target()
        if target is None:
            return {'CANCELLED'}
        # Always start from a fresh path: the cached one can be a tick late.
        record = _handle_at(_build_path_cache(context, target), self.frame)
        if record is None:
            return {'CANCELLED'}

        data = _PATH_CACHE.get(self.target_key) or {}
        controls = data.get("controls")
        dense = controls is not None

        # Double-click toggles immediately. Alt is deferred so Alt-click toggles
        # Corner/Smooth while Alt-drag shapes the tangent. Dense keys have no
        # meaningful tangents: both are off there.
        no_handles = bool(data.get("no_handles"))
        if self.part == 'KEY' and event.value == 'DOUBLE_CLICK' and not dense and not no_handles:
            _toggle_corner_smooth(target, self.frame)
            _set_edit_selection(target, self.frame, 'KEY')
            _refresh_after_edit(context, target)
            return {'FINISHED'}

        self._reset_drag()
        self._alt_shape = bool(self.part == 'KEY' and event.alt and not dense and not no_handles)
        self._alt_smooth = bool(self.part == 'KEY' and event.alt and dense and float(self.frame) in controls)
        if self.part == 'KEY' and event.shift:
            _set_edit_selection(target, self.frame, 'KEY', extend=True, toggle=True)
        else:
            _set_edit_selection(target, self.frame, self.part)

        self._snapshot = _snapshot_key(target, self.frame)
        if not self._snapshot:
            return {'CANCELLED'}
        self._record = record
        self._snapshots = {float(self.frame): self._snapshot}
        self._mappings = {float(self.frame): record["mapping"]}
        if self.part == 'KEY' and self._alt_smooth:
            # Alt on a control point: a click smooths, a drag draws the tangent.
            data = _get_cache(context, target)
            for frame in self._start_spline(data, controls, [float(self.frame)], [], handle=True):
                other = _handle_at(data, frame)
                snapshot = _snapshot_key(target, frame)
                if other and snapshot:
                    self._snapshots[float(frame)] = snapshot
                    self._mappings[float(frame)] = other["mapping"]
        elif self.part == 'KEY':
            data = _get_cache(context, target)
            selected = [float(f) for f in _selected_frames(target)] or [float(self.frame)]
            frames = list(selected)
            moved = [f for f in selected if dense and f in controls]
            if moved:
                # Control points reshape the smooth curve that runs through them.
                frames = self._start_spline(data, controls, moved, selected)
            for frame in frames:
                other = _handle_at(data, frame)
                snapshot = _snapshot_key(target, frame)
                if other and snapshot:
                    self._snapshots[float(frame)] = snapshot
                    self._mappings[float(frame)] = other["mapping"]
        elif record.get("spline"):
            # Handle of a control point: sets the tangent of the control curve.
            for frame in self._start_spline(data, controls, [float(self.frame)], [], handle=True):
                other = _handle_at(data, frame)
                snapshot = _snapshot_key(target, frame)
                if other and snapshot:
                    self._snapshots[float(frame)] = snapshot
                    self._mappings[float(frame)] = other["mapping"]
        else:
            # The handle type only changes once a real drag starts, never on click.
            side = 'handle_left_type' if self.part == 'LEFT' else 'handle_right_type'
            curves = _location_fcurves(target)
            self._pending_handle_convert = any(
                getattr(keyframe, side) in {'AUTO', 'AUTO_CLAMPED', 'VECTOR'}
                for keyframe in (_key_for_axis(curves, item["axis"], self.frame)[1] for item in self._snapshot)
                if keyframe is not None
            )

        self._start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._anchor_world = record["key" if self.part == 'KEY' else self.part.lower()].copy()
        _EDITING = True
        _tag_redraw_all_view3d()
        return {'RUNNING_MODAL'}

    def _start_spline(self, data, controls, moved, selected, handle=False):
        """Prepare a control curve edit; return the frames it can change."""
        self._spline = _make_spline(data, controls, moved, handle)
        self._extra = tuple(f for f in selected if f not in controls)
        return sorted(set(self._spline["keys"]) | set(self._extra))

    def _spline_deltas(self, world_delta):
        spline = self._spline
        frames, before = spline["frames"], spline["points"]
        if self.part == 'KEY' and self._alt_smooth:
            # Alt + drag on a control point draws its tangent, like its right handle.
            return _spline_tangent_deltas(spline, self._anchor_world + world_delta, 'RIGHT')
        if self.part == 'KEY':
            after = [p + world_delta if i in spline["indices"] else p for i, p in enumerate(before)]
            deltas = _spline_deltas(frames, before, after, spline["keys"], spline["tangents"])
            for frame in self._extra:  # Small keys selected with the control points.
                deltas[frame] = deltas.get(frame, Vector((0.0, 0.0, 0.0))) + world_delta
            return deltas
        return _spline_tangent_deltas(spline, self._anchor_world + world_delta, self.part)

    def modal(self, context, event, tweak):
        target = self._target()
        if target is None or self._start_mouse is None or self._anchor_world is None:
            return {'CANCELLED'}
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))

        # Blender-style constraints while dragging. The same key again returns
        # to free movement; Shift + axis constrains to the complementary plane.
        if self._drag_started and event.value == 'PRESS' and event.type in {'X', 'Y', 'Z'}:
            requested = f"PLANE_{event.type}" if event.shift else event.type
            self._constraint_mode = 'FREE' if self._constraint_mode == requested else requested
            self._update_header(context)
            _tag_redraw_all_view3d()
            return {'RUNNING_MODAL'}

        # A click only selects. Editing starts after a real pointer drag, so a
        # small hand jitter never moves a key or a handle.
        if not self._drag_started:
            if (mouse - self._start_mouse).length < 7.0:
                return {'RUNNING_MODAL'}
            self._drag_started = True
            if self._spline is None and (self.part != 'KEY' or self._alt_shape):
                self._interpolation = _ensure_bezier(target, self.frame)
            if self.part == 'KEY' and self._alt_shape:
                _set_key_handle_types(target, self.frame, self._snapshot, 'ALIGNED')
            elif self.part != 'KEY' and self._pending_handle_convert and self._spline is None:
                _set_key_handle_types(
                    target, self.frame, self._snapshot, 'ALIGNED',
                    only_types={'AUTO', 'AUTO_CLAMPED', 'VECTOR'}, side=self.part)
                self._pending_handle_convert = False
            self._update_header(context)

        if context.region is None or context.region_data is None:
            return {'RUNNING_MODAL'}
        current = view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, mouse, self._anchor_world)
        origin = view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, self._start_mouse, self._anchor_world)
        world_delta = self._apply_constraint(context, current - origin)

        if self._spline is not None:
            if self.part == 'KEY' and 'SNAP' in tweak and not self._alt_smooth:
                step = _prefs().snap_increment
                world_delta = Vector(tuple(round(v / step) * step for v in world_delta))
            _move_keys(target, self._snapshots, self._mappings, world_delta,
                       deltas=self._spline_deltas(world_delta))
        elif self.part == 'KEY' and not self._alt_shape:
            snap = _prefs().snap_increment if 'SNAP' in tweak else 0.0
            _move_keys(target, self._snapshots, self._mappings, world_delta, snap)
        elif self.part == 'KEY':
            _set_tangent(target, self.frame, self._snapshot, self._record, self._anchor_world + world_delta)
        else:
            _set_handle(target, self.frame, self.part, self._snapshot, self._record,
                        self._anchor_world + world_delta)

        _refresh_after_edit(context, target)
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        global _EDITING
        target = self._target()
        if target is not None:
            if cancel:
                for frame, snapshot in self._snapshots.items():
                    _restore_snapshot(target, frame, snapshot)
                _restore_interpolation(target, self._interpolation)
            elif self.part == 'KEY' and self._alt_smooth and not self._drag_started:
                _smooth_sections(target, _build_path_cache(context, target), [float(self.frame)])
                _set_edit_selection(target, self.frame, 'KEY')
            elif self.part == 'KEY' and self._alt_shape and not self._drag_started \
                    and (_PATH_CACHE.get(self.target_key) or {}).get("controls") is None \
                    and not (_PATH_CACHE.get(self.target_key) or {}).get("no_handles"):
                _toggle_corner_smooth(target, self.frame)
                _set_edit_selection(target, self.frame, 'KEY')
            _refresh_after_edit(context, target)
        self._reset_drag()
        _EDITING = False
        if context.area is not None:
            context.area.header_text_set(None)
        _tag_redraw_all_view3d()


class AEMP_GT_path_insert(Gizmo):
    """Hover a path to preview a new key, click to insert it (like Loop Cut).

    The preview snaps to the nearest whole frame. The key is inserted without
    changing the motion. Keys, handles and drags always win over insertion.
    """
    bl_idname = "AEMP_GT_path_insert"

    def setup(self):
        self.target_key = ("", "")
        self.use_undo = True
        self.use_tooltip = False
        self._projection = None
        self._press = None
        self._frame = None
        self._moved = False

    def _projected(self, context, data):
        """Screen positions of the path samples, cached for the current view."""
        region, rv3d = context.region, context.region_data
        signature = (id(data), len(data["samples"]), region.width, region.height,
                     tuple(round(v, 6) for row in rv3d.perspective_matrix for v in row))
        if self._projection is None or self._projection[0] != signature:
            points = []
            for frame, world in data["samples"]:
                point = view3d_utils.location_3d_to_region_2d(region, rv3d, world)
                points.append((frame, point))
            self._projection = (signature, points)
        return self._projection[1]

    def _clear_hover(self):
        if _HOVER["key"] == self.target_key:
            _HOVER.update(key=None, frame=None, world=None)

    def _hit(self, context, location):
        """Frame under the pointer, or None."""
        settings = context.scene.aemp_settings
        prefs = _prefs()
        if not (settings.show_path and settings.direct_edit and prefs.hover_insert):
            return None
        if _EDITING or context.region is None or context.region_data is None:
            return None
        screen = context.screen
        if screen is not None and (screen.is_animation_playing or getattr(screen, "is_scrubbing", False)):
            return None
        target = _target_from_key(self.target_key)
        data = _PATH_CACHE.get(self.target_key)
        if target is None or not data or len(data["samples"]) < 2 or target.obj.mode == 'EDIT':
            return None
        mouse = Vector(location)
        region, rv3d = context.region, context.region_data

        # Keys and handles always win.
        guard = max(float(prefs.pick_radius), float(prefs.key_size) + 6.0)
        for _frame, world in data["keys"]:
            point = view3d_utils.location_3d_to_region_2d(region, rv3d, world)
            if point is not None and (point - mouse).length <= guard:
                return None
        if data.get("editable") and prefs.show_handles and _selection_matches(target):
            record = _handle_at(data, _EDIT_SELECTION["frame"])
            if record:
                for part in ("left", "right"):
                    point = view3d_utils.location_3d_to_region_2d(region, rv3d, record[part])
                    if point is not None and (point - mouse).length <= max(guard, prefs.handle_size + 6.0):
                        return None

        best = None
        points = self._projected(context, data)
        for (frame_a, point_a), (frame_b, point_b) in zip(points[:-1], points[1:]):
            if point_a is None or point_b is None:
                continue
            segment = point_b - point_a
            length_squared = segment.length_squared
            u = 0.0 if length_squared < 1.0e-9 else max(0.0, min(1.0, (mouse - point_a).dot(segment) / length_squared))
            distance = (point_a + segment * u - mouse).length
            if best is None or distance < best[0]:
                best = (distance, frame_a + (frame_b - frame_a) * u)
        if best is None or best[0] > float(prefs.hover_radius):
            return None
        frame = float(round(best[1]))
        frame = max(float(data["start"]), min(float(data["end"]), frame))
        if any(abs(frame - key_frame) < 0.5 for key_frame, _world in data["keys"]):
            return None
        return frame

    def _world_at(self, data, frame):
        samples = data["samples"]
        frames = [f for f, _w in samples]
        index = bisect_left(frames, frame)
        if index <= 0:
            return samples[0][1].copy()
        if index >= len(samples):
            return samples[-1][1].copy()
        (frame_a, world_a), (frame_b, world_b) = samples[index - 1], samples[index]
        if frame_b - frame_a < 1.0e-9:
            return world_b.copy()
        return world_a.lerp(world_b, (frame - frame_a) / (frame_b - frame_a))

    def test_select(self, context, location):
        frame = self._hit(context, location)
        if frame is None:
            self._clear_hover()
            return -1
        data = _PATH_CACHE.get(self.target_key)
        if _HOVER["key"] != self.target_key or _HOVER["frame"] != frame:
            _HOVER.update(key=self.target_key, frame=frame, world=self._world_at(data, frame))
            if context.area is not None:
                context.area.tag_redraw()
        return 0

    def draw(self, context):
        if not self.is_highlight or self._press is not None and self._moved:
            if not self.is_highlight:
                self._clear_hover()
            return
        if _HOVER["key"] != self.target_key or _HOVER["world"] is None:
            return
        prefs = _prefs()
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        size = max(5.0, prefs.key_size * 0.85)
        _draw_screen_disc(context, shader, _HOVER["world"], size + 4.0, (0.02, 0.02, 0.02, 0.9))
        _draw_screen_disc(context, shader, _HOVER["world"], size, tuple(prefs.hover_color))
        gpu.state.blend_set('NONE')

    def invoke(self, context, event):
        if _HOVER["key"] != self.target_key or _HOVER["frame"] is None:
            return {'CANCELLED'}
        self._press = Vector((event.mouse_region_x, event.mouse_region_y))
        self._frame = _HOVER["frame"]
        self._moved = False
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        if self._press is None:
            return {'CANCELLED'}
        # A drag is not a click: never insert a key at the end of a drag.
        if (Vector((event.mouse_region_x, event.mouse_region_y)) - self._press).length > 5.0:
            self._moved = True
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        frame = self._frame
        clicked = not cancel and not self._moved and frame is not None
        self._press = None
        self._frame = None
        self._moved = False
        if not clicked:
            return
        target = _target_from_key(self.target_key)
        if target is None:
            return
        if _insert_key(target, frame):
            _clear_hover_state()
            _refresh_after_edit(context, target)
            if _is_editable(target):
                _set_edit_selection(target, frame, 'KEY')


def _clear_hover_state():
    _HOVER.update(key=None, frame=None, world=None)


class AEMP_GGT_motion_path(GizmoGroup):
    bl_idname = "AEMP_GGT_motion_path"
    bl_label = "Editable Motion Path Direct Manipulation"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'
    bl_options = {'3D', 'PERSISTENT', 'SELECT'}

    @classmethod
    def poll(cls, context):
        scene = getattr(context, 'scene', None)
        settings = getattr(scene, 'aemp_settings', None) if scene else None
        return bool(settings and settings.show_path and settings.direct_edit)

    def setup(self, context):
        self._signature = None
        self._rebuild(context)

    def _has_modal_gizmo(self):
        # Never destroy/recreate a gizmo while Blender's tweak operator uses
        # it: that invalidates Blender's active gizmo pointer and can crash.
        try:
            return any(gizmo.is_modal for gizmo in self.gizmos)
        except (ReferenceError, RuntimeError):
            return False

    def _structure_signature(self, context):
        settings = context.scene.aemp_settings
        target = _active_target(context)
        editable = None
        if _is_editable(target):
            frames = _location_keyframes(target)
            prefs = _prefs()
            editable = (target.key, tuple(frames), _is_dense(frames, prefs, ignore_setting=True),
                        prefs.use_control_points, prefs.control_spacing)
        paths = tuple(t.key for t in _display_targets(context, settings) if t.obj.mode != 'EDIT')
        return editable, paths

    def _rebuild(self, context):
        if self._has_modal_gizmo():
            return
        self.gizmos.clear()
        self._signature = self._structure_signature(context)
        editable, paths = self._signature
        if editable is not None:
            key, frames, dense, use_controls, spacing = editable
            controls = set(_control_frames(list(frames), spacing)) if dense and use_controls else set()
            for frame in frames:
                # Dense keys: handles only on control points (none in real keys mode).
                for part in (('KEY', 'LEFT', 'RIGHT') if not dense or frame in controls else ('KEY',)):
                    gizmo = self.gizmos.new(AEMP_GT_path_point.bl_idname)
                    gizmo.target_key = key
                    gizmo.frame = frame
                    gizmo.part = part
        for key in paths:
            gizmo = self.gizmos.new(AEMP_GT_path_insert.bl_idname)
            gizmo.target_key = key

    def _sync_structure(self, context):
        # Called for every depsgraph/RNA update, including each mouse move of a
        # drag: only rebuild when the set of keys changed. Positions are read
        # dynamically by draw().
        if self._structure_signature(context) != self._signature and not self._has_modal_gizmo():
            self._rebuild(context)

    def refresh(self, context):
        self._sync_structure(context)

    def draw_prepare(self, context):
        self._sync_structure(context)


# -----------------------------------------------------------------------------
# Settings: per-scene state and global preferences
# -----------------------------------------------------------------------------

def _update_redraw(_self, _context):
    _tag_redraw_all_view3d()


def _update_dirty(_self, _context):
    _mark_dirty()


def _color(name, default, description=""):
    return FloatVectorProperty(
        name=name, description=description, subtype='COLOR', size=4, min=0.0, max=1.0,
        default=default, update=_update_redraw)


class AEMP_Settings(PropertyGroup):
    """What to show in this scene. Look and behavior live in the preferences."""

    show_path: BoolProperty(
        name="Show Path", description="Display the motion path in the 3D View",
        default=True, update=_update_dirty)
    direct_edit: BoolProperty(
        name="Editable", description="Edit the keys and handles of the path directly in the 3D View",
        default=True, update=_update_redraw)
    display_mode: EnumProperty(
        name="Paths",
        description="Which motion paths are displayed",
        items=[
            ('ACTIVE', "Active", "Only the active object or bone"),
            ('SELECTED', "Selected", "Every selected object or bone"),
        ],
        default='ACTIVE', update=_update_dirty)
    range_mode: EnumProperty(
        name="Range",
        description="Frame range covered by the path",
        items=[
            ('KEYS', "Keyframes", "From the first to the last Location keyframe"),
            ('WINDOW', "Around Frame", "A window of frames around the current frame"),
            ('SCENE', "Scene", "The scene frame range"),
        ],
        default='KEYS', update=_update_dirty)
    frames_before: IntProperty(
        name="Before", description="Frames displayed before the current frame",
        default=24, min=0, max=10000, update=_update_dirty)
    frames_after: IntProperty(
        name="After", description="Frames displayed after the current frame",
        default=24, min=0, max=10000, update=_update_dirty)


class AEMP_Preferences(AddonPreferences):
    bl_idname = _ADDON_ID

    # Display
    show_handles: BoolProperty(
        name="Bezier Handles", description="Show the handles of the selected key",
        default=True, update=_update_redraw)
    show_direction: BoolProperty(
        name="Direction Arrows", description="Show arrows along the path in the direction of the animation",
        default=True, update=_update_redraw)
    show_time_split: BoolProperty(
        name="Past / Future Colors", description="Use a different color before and after the current frame",
        default=True, update=_update_redraw)
    show_frame_labels: BoolProperty(
        name="Frame Numbers", description="Show the frame number next to each key",
        default=False, update=_update_redraw)
    show_key_type_badges: BoolProperty(
        name="Key Type Letters",
        description="Show a letter next to each key: V = Vector, S = Aligned, A = Automatic, F = Free",
        default=False, update=_update_redraw)
    show_samples: BoolProperty(
        name="Frame Dots", description="Show a dot on every frame to read the spacing of the motion",
        default=False, update=_update_redraw)
    xray: BoolProperty(
        name="X-Ray", description="Show the path through the geometry",
        default=False, update=_update_redraw)
    path_point: EnumProperty(
        name="Bone Point",
        description="Point of the bone that draws the path",
        items=[
            ('HEAD', "Head", "Path of the base of the bone"),
            ('TAIL', "Tail", "Path of the tip of the bone: best for hands and feet"),
        ],
        default='HEAD', update=lambda _self, _context: _clear_cache())

    # Appearance
    path_color: _color("Path", (0.35, 0.75, 1.0, 0.95))
    past_color: _color("Past Path", (0.20, 0.38, 0.55, 0.55))
    key_color: _color("Smooth Key", (1.0, 0.58, 0.10, 1.0))
    corner_key_color: _color("Corner Key", (1.0, 0.25, 0.08, 1.0))
    selected_key_color: _color("Selected Key", (1.0, 0.86, 0.22, 1.0))
    handle_color: _color("Handles", (0.95, 0.95, 0.95, 1.0))
    handle_line_color: _color("Handle Lines", (0.8, 0.8, 0.8, 0.7))
    label_color: _color("Labels", (0.92, 0.92, 0.92, 0.9))
    hover_color: _color("New Key Preview", (0.40, 1.0, 0.55, 1.0))
    dense_key_opacity: FloatProperty(
        name="Dense Keys Opacity", description="Opacity of the keys that are not control points",
        default=0.35, min=0.0, max=1.0, subtype='FACTOR', update=_update_redraw)
    line_width: FloatProperty(name="Line Width", default=2.0, min=1.0, max=8.0, update=_update_redraw)
    key_size: FloatProperty(name="Key Size", default=9.0, min=3.0, max=24.0, update=_update_redraw)
    handle_size: FloatProperty(name="Handle Size", default=10.0, min=3.0, max=24.0, update=_update_redraw)
    sample_size: FloatProperty(name="Dot Size", default=3.0, min=1.0, max=12.0, update=_update_redraw)
    label_size: IntProperty(name="Label Size", default=12, min=8, max=30, update=_update_redraw)
    key_outline: BoolProperty(
        name="Key Outline", description="Dark outline around keys, easier to read on busy backgrounds",
        default=True, update=_update_redraw)
    key_outline_size: FloatProperty(
        name="Outline Width", default=2.0, min=0.5, max=6.0, subtype='PIXEL', update=_update_redraw)
    arrow_spacing: IntProperty(
        name="Arrow Spacing", description="Number of path samples between two arrows",
        default=8, min=2, max=100, update=_update_redraw)
    arrow_size: FloatProperty(
        name="Arrow Size", default=7.0, min=3.0, max=24.0, subtype='PIXEL', update=_update_redraw)

    # Editing
    pick_radius: FloatProperty(
        name="Click Tolerance", description="Distance in pixels within which a key can be clicked",
        default=20.0, min=4.0, max=40.0, subtype='PIXEL')
    snap_increment: FloatProperty(
        name="Snap Increment", description="Step used when dragging a key with Ctrl held",
        default=0.1, min=0.001, max=100.0, precision=3)
    constraint_space: EnumProperty(
        name="Constraint Space",
        description="Axes used by the X/Y/Z constraints while dragging",
        items=[
            ('GLOBAL', "Global", "World X/Y/Z axes"),
            ('LOCAL', "Local", "Local axes of the animated object or bone"),
        ],
        default='GLOBAL')
    show_constraint_guide: BoolProperty(
        name="Axis Guide", description="Show the constraint axis while dragging", default=True)
    use_control_points: BoolProperty(
        name="Control Points",
        description="When there is a key on (almost) every frame, like motion capture, edit the path with a few "
                    "control points: the keys around a dragged control point follow smoothly",
        default=True, update=lambda _self, _context: _clear_cache())
    control_spacing: IntProperty(
        name="Control Point Spacing", description="Frames between two control points",
        default=8, min=2, max=120, update=lambda _self, _context: _clear_cache())
    hover_insert: BoolProperty(
        name="Click to Add Keys",
        description="Hovering a path shows where a key would go; a click adds it without changing the motion",
        default=True, update=_update_redraw)
    hover_radius: FloatProperty(
        name="Hover Distance",
        description="Distance in pixels from the path within which the new key preview appears",
        default=10.0, min=4.0, max=30.0, subtype='PIXEL')

    # Performance
    auto_update: BoolProperty(
        name="Auto Refresh",
        description="Recalculate the path automatically when a parent or constraint changes. "
                    "Turn off on very heavy rigs and use the Refresh button instead",
        default=True, update=_update_dirty)
    adaptive_sampling: BoolProperty(
        name="Adaptive Sampling", description="Skip frames on long ranges to keep the viewport fast",
        default=True, update=_update_dirty)
    max_samples: IntProperty(
        name="Max Samples", description="Maximum number of points evaluated along a path",
        default=500, min=32, max=10000, update=_update_dirty)
    sample_step: IntProperty(
        name="Frame Step", description="Evaluate the path every N frames",
        default=1, min=1, max=50, update=_update_dirty)

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        columns = layout.grid_flow(row_major=True, columns=2, even_columns=True, even_rows=False)
        _draw_display_options(columns.box(), self, title=True)
        _draw_editing_options(columns.box(), self, title=True)
        _draw_appearance_options(columns.box(), self, title=True)
        _draw_performance_options(columns.box(), self, title=True)
        layout.operator("aemp.reset_preferences", icon='LOOP_BACK')


_FALLBACK_PREFS = None


def _prefs():
    """Add-on preferences, or their defaults when the add-on is not registered as one."""
    global _FALLBACK_PREFS
    try:
        addon = bpy.context.preferences.addons.get(_ADDON_ID)
        if addon is not None and addon.preferences is not None:
            return addon.preferences
    except (AttributeError, RuntimeError):
        pass
    if _FALLBACK_PREFS is None:
        defaults = {}
        for name, prop in AEMP_Preferences.__annotations__.items():
            defaults[name] = getattr(prop, "keywords", {}).get("default")
        _FALLBACK_PREFS = SimpleNamespace(**defaults)
    return _FALLBACK_PREFS


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

def _draw_display_options(layout, prefs, title=False):
    if title:
        layout.label(text="Display")
    col = layout.column(align=True)
    col.prop(prefs, "show_handles")
    col.prop(prefs, "show_direction")
    col.prop(prefs, "show_time_split")
    col.prop(prefs, "show_samples")
    col.prop(prefs, "show_frame_labels")
    col.prop(prefs, "show_key_type_badges")
    col.prop(prefs, "xray")
    layout.prop(prefs, "path_point")


def _draw_appearance_options(layout, prefs, title=False):
    if title:
        layout.label(text="Appearance")
    col = layout.column(align=True)
    col.prop(prefs, "line_width", slider=True)
    col.prop(prefs, "key_size", slider=True)
    col.prop(prefs, "handle_size", slider=True)
    col = layout.column(align=True)
    col.prop(prefs, "path_color")
    if prefs.show_time_split:
        col.prop(prefs, "past_color")
    col.prop(prefs, "key_color")
    col.prop(prefs, "corner_key_color")
    col.prop(prefs, "selected_key_color")
    col.prop(prefs, "handle_color")
    col.prop(prefs, "handle_line_color")
    col = layout.column(align=True)
    col.prop(prefs, "key_outline")
    if prefs.key_outline:
        col.prop(prefs, "key_outline_size", slider=True)
    if prefs.show_direction:
        col = layout.column(align=True)
        col.prop(prefs, "arrow_spacing")
        col.prop(prefs, "arrow_size")
    if prefs.show_samples:
        layout.prop(prefs, "sample_size")
    if prefs.show_frame_labels or prefs.show_key_type_badges:
        col = layout.column(align=True)
        col.prop(prefs, "label_size")
        col.prop(prefs, "label_color")


def _draw_editing_options(layout, prefs, title=False):
    if title:
        layout.label(text="Editing")
    col = layout.column(align=True)
    col.prop(prefs, "constraint_space")
    col.prop(prefs, "show_constraint_guide")
    col.prop(prefs, "snap_increment")
    col.prop(prefs, "pick_radius")
    col = layout.column(align=True)
    col.prop(prefs, "use_control_points")
    if prefs.use_control_points:
        col.prop(prefs, "control_spacing")
        col.prop(prefs, "dense_key_opacity", slider=True)
    col = layout.column(align=True)
    col.prop(prefs, "hover_insert")
    if prefs.hover_insert:
        col.prop(prefs, "hover_radius")
        col.prop(prefs, "hover_color")


def _draw_performance_options(layout, prefs, title=False):
    if title:
        layout.label(text="Performance")
    col = layout.column(align=True)
    col.prop(prefs, "auto_update")
    col.prop(prefs, "adaptive_sampling")
    if prefs.adaptive_sampling:
        col.prop(prefs, "max_samples")
    col.prop(prefs, "sample_step")


_SHORTCUTS = (
    ("Click", "Select a key"),
    ("Drag", "Move a key or a handle"),
    ("Shift + Click", "Add to the selection"),
    ("Alt + Click", "Corner / Smooth"),
    ("Alt + Drag", "Shape the tangent"),
    ("X / Y / Z", "Lock to an axis"),
    ("Shift + X / Y / Z", "Lock to a plane"),
    ("Ctrl", "Snap while dragging"),
)


class VIEW3D_PT_editable_motion_path(Panel):
    bl_label = "Editable Motion Paths"
    bl_idname = "VIEW3D_PT_editable_motion_path"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Path"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.aemp_settings
        prefs = _prefs()
        target = _active_target(context)
        editable = _is_editable(target)
        displayable = _is_displayable(target)

        row = layout.row(align=True)
        row.prop(settings, "show_path", toggle=True, icon='HIDE_OFF' if settings.show_path else 'HIDE_ON')
        row.prop(settings, "direct_edit", toggle=True, icon='RESTRICT_SELECT_OFF')
        row.operator("aemp.refresh_path", text="", icon='FILE_REFRESH')
        layout.row().prop(settings, "display_mode", expand=True)

        # Target status: always tells the user why nothing is displayed.
        box = layout.box()
        displayed = _display_targets(context, settings) if settings.show_path else []
        shown = sum(1 for t in displayed if t.key in _PATH_CACHE)
        waiting = len(displayed) - shown
        if target is None:
            box.label(text="Select an object or a bone", icon='INFO')
        else:
            box.label(text=target.label, icon='BONE_DATA' if target.bone else 'OBJECT_DATA', translate=False)
            data = _PATH_CACHE.get(target.key)
            if target.obj.mode == 'EDIT':
                if displayable and not data:
                    box.label(text="Show the path in Object or Pose Mode first", icon='INFO')
                elif displayable:
                    box.label(text="Edit Mode: view only", icon='INFO')
            if not displayable and target.obj.type == 'ARMATURE' and not target.bone:
                box.label(text="Animated by its bones", icon='INFO')
                box.label(text="Select bones in Pose Mode", icon='BLANK1')
            elif not displayable:
                box.label(text="Not animated", icon='INFO')
            elif editable and data and data.get("controls") is not None:
                box.label(text=iface_("Dense keys: {} control points").format(len(data["controls"])),
                          icon='CHECKMARK', translate=False)
                box.label(text="Drag a control point or any key", icon='BLANK1')
                box.operator("aemp.toggle_control_points", text="Use Real Keys", icon='KEYFRAME')
            elif editable and data and not prefs.use_control_points and \
                    _is_dense([f for f, _w in data["keys"]], prefs, ignore_setting=True):
                box.label(text="Dense keys: real keys", icon='CHECKMARK')
                box.operator("aemp.toggle_control_points", text="Use Control Points", icon='HANDLE_AUTO')
            elif editable:
                box.label(text="Editable: drag keys, click path", icon='CHECKMARK')
            elif target.obj.mode != 'EDIT':
                box.label(text="View only: moved by parents", icon='INFO')
                box.label(text="Click the path to add a key", icon='BLANK1')
            if (data and data.get("approximate")) or (_SPACE.get(target.key) or {}).get("stale"):
                box.label(text="Path may be outdated: click Refresh", icon='ERROR')
        if shown > 1:
            box.label(text=iface_("{} paths shown").format(shown), icon='CURVE_PATH', translate=False)
        if waiting and context.mode.startswith('EDIT'):
            box.label(text="Leave Edit Mode once to show the others", icon='INFO')

        row = layout.row(align=True)
        row.operator("aemp.insert_current_location_key", icon='KEYFRAME_HLT')
        row.operator("aemp.delete_selected_keys", text="", icon='X')

        dense = bool(editable and (_PATH_CACHE.get(target.key) or {}).get("controls"))
        no_handles = bool(editable and (_PATH_CACHE.get(target.key) or {}).get("no_handles"))
        if _selection_matches(target) and no_handles:
            frame = float(_EDIT_SELECTION["frame"])
            box = layout.box()
            box.label(text=iface_("Frame {}").format(f"{frame:g}"), icon='KEYFRAME', translate=False)
            box.label(text="Curves: use control points", icon='INFO')
        elif _selection_matches(target) and dense:
            frame = float(_EDIT_SELECTION["frame"])
            box = layout.box()
            box.label(text=iface_("Frame {}").format(f"{frame:g}"), icon='KEYFRAME', translate=False)
            box.operator("aemp.smooth_path", icon='SMOOTHCURVE')
        elif _selection_matches(target) and editable:
            frame = float(_EDIT_SELECTION["frame"])
            box = layout.box()
            mode = iface_(_MODE_LABELS.get(_spatial_key_mode(target, frame), "Key"))
            box.label(text=iface_("Frame {}: {}").format(f"{frame:g}", mode), icon='KEYFRAME', translate=False)
            row = box.row(align=True)
            row.operator("aemp.toggle_selected_corner", icon='IPO_BEZIER')
            row.menu("AEMP_MT_handle_type", text="", icon='DOWNARROW_HLT')

        header, body = layout.panel("AEMP_PT_display", default_closed=True)
        header.label(text="Display")
        if body:
            _draw_display_options(body, prefs)

        header, body = layout.panel("AEMP_PT_range", default_closed=True)
        header.label(text="Frame Range")
        if body:
            body.prop(settings, "range_mode", text="")
            if settings.range_mode == 'WINDOW':
                row = body.row(align=True)
                row.prop(settings, "frames_before")
                row.prop(settings, "frames_after")

        header, body = layout.panel("AEMP_PT_appearance", default_closed=True)
        header.label(text="Appearance")
        if body:
            _draw_appearance_options(body, prefs)
            body.operator("aemp.reset_preferences", icon='LOOP_BACK')

        header, body = layout.panel("AEMP_PT_editing", default_closed=True)
        header.label(text="Editing")
        if body:
            _draw_editing_options(body, prefs)

        header, body = layout.panel("AEMP_PT_performance", default_closed=True)
        header.label(text="Performance")
        if body:
            _draw_performance_options(body, prefs)
            if _BAKE_INFO["error"]:
                body.label(text="Parent motion could not be evaluated", icon='ERROR')
            elif _BAKE_INFO["frames"]:
                body.label(translate=False, text=iface_("Last refresh: {} frames in {} ms").format(
                    _BAKE_INFO["frames"], int(round(_BAKE_INFO["ms"]))))

        header, body = layout.panel("AEMP_PT_shortcuts", default_closed=True)
        header.label(text="Shortcuts")
        if body:
            col = body.column(align=True)
            for keys, action in _SHORTCUTS:
                row = col.split(factor=0.45)
                row.label(text=keys)
                row.label(text=action)


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------

CLASSES = (
    AEMP_Settings,
    AEMP_Preferences,
    AEMP_OT_refresh_path,
    AEMP_OT_insert_key,
    AEMP_OT_delete_keys,
    AEMP_OT_set_handle_type,
    AEMP_MT_handle_type,
    AEMP_OT_toggle_selected_corner,
    AEMP_OT_smooth_path,
    AEMP_OT_toggle_control_points,
    AEMP_OT_modifier_click,
    AEMP_OT_reset_preferences,
    AEMP_GT_path_point,
    AEMP_GT_path_insert,
    AEMP_GGT_motion_path,
    VIEW3D_PT_editable_motion_path,
)

_HANDLERS = (
    ("undo_post", _on_undo_redo),
    ("redo_post", _on_undo_redo),
    ("load_post", _on_load),
    ("depsgraph_update_post", _on_depsgraph),
)


def _register_keymaps():
    # Modifier-clicks are scoped to the 3D View and PASS_THROUGH unless the
    # pointer is over a motion-path key, so Blender keeps its normal Alt/Shift
    # click behavior everywhere else.
    wm = bpy.context.window_manager
    keyconfig = wm.keyconfigs.addon if wm else None
    if keyconfig is None:
        return
    keymap = keyconfig.keymaps.new(name='3D View', space_type='VIEW_3D')
    for mode, kwargs in (('ALT', {'alt': True}), ('SHIFT', {'shift': True})):
        item = keymap.keymap_items.new('aemp.modifier_click', 'LEFTMOUSE', 'PRESS', **kwargs)
        item.properties.mode = mode
        _ADDON_KEYMAPS.append((keymap, item))
    item = keymap.keymap_items.new('aemp.toggle_control_points', 'C', 'PRESS', shift=True, alt=True)
    _ADDON_KEYMAPS.append((keymap, item))


def _unregister_keymaps():
    for keymap, item in _ADDON_KEYMAPS:
        try:
            keymap.keymap_items.remove(item)
        except (ReferenceError, RuntimeError):
            continue
    _ADDON_KEYMAPS.clear()


def register():
    global _DRAW_HANDLE, _DRAW_HANDLE_2D
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.aemp_settings = PointerProperty(type=AEMP_Settings)
    bpy.app.translations.register(__name__, TRANSLATIONS)
    _register_keymaps()

    for name, function in _HANDLERS:
        handler = getattr(bpy.app.handlers, name)
        if function not in handler:
            handler.append(function)

    if _DRAW_HANDLE is None:
        _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw_motion_path, (), 'WINDOW', 'POST_VIEW')
    if _DRAW_HANDLE_2D is None:
        _DRAW_HANDLE_2D = bpy.types.SpaceView3D.draw_handler_add(_draw_motion_path_2d, (), 'WINDOW', 'POST_PIXEL')
    if not bpy.app.timers.is_registered(_live_update_timer):
        bpy.app.timers.register(_live_update_timer, first_interval=_TIMER_INTERVAL, persistent=True)


def unregister():
    global _EDITING
    _unregister_keymaps()
    for name, function in _HANDLERS:
        handler = getattr(bpy.app.handlers, name)
        if function in handler:
            handler.remove(function)
    if bpy.app.timers.is_registered(_live_update_timer):
        bpy.app.timers.unregister(_live_update_timer)
    _clear_cache()
    _set_edit_selection(None)
    _EDITING = False

    for handle_name in ("_DRAW_HANDLE", "_DRAW_HANDLE_2D"):
        handle = globals()[handle_name]
        if handle is not None:
            try:
                bpy.types.SpaceView3D.draw_handler_remove(handle, 'WINDOW')
            except (ReferenceError, RuntimeError, ValueError):
                pass
            globals()[handle_name] = None

    bpy.app.translations.unregister(__name__)
    if hasattr(bpy.types.Scene, "aemp_settings"):
        del bpy.types.Scene.aemp_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
