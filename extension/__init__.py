bl_info = {
    "name": "Editable Motion Paths",
    "author": "Editable Motion Paths contributors",
    "version": (0, 9, 4),
    "blender": (5, 2, 0),
    "location": "View3D > Sidebar > Motion Path",
    "description": "Interactive editable motion paths for object Location keyframes",
    "category": "Animation",
}

import bpy
import gpu
import blf
import math
from bpy.types import Operator, Panel, PropertyGroup, Menu, Gizmo, GizmoGroup
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, FloatVectorProperty
from gpu_extras.batch import batch_for_shader
from bpy_extras import view3d_utils
from bpy_extras.anim_utils import animdata_get_channelbag_for_assigned_slot
from mathutils import Vector, Matrix
from bpy.app.handlers import persistent

# -----------------------------------------------------------------------------
# Runtime state
# -----------------------------------------------------------------------------

_DRAW_HANDLE = None
_DRAW_HANDLE_2D = None
_EDIT_SESSION_ACTIVE = False
_EDIT_SESSION_SERIAL = 0
_PATH_CACHE = {}
_CACHE_SIGNATURES = {}
_ADDON_KEYMAPS = []
_CACHE_DIRTY = True
_IS_BUILDING = False
_TIMER_INTERVAL = 0.033  # ~30 Hz: cheap F-Curve evaluation, no scene.frame_set().

# Current viewport-edit selection. This is runtime UI state only; animation data
# remains entirely in Blender F-Curves.
_EDIT_SELECTION = {
    "object_name": "",
    "frame": None,
    "part": "NONE",  # NONE, KEY, LEFT, RIGHT
}
_HOVER_SELECTION = {
    "object_name": "",
    "frame": None,
    "part": "NONE",
}

_MULTI_SELECTION = set()  # {(object_name, frame)} for multi-key editing.



def _cache_key(obj):
    return obj.as_pointer() if obj else 0


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
# Blender 5.2 animation access
# -----------------------------------------------------------------------------

def _iter_action_fcurves(obj):
    """Yield F-Curves from the Action Slot assigned to this object."""
    animation_data = obj.animation_data
    if animation_data is None or animation_data.action is None or animation_data.action_slot is None:
        return

    channelbag = animdata_get_channelbag_for_assigned_slot(animation_data)
    if channelbag is None:
        return

    yield from channelbag.fcurves


def _location_fcurves(obj):
    result = {}
    for fcu in _iter_action_fcurves(obj) or ():
        if fcu.data_path == "location" and 0 <= fcu.array_index <= 2:
            result[fcu.array_index] = fcu
    return result


def _location_keyframes(obj):
    frames = set()
    for fcu in _location_fcurves(obj).values():
        for kp in fcu.keyframe_points:
            frames.add(float(kp.co.x))
    return sorted(frames)


def _has_location_animation(obj):
    return bool(_location_fcurves(obj))


def _keypoint_at_frame(fcu, frame, epsilon=0.001):
    for kp in fcu.keyframe_points:
        if abs(float(kp.co.x) - float(frame)) <= epsilon:
            return kp
    return None


def _deselect_location_keys(obj):
    for fcu in _location_fcurves(obj).values():
        for kp in fcu.keyframe_points:
            kp.select_control_point = False
            kp.select_left_handle = False
            kp.select_right_handle = False


def _select_location_key_at_frame(obj, frame, part='KEY', epsilon=0.001, clear=True):
    if clear:
        _deselect_location_keys(obj)
    for fcu in _location_fcurves(obj).values():
        kp = _keypoint_at_frame(fcu, frame, epsilon)
        if kp is None:
            continue
        if part == 'KEY':
            kp.select_control_point = True
        elif part == 'LEFT':
            kp.select_left_handle = True
        elif part == 'RIGHT':
            kp.select_right_handle = True


def _set_edit_selection(obj, frame=None, part='NONE', extend=False, toggle=False):
    global _MULTI_SELECTION
    name = obj.name if obj else ""
    f = float(frame) if frame is not None else None

    if obj is None or f is None:
        _MULTI_SELECTION.clear()
    elif part == 'KEY':
        token = (name, f)
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
        _MULTI_SELECTION = {(name, f)}

    _EDIT_SELECTION["object_name"] = name
    _EDIT_SELECTION["frame"] = f
    _EDIT_SELECTION["part"] = part
    if obj and f is not None:
        _select_location_key_at_frame(obj, f, part, clear=not extend)
        scene = bpy.context.scene
        if scene is not None and hasattr(scene, "aemp_settings"):
            scene.aemp_settings.show_selected_section = True
    _tag_redraw_all_view3d()

def _is_multi_selected(obj_name, frame):
    return (obj_name, float(frame)) in _MULTI_SELECTION

def _display_objects(context, settings):
    if settings.display_mode == 'SELECTED':
        objs = [o for o in context.selected_objects if _has_location_animation(o)]
        if context.active_object and _has_location_animation(context.active_object) and context.active_object not in objs:
            objs.append(context.active_object)
        return objs
    obj = context.active_object
    return [obj] if obj and _has_location_animation(obj) else []


# -----------------------------------------------------------------------------
# Fast path evaluation (no scene.frame_set)
# -----------------------------------------------------------------------------

def _frame_bounds(context, obj, settings):
    scene = context.scene
    if settings.range_mode == 'SCENE':
        return scene.frame_start, scene.frame_end
    if settings.range_mode == 'WINDOW':
        return (
            int(scene.frame_current - settings.frames_before),
            int(scene.frame_current + settings.frames_after),
        )
    keys = _location_keyframes(obj)
    if len(keys) < 2:
        return None
    return int(min(keys)), int(max(keys))


def _world_mapping(obj):
    """Return affine mapping from object Location to current world translation.

    For ordinary object transforms / static parenting this is exact. It also keeps
    the overlay stable while the object is interactively transformed. Constraints
    or time-varying parent transforms can make future/past samples approximate;
    a native Blender implementation could evaluate those directly in the depsgraph.
    """
    if obj.parent:
        parent_basis = obj.parent.matrix_world @ obj.matrix_parent_inverse
        linear = parent_basis.to_3x3().copy()
    else:
        linear = Matrix.Identity(3)
    current_local = Vector(obj.location)
    offset = obj.matrix_world.translation.copy() - (linear @ current_local)
    return linear, offset


def _local_to_world(local, mapping):
    linear, offset = mapping
    return offset + (linear @ Vector(local))


def _world_to_local(world, mapping):
    linear, offset = mapping
    return linear.inverted_safe() @ (Vector(world) - offset)


def _eval_location_base(obj, curves, frame):
    # Missing channels retain their current component. This mirrors Blender's
    # partial animation behaviour without creating hidden data.
    loc = Vector(obj.location)
    for axis in range(3):
        fcu = curves.get(axis)
        if fcu is not None:
            loc[axis] = fcu.evaluate(frame)
    return loc


def _smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _live_transform_delta(context, obj, curves, keyframes):
    """Return a temporary display-only key displacement while Auto Key + G runs.

    Blender may not commit the new F-Curve value until the transform is confirmed.
    We therefore deform the displayed path around the current keyed frame using
    the live object Location. Nothing is written to the animation here.
    """
    scene = context.scene
    tool_settings = getattr(scene, "tool_settings", None)
    if not tool_settings or not getattr(tool_settings, "use_keyframe_insert_auto", False):
        return None

    frame = float(scene.frame_current)

    # IMPORTANT: Auto Key often does not create the new key until Blender's
    # transform operator is confirmed.  The previous implementation only
    # previewed motion when a key already existed on the current frame, which
    # made the path stay frozen during G and jump only on validation.  Compare
    # the live object transform with the F-Curve-evaluated position even on an
    # unkeyed frame, so the overlay previews the future Auto-Key continuously.
    keyed = _eval_location_base(obj, curves, frame)
    delta = Vector(obj.location) - keyed
    if delta.length_squared < 1.0e-12:
        return None

    prev_frame = None
    next_frame = None
    for k in keyframes:
        if k < frame - 0.001:
            prev_frame = k
        elif k > frame + 0.001:
            next_frame = k
            break
    return frame, delta, prev_frame, next_frame


def _apply_live_delta(frame, loc, live):
    if live is None:
        return loc
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
    return loc + delta * weight


def _handle_record(obj, curves, frame, mapping):
    """Build *spatial* tangent handles from the three temporal F-Curves.

    Blender stores a Bezier handle for each scalar F-Curve in (time, value)
    space. Treating the three handle Y values directly as XYZ coordinates is
    only correct when X/Y/Z happen to use identical handle times. V0.5 did
    that, which is why handle types could jump, loop, or appear ineffective.

    Here we reconstruct the true spatial tangent from dy/dt for every axis and
    display it at one shared visual time distance. Editing performs the inverse
    mapping, so the existing temporal handle X positions are preserved.
    """
    key_local = _eval_location_base(obj, curves, frame)
    left_slopes = Vector((0.0, 0.0, 0.0))
    right_slopes = Vector((0.0, 0.0, 0.0))
    left_dts = []
    right_dts = []
    left_types = []
    right_types = []

    for axis in range(3):
        fcu = curves.get(axis)
        if fcu is None:
            continue
        kp = _keypoint_at_frame(fcu, frame)
        if kp is None:
            continue
        key_local[axis] = kp.co.y

        ldt = max(1.0e-6, float(kp.co.x - kp.handle_left.x))
        rdt = max(1.0e-6, float(kp.handle_right.x - kp.co.x))
        left_dts.append(ldt)
        right_dts.append(rdt)
        left_slopes[axis] = (float(kp.co.y) - float(kp.handle_left.y)) / ldt
        right_slopes[axis] = (float(kp.handle_right.y) - float(kp.co.y)) / rdt
        left_types.append(kp.handle_left_type)
        right_types.append(kp.handle_right_type)

    # A common temporal distance turns the derivatives into coherent XYZ
    # control points. The median-ish average is stable even if individual axes
    # have different temporal easing handles.
    visual_left_dt = sum(left_dts) / len(left_dts) if left_dts else 1.0
    visual_right_dt = sum(right_dts) / len(right_dts) if right_dts else 1.0
    visual_left_dt = max(0.05, visual_left_dt)
    visual_right_dt = max(0.05, visual_right_dt)

    left_local = key_local - left_slopes * visual_left_dt
    right_local = key_local + right_slopes * visual_right_dt

    return {
        "frame": float(frame),
        "key": _local_to_world(key_local, mapping),
        "left": _local_to_world(left_local, mapping),
        "right": _local_to_world(right_local, mapping),
        "left_time": float(frame) - visual_left_dt,
        "right_time": float(frame) + visual_right_dt,
        "left_visual_dt": visual_left_dt,
        "right_visual_dt": visual_right_dt,
        "left_types": tuple(left_types),
        "right_types": tuple(right_types),
        "has_left": bool(left_dts),
        "has_right": bool(right_dts),
    }


def _animation_signature(obj, settings):
    if not obj or not _has_location_animation(obj):
        return None
    curves = []
    for fc in _location_fcurves(obj).values():
        points = tuple(
            (
                tuple(round(float(v), 7) for v in kp.co),
                tuple(round(float(v), 7) for v in kp.handle_left),
                tuple(round(float(v), 7) for v in kp.handle_right),
                kp.interpolation,
                kp.handle_left_type,
                kp.handle_right_type,
            )
            for kp in fc.keyframe_points
        )
        curves.append((fc.array_index, points, fc.mute))

    # matrix/location are included specifically so an in-progress native G transform
    # redraws the display-only live deformation without clearing the old cache.
    matrix_sig = tuple(round(float(v), 6) for row in obj.matrix_world for v in row)
    loc_sig = tuple(round(float(v), 6) for v in obj.location)
    return (
        tuple(curves),
        matrix_sig,
        loc_sig,
        settings.range_mode,
        settings.sample_step,
        settings.adaptive_sampling,
        settings.max_samples,
        settings.frames_before,
        settings.frames_after,
        settings.show_handles,
        bpy.context.scene.frame_start,
        bpy.context.scene.frame_end,
        bpy.context.scene.frame_current,
    )


def _build_path_cache(context, obj):
    """Build a complete replacement cache and swap it atomically.

    Critically: this function never changes scene.frame_current. That removes the
    viewport flicker caused by repeatedly calling scene.frame_set() during G.
    """
    global _IS_BUILDING
    if _IS_BUILDING or obj is None:
        return _PATH_CACHE.get(_cache_key(obj)) if obj else None

    settings = context.scene.aemp_settings
    bounds = _frame_bounds(context, obj, settings)
    key = _cache_key(obj)
    if bounds is None:
        _PATH_CACHE.pop(key, None)
        _CACHE_SIGNATURES.pop(key, None)
        _tag_redraw_all_view3d()
        return None

    start, end = bounds
    if end < start:
        start, end = end, start
    step = max(1, int(settings.sample_step))
    if settings.adaptive_sampling and end > start:
        auto_step = int(math.ceil((end - start + 1) / max(2, int(settings.max_samples))))
        step = max(step, auto_step)
    frames = list(range(start, end + 1, step))
    if not frames or frames[-1] != end:
        frames.append(end)

    curves = _location_fcurves(obj)
    keyframes = _location_keyframes(obj)
    mapping = _world_mapping(obj)
    live = _live_transform_delta(context, obj, curves, keyframes)

    _IS_BUILDING = True
    try:
        samples = []
        for frame in frames:
            loc = _eval_location_base(obj, curves, frame)
            loc = _apply_live_delta(float(frame), loc, live)
            samples.append((float(frame), _local_to_world(loc, mapping)))

        key_positions = []
        handles = {}
        for frame in keyframes:
            loc = _eval_location_base(obj, curves, frame)
            loc = _apply_live_delta(frame, loc, live)
            world = _local_to_world(loc, mapping)
            key_positions.append((frame, world))
            rec = _handle_record(obj, curves, frame, mapping)
            # Live transform displacement should move the displayed key + handles
            # together, matching Blender's common auto-handle behaviour visually.
            if live is not None and abs(frame - live[0]) <= 0.001:
                world_delta = mapping[0] @ live[1]
                rec["key"] = rec["key"] + world_delta
                rec["left"] = rec["left"] + world_delta
                rec["right"] = rec["right"] + world_delta
            handles[frame] = rec

        data = {
            "object_name": obj.name,
            "samples": samples,
            "keys": key_positions,
            "handles": handles,
            "start": start,
            "end": end,
            "mapping": mapping,
        }
        # Atomic swap: the draw callback never sees a half-built/empty path.
        _PATH_CACHE[key] = data
        _CACHE_SIGNATURES[key] = _animation_signature(obj, settings)
    finally:
        _IS_BUILDING = False

    _tag_redraw_all_view3d()
    return data


def _get_cache(context, obj, build_if_missing=True):
    data = _PATH_CACHE.get(_cache_key(obj))
    if data is None and build_if_missing:
        data = _build_path_cache(context, obj)
    return data


def _mark_dirty(*_args):
    global _CACHE_DIRTY
    _CACHE_DIRTY = True
    _tag_redraw_all_view3d()


def _clear_cache(*_args):
    global _CACHE_DIRTY
    _CACHE_DIRTY = True
    _PATH_CACHE.clear()
    _CACHE_SIGNATURES.clear()
    _tag_redraw_all_view3d()


@persistent
def _on_undo_redo(_dummy):
    # Keep the last valid pixels until the next cheap rebuild, avoiding flashes.
    _mark_dirty()


@persistent
def _on_load(_dummy):
    _clear_cache()


@persistent
def _on_depsgraph(_scene, _depsgraph):
    # Do not force a full rebuild for every depsgraph pulse. The timer compares a
    # compact animation/transform signature and only rebuilds paths that changed.
    # This is important for heavy scenes and avoids needless redraw churn.
    if not _IS_BUILDING:
        _tag_redraw_all_view3d()


def _live_update_timer():
    global _CACHE_DIRTY
    if _DRAW_HANDLE is None:
        return None
    if _IS_BUILDING:
        return _TIMER_INTERVAL

    try:
        context = bpy.context
        scene = context.scene
        obj = context.active_object
        if not scene or not hasattr(scene, 'aemp_settings'):
            return _TIMER_INTERVAL
        settings = scene.aemp_settings

        if not settings.show_path:
            return _TIMER_INTERVAL

        visible = _display_objects(context, settings)
        visible_keys = set()
        for obj in visible:
            key = _cache_key(obj)
            visible_keys.add(key)
            signature = _animation_signature(obj, settings)
            if signature is None:
                _PATH_CACHE.pop(key, None)
                _CACHE_SIGNATURES.pop(key, None)
                continue
            if _CACHE_DIRTY or signature != _CACHE_SIGNATURES.get(key) or key not in _PATH_CACHE:
                _build_path_cache(context, obj)

        # Drop stale caches when switching active/selected display mode.
        for key in list(_PATH_CACHE.keys()):
            if key not in visible_keys:
                _PATH_CACHE.pop(key, None)
                _CACHE_SIGNATURES.pop(key, None)
        _CACHE_DIRTY = False
    except (ReferenceError, RuntimeError, AttributeError):
        pass
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


def _screen_disc_vertices(context, pos, radius_px, segments=20):
    """Return world-space triangles for a screen-space disc.

    Blender's point-size rendering is backend dependent (notably Metal/macOS).
    Building a tiny camera-facing disc from projected pixel coordinates gives
    predictable key size and color on both Metal and OpenGL backends.
    """
    region = getattr(context, 'region', None)
    rv3d = getattr(context, 'region_data', None)
    if region is None or rv3d is None:
        return []
    center_2d = view3d_utils.location_3d_to_region_2d(region, rv3d, pos)
    if center_2d is None:
        return []
    radius_px = max(1.0, float(radius_px))
    ring = []
    for i in range(max(8, int(segments))):
        a = (2.0 * math.pi * i) / max(8, int(segments))
        p2 = center_2d + Vector((math.cos(a) * radius_px, math.sin(a) * radius_px))
        ring.append(view3d_utils.region_2d_to_location_3d(region, rv3d, p2, pos))
    verts = []
    for i, a in enumerate(ring):
        b = ring[(i + 1) % len(ring)]
        verts.extend((pos, a, b))
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

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.blend_set('ALPHA')

    for obj in _display_objects(context, settings):
        data = _PATH_CACHE.get(_cache_key(obj))
        if not data:
            continue
        samples = data.get("samples", [])
        if len(samples) < 2:
            continue

        gpu.state.depth_test_set('NONE' if settings.xray else 'LESS_EQUAL')
        gpu.state.line_width_set(settings.line_width)
        shader.bind()

        # Past/future split around the current frame gives immediate temporal orientation.
        for (f0, p0), (f1, p1) in zip(samples[:-1], samples[1:]):
            if settings.show_time_split and max(f0, f1) <= scene.frame_current:
                color = tuple(settings.past_color)
            else:
                color = tuple(settings.path_color)
            shader.uniform_float("color", color)
            batch_for_shader(shader, 'LINES', {"pos": [p0, p1]}).draw(shader)

        if settings.show_samples and len(samples) > 2:
            sample_color = tuple(settings.path_color[:3]) + (min(settings.path_color[3], 0.60),)
            _draw_points(shader, [co for _, co in samples[1:-1]], settings.sample_size, sample_color)

        # Interactive key/handle points are owned by native gizmos when direct
        # editing is enabled. Drawing a second point layer here caused backend
        # differences on macOS/Metal and made size/color changes look ignored.
        gpu.state.depth_test_set('NONE' if (settings.xray or settings.direct_edit) else 'LESS_EQUAL')
        if not settings.direct_edit:
            for frame, pos in data.get("keys", []):
                selected = _is_multi_selected(obj.name, frame)
                if selected:
                    col = tuple(settings.selected_key_color)
                    size = settings.key_size + 3.0
                else:
                    rec = data.get("handles", {}).get(frame)
                    is_vector = rec and _spatial_key_mode(obj, frame) == 'VECTOR'
                    col = tuple(settings.corner_key_color if is_vector else settings.key_color)
                    size = settings.key_size
                if settings.key_outline:
                    _draw_screen_disc(context, shader, pos, size + settings.key_outline_size * 2.0, (0.02, 0.02, 0.02, 0.90))
                _draw_screen_disc(context, shader, pos, size, col)

        if (
            obj == context.active_object and settings.show_handles
            and _EDIT_SELECTION["object_name"] == obj.name
            and _EDIT_SELECTION["frame"] is not None
        ):
            frame = _EDIT_SELECTION["frame"]
            rec = next((candidate for k, candidate in data["handles"].items() if abs(k-frame)<=0.001), None)
            if rec:
                key, left, right = rec["key"], rec["left"], rec["right"]
                gpu.state.line_width_set(1.0)
                shader.uniform_float("color", tuple(settings.handle_line_color))
                batch_for_shader(shader, 'LINES', {"pos": [left, key, key, right]}).draw(shader)
                if not settings.direct_edit:
                    _draw_screen_disc(context, shader, left, settings.handle_size, tuple(settings.handle_color))
                    _draw_screen_disc(context, shader, right, settings.handle_size, tuple(settings.handle_color))
                    if _EDIT_SELECTION["part"] in {'LEFT','RIGHT'}:
                        p = left if _EDIT_SELECTION["part"] == 'LEFT' else right
                        _draw_screen_disc(context, shader, p, settings.handle_size + 3.0, tuple(settings.selected_key_color))

    gpu.state.line_width_set(1.0)
    gpu.state.point_size_set(1.0)
    gpu.state.depth_test_set('NONE')
    gpu.state.blend_set('NONE')


def _draw_motion_path_2d():
    context = bpy.context
    if context.area is None or context.area.type != 'VIEW_3D':
        return
    settings = getattr(context.scene, "aemp_settings", None)
    if settings is None or not settings.show_path:
        return

    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    for obj in _display_objects(context, settings):
        data = _PATH_CACHE.get(_cache_key(obj))
        if not data:
            continue
        samples = data.get("samples", [])

        if settings.show_direction and len(samples) >= 3:
            spacing = max(2, int(settings.arrow_spacing))
            size = float(settings.arrow_size)
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
                coords.extend([(p1.x,p1.y,0.0),(left.x,left.y,0.0),(p1.x,p1.y,0.0),(right.x,right.y,0.0)])
            if coords:
                gpu.state.blend_set('ALPHA')
                gpu.state.line_width_set(max(1.0, settings.line_width))
                batch = batch_for_shader(shader, 'LINES', {"pos": coords})
                shader.bind(); shader.uniform_float("color", tuple(settings.path_color)); batch.draw(shader)

        if settings.show_frame_labels or settings.show_key_type_badges:
            font_id = 0
            blf.size(font_id, int(settings.label_size))
            for frame, pos in data.get("keys", []):
                p = _screen_point(context, pos)
                if p is None:
                    continue
                parts = []
                if settings.show_frame_labels:
                    parts.append(str(int(round(frame))) if abs(frame-round(frame)) < 0.001 else f"{frame:g}")
                if settings.show_key_type_badges:
                    mode = _spatial_key_mode(obj, frame)
                    parts.append({'VECTOR':'V','ALIGNED':'S','AUTO':'A','FREE':'F','MIXED':'M'}.get(mode,''))
                text = "  ".join(x for x in parts if x)
                if not text:
                    continue
                blf.position(font_id, p.x + 8.0, p.y + 8.0, 0)
                col = settings.label_color
                blf.color(font_id, *col)
                blf.draw(font_id, text)

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


def _nearest_cached_sample_2d(context, obj, mouse_xy, threshold_px, region=None, rv3d=None):
    data = _get_cache(context, obj, build_if_missing=True)
    if not data:
        return None
    mouse = Vector(mouse_xy)
    best = None
    best_dist = float('inf')
    for frame, co3d in data["samples"]:
        p2d = _screen_point(context, co3d, region, rv3d)
        if p2d is None:
            continue
        dist = (p2d - mouse).length
        if dist < best_dist:
            best_dist = dist
            best = (frame, co3d.copy(), p2d.copy())
    if best is None or best_dist > threshold_px:
        return None
    return best


def _spatial_key_mode(obj, frame):
    types = []
    for fc in _location_fcurves(obj).values():
        kp = _keypoint_at_frame(fc, frame)
        if kp is not None:
            types.extend((kp.handle_left_type, kp.handle_right_type))
    if types and all(t == 'VECTOR' for t in types):
        return 'VECTOR'
    if types and all(t in {'AUTO', 'AUTO_CLAMPED'} for t in types):
        return 'AUTO'
    if types and all(t == 'ALIGNED' for t in types):
        return 'ALIGNED'
    if types and all(t == 'FREE' for t in types):
        return 'FREE'
    return 'MIXED' if types else 'NONE'

def _toggle_corner_smooth(obj, frame):
    target = 'ALIGNED' if _spatial_key_mode(obj, frame) == 'VECTOR' else 'VECTOR'
    changed = False
    for fc in _location_fcurves(obj).values():
        kp = _keypoint_at_frame(fc, frame)
        if kp is None:
            continue
        kp.handle_left_type = target
        kp.handle_right_type = target
        fc.update()
        changed = True
    if changed:
        _mark_dirty()
    return target if changed else None

def _selected_frames_for_object(obj):
    frames = sorted(f for name, f in _MULTI_SELECTION if name == obj.name)
    return frames

# -----------------------------------------------------------------------------
# Handle helpers
# -----------------------------------------------------------------------------

def _snapshot_key_safe(obj, frame):
    """Snapshot scalar key data without keeping RNA references across modal events.

    Blender's Python API warns that direct references to data owned by containers
    can become invalid when the data is updated or undo/redo happens.  Motion-path
    dragging updates F-Curves continuously, so store only plain Python values and
    reacquire each F-Curve/key on every event.
    """
    snapshot = []
    for axis, fc in _location_fcurves(obj).items():
        kp = _keypoint_at_frame(fc, frame)
        if kp is None:
            continue
        snapshot.append({
            "axis": int(axis),
            "co": tuple(kp.co),
            "left": tuple(kp.handle_left),
            "right": tuple(kp.handle_right),
            "left_type": str(kp.handle_left_type),
            "right_type": str(kp.handle_right_type),
        })
    return snapshot


def _safe_key_for_axis(obj, axis, frame):
    fc = _location_fcurves(obj).get(int(axis))
    if fc is None:
        return None, None
    return fc, _keypoint_at_frame(fc, frame)


def _restore_snapshot_safe(obj, frame, snapshot):
    touched = []
    for item in snapshot:
        fc, kp = _safe_key_for_axis(obj, item["axis"], frame)
        if fc is None or kp is None:
            continue
        kp.co = item["co"]
        kp.handle_left = item["left"]
        kp.handle_right = item["right"]
        kp.handle_left_type = item["left_type"]
        kp.handle_right_type = item["right_type"]
        touched.append(fc)
    for fc in touched:
        fc.update()


def _set_handle_type_on_selection(obj, frame, part, handle_type):
    changed = False
    for fc in _location_fcurves(obj).values():
        kp = _keypoint_at_frame(fc, frame)
        if kp is None:
            continue
        if part in {'KEY', 'LEFT'}:
            kp.handle_left_type = handle_type
            changed = True
        if part in {'KEY', 'RIGHT'}:
            kp.handle_right_type = handle_type
            changed = True
        fc.update()
    if changed:
        _mark_dirty()
    return changed


def _selection_handle_type(obj, frame, part):
    """Return a compact human-readable handle type for the current selection."""
    left = set()
    right = set()
    for fc in _location_fcurves(obj).values():
        kp = _keypoint_at_frame(fc, frame)
        if kp is None:
            continue
        left.add(kp.handle_left_type)
        right.add(kp.handle_right_type)
    values = left if part == 'LEFT' else right if part == 'RIGHT' else (left | right)
    if not values:
        return None
    if len(values) == 1:
        value = next(iter(values))
        return {
            'AUTO': 'Auto',
            'AUTO_CLAMPED': 'Auto limité',
            'ALIGNED': 'Alignée',
            'FREE': 'Libre',
            'VECTOR': 'Vector',
        }.get(value, value.title())
    return 'Mixte'


# -----------------------------------------------------------------------------
# Operators
# -----------------------------------------------------------------------------

class AEMP_OT_toggle_path(Operator):
    bl_idname = "aemp.toggle_path"
    bl_label = "Afficher/Masquer la trajectoire"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.aemp_settings
        settings.show_path = not settings.show_path
        if settings.show_path and context.active_object:
            _build_path_cache(context, context.active_object)
        _tag_redraw_all_view3d()
        return {'FINISHED'}


class AEMP_OT_refresh_path(Operator):
    bl_idname = "aemp.refresh_path"
    bl_label = "Recalculer la trajectoire"
    bl_options = {'REGISTER'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or not _has_location_animation(obj):
            self.report({'WARNING'}, "Sélectionne un objet avec des keyframes Location.")
            return {'CANCELLED'}
        _build_path_cache(context, obj)
        return {'FINISHED'}


class AEMP_OT_insert_current_location_key(Operator):
    bl_idname = "aemp.insert_current_location_key"
    bl_label = "Ajouter une clé de position ici"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            return {'CANCELLED'}
        frame = context.scene.frame_current
        obj.keyframe_insert(data_path="location", frame=frame, group="Location")
        _set_edit_selection(obj, frame, 'KEY')
        _mark_dirty()
        _build_path_cache(context, obj)
        return {'FINISHED'}


class AEMP_OT_add_key_on_path(Operator):
    bl_idname = "aemp.add_key_on_path"
    bl_label = "Ajouter une clé sur la trajectoire"
    bl_options = {'REGISTER', 'UNDO', 'BLOCKING'}

    def invoke(self, context, event):
        if context.area.type != 'VIEW_3D':
            return {'CANCELLED'}
        obj = context.active_object
        if obj is None or not _has_location_animation(obj):
            self.report({'ERROR'}, "Ajoute d'abord au moins deux keyframes Location.")
            return {'CANCELLED'}
        context.scene.aemp_settings.show_path = True
        _build_path_cache(context, obj)
        self.obj_name = obj.name
        context.window_manager.modal_handler_add(self)
        context.window.cursor_modal_set('CROSSHAIR')
        context.area.header_text_set("Motion Path - Clic: ajouter une clé | Shift+Clic: continuer | Esc/RMB: quitter")
        return {'RUNNING_MODAL'}

    def _finish(self, context):
        if context.window is not None:
            context.window.cursor_modal_restore()
        if context.area:
            context.area.header_text_set(None)
        _tag_redraw_all_view3d()

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            obj = bpy.data.objects.get(self.obj_name)
            if obj is None:
                self._finish(context)
                return {'CANCELLED'}
            pick = _nearest_cached_sample_2d(
                context, obj,
                (event.mouse_region_x, event.mouse_region_y),
                context.scene.aemp_settings.pick_radius,
            )
            if pick is None:
                return {'RUNNING_MODAL'}
            frame = int(round(pick[0]))
            context.scene.frame_set(frame)
            context.view_layer.objects.active = obj
            obj.select_set(True)
            obj.keyframe_insert(data_path="location", frame=frame, group="Location")
            _set_edit_selection(obj, frame, 'KEY')
            _mark_dirty()
            _build_path_cache(context, obj)
            self.report({'INFO'}, f"Keyframe Location ajoutée frame {frame}")
            if event.shift:
                return {'RUNNING_MODAL'}
            self._finish(context)
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


class AEMP_OT_set_handle_type(Operator):
    bl_idname = "aemp.set_handle_type"
    bl_label = "Type de poignée"
    bl_options = {'REGISTER', 'UNDO'}

    handle_type: EnumProperty(
        items=[
            ('AUTO', "Auto", "Courbe fluide calculée automatiquement par Blender"),
            ('ALIGNED', "Alignée", "Tangentes manuelles alignées pour garder une transition lisse"),
            ('FREE', "Libre", "Chaque tangente est indépendante"),
            ('VECTOR', "Vector", "Tangente dirigée vers la clé voisine pour un segment droit / angle net"),
        ]
    )

    def execute(self, context):
        obj = context.active_object
        frame = _EDIT_SELECTION["frame"]
        part = _EDIT_SELECTION["part"]
        if obj is None or frame is None or _EDIT_SELECTION["object_name"] != obj.name:
            return {'CANCELLED'}
        if _set_handle_type_on_selection(obj, frame, part, self.handle_type):
            _build_path_cache(context, obj)
            return {'FINISHED'}
        return {'CANCELLED'}


class AEMP_MT_handle_type(Menu):
    bl_label = "Type de poignée"
    bl_idname = "AEMP_MT_handle_type"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Interpolation spatiale")
        for value, label in (
            ('AUTO', "Auto - lissage automatique"),
            ('ALIGNED', "Alignée - manuel lisse"),
            ('FREE', "Libre - côtés indépendants"),
            ('VECTOR', "Vector - droit / angle net"),
        ):
            op = layout.operator("aemp.set_handle_type", text=label)
            op.handle_type = value


class AEMP_OT_toggle_selected_corner(Operator):
    bl_idname = "aemp.toggle_selected_corner"
    bl_label = "Angle / Courbe"
    bl_description = "Basculer la clé active entre un angle Vector et une courbe Alignée"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        frame = _EDIT_SELECTION.get("frame")
        if obj is None or frame is None or _EDIT_SELECTION.get("object_name") != obj.name:
            return {'CANCELLED'}
        if _toggle_corner_smooth(obj, frame) is None:
            return {'CANCELLED'}
        _build_path_cache(context, obj)
        _tag_redraw_all_view3d()
        return {'FINISHED'}


class AEMP_OT_modifier_click(Operator):
    """Modifier-click fallback with Alt-drag manual tangent control."""
    bl_idname = "aemp.modifier_click"
    bl_label = "Motion Path Modifier Click"
    bl_options = {'UNDO'}

    mode: EnumProperty(items=[('ALT','Alt',''),('SHIFT','Shift','')], default='ALT')

    def _pick_key(self, context, event):
        settings = getattr(context.scene, 'aemp_settings', None)
        obj = context.active_object
        if not settings or not settings.show_path or not settings.direct_edit or obj is None:
            return None
        data = _get_cache(context, obj, build_if_missing=True)
        if not data:
            return None
        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        best = None
        for frame, pos in data.get('keys', []):
            p2d = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, pos)
            if p2d is None:
                continue
            d = (mouse - p2d).length
            if best is None or d < best[0]:
                best = (d, float(frame), pos.copy())
        if best is None or best[0] > max(float(settings.pick_radius), float(settings.key_size) + 6.0):
            return None
        return obj, data, best[1], best[2]

    def invoke(self, context, event):
        if context.area is None or context.area.type != 'VIEW_3D':
            return {'PASS_THROUGH'}
        hit = self._pick_key(context, event)
        if hit is None:
            return {'PASS_THROUGH'}
        obj, data, frame, world_pos = hit

        if self.mode == 'SHIFT':
            _set_edit_selection(obj, frame, 'KEY', extend=True, toggle=True)
            _select_location_key_at_frame(obj, frame, 'KEY', clear=False)
            _tag_redraw_all_view3d()
            return {'FINISHED'}

        self.obj_name = obj.name
        self.frame = float(frame)
        self._start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._key_world = world_pos.copy()
        self._mapping = data.get('mapping') or _world_mapping(obj)
        self._snapshot = _snapshot_key_safe(obj, frame)
        self._drag_started = False
        self._threshold = 7.0
        _set_edit_selection(obj, frame, 'KEY')
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def _apply_manual_tangent(self, context, mouse):
        obj = bpy.data.objects.get(self.obj_name)
        if obj is None:
            return
        if context.region is None or context.region_data is None:
            return
        dragged_world = view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, mouse, self._key_world)
        key_local = _eval_location_base(obj, _location_fcurves(obj), self.frame)
        dragged_local = _world_to_local(dragged_world, self._mapping)
        tangent = dragged_local - key_local
        data = _get_cache(context, obj, build_if_missing=True)
        rec = data.get('handles', {}).get(float(self.frame)) if data else None
        vldt = max(1.0e-6, float(rec.get('left_visual_dt', 1.0))) if rec else 1.0
        vrdt = max(1.0e-6, float(rec.get('right_visual_dt', 1.0))) if rec else 1.0
        touched = []
        for item in self._snapshot:
            fc, kp = _safe_key_for_axis(obj, item['axis'], self.frame)
            if fc is None or kp is None:
                continue
            axis = item['axis']
            kp.handle_left_type = 'ALIGNED'
            kp.handle_right_type = 'ALIGNED'
            ldt = max(1.0e-6, float(kp.co.x - kp.handle_left.x))
            rdt = max(1.0e-6, float(kp.handle_right.x - kp.co.x))
            kp.handle_left.y = float(kp.co.y) - (tangent[axis] / vldt) * ldt
            kp.handle_right.y = float(kp.co.y) + (tangent[axis] / vrdt) * rdt
            touched.append(fc)
        for fc in touched:
            fc.update()
        _mark_dirty()
        _build_path_cache(context, obj)

    def modal(self, context, event):
        obj = bpy.data.objects.get(getattr(self, 'obj_name', ''))
        if obj is None:
            return {'CANCELLED'}
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            if self._snapshot:
                _restore_snapshot_safe(obj, self.frame, self._snapshot)
                _build_path_cache(context, obj)
            if context.area is not None:
                context.area.header_text_set(None)
            return {'CANCELLED'}

        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        if event.type == 'MOUSEMOVE':
            if not self._drag_started and (mouse - self._start_mouse).length >= self._threshold:
                self._drag_started = True
            if self._drag_started:
                self._apply_manual_tangent(context, mouse)
                if context.area is not None:
                    context.area.header_text_set("Alt-glisser · Tangente manuelle - relâcher pour valider · Esc pour annuler")
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            if context.area is not None:
                context.area.header_text_set(None)
            if self._drag_started:
                _set_edit_selection(obj, self.frame, 'KEY')
                _tag_redraw_all_view3d()
                return {'FINISHED'}
            _toggle_corner_smooth(obj, self.frame)
            _set_edit_selection(obj, self.frame, 'KEY')
            _build_path_cache(context, obj)
            _tag_redraw_all_view3d()
            return {'FINISHED'}

        return {'RUNNING_MODAL'}


class AEMP_OT_clear_cache(Operator):
    bl_idname = "aemp.clear_cache"
    bl_label = "Effacer le cache"

    def execute(self, context):
        _clear_cache()
        return {'FINISHED'}



# -----------------------------------------------------------------------------
# Native direct-edit gizmos (V0.8)
# -----------------------------------------------------------------------------

class AEMP_GT_path_point(Gizmo):
    """Native Blender gizmo for one motion-path key or spatial handle.

    This replaces the always-running modal editor. Blender itself owns hover,
    click capture and gizmo lifetime, so ordinary object selection/navigation
    remains available and the N-panel is no longer coupled to a modal operator.
    """
    bl_idname = "AEMP_GT_path_point"

    def setup(self):
        self.obj_name = ""
        self.frame = 0.0
        self.part = 'KEY'  # KEY / LEFT / RIGHT
        self._snapshot = []
        self._multi_snapshots = {}
        self._start_mouse = None
        self._anchor_world = None
        self._mapping = None
        self._visual_dt = 1.0
        self._drag_started = False
        self._drag_threshold_px = 7.0
        self._pending_handle_convert = False
        self._constraint_mode = 'FREE'  # FREE, X, Y, Z, PLANE_X, PLANE_Y, PLANE_Z
        self._last_mouse = None
        self._alt_shape = False
        self.use_undo = True
        # Custom gizmos do not expose an RNA property tooltip.  Leaving the
        # tooltip enabled can make Blender query missing button/property data.
        self.use_tooltip = False
        self.use_select_background = True
        self.use_event_handle_all = True

    def _obj(self):
        return bpy.data.objects.get(self.obj_name)

    def _constraint_axes(self, context):
        """Return world-space X/Y/Z unit axes for the chosen constraint space."""
        obj = self._obj()
        settings = context.scene.aemp_settings
        if settings.constraint_space == 'LOCAL' and obj is not None:
            basis = obj.matrix_world.to_3x3().normalized()
            axes = [Vector(basis.col[i]).normalized() for i in range(3)]
        else:
            axes = [Vector((1.0, 0.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((0.0, 0.0, 1.0))]
        return axes

    def _apply_constraint(self, context, delta):
        mode = self._constraint_mode
        if mode == 'FREE':
            return delta
        axes = self._constraint_axes(context)
        index = {'X': 0, 'Y': 1, 'Z': 2, 'PLANE_X': 0, 'PLANE_Y': 1, 'PLANE_Z': 2}.get(mode)
        if index is None:
            return delta
        axis = axes[index]
        along = axis * delta.dot(axis)
        return (delta - along) if mode.startswith('PLANE_') else along

    def _constraint_label(self, context):
        space = 'Local' if context.scene.aemp_settings.constraint_space == 'LOCAL' else 'Global'
        mode = self._constraint_mode
        if mode == 'FREE':
            return f"Libre ({space})"
        if mode.startswith('PLANE_'):
            excluded = mode[-1]
            plane = {'X':'YZ', 'Y':'XZ', 'Z':'XY'}[excluded]
            return f"Plan {plane} ({space})"
        return f"Axe {mode} ({space})"

    def _update_header(self, context):
        if not self._drag_started:
            return
        part = 'Poignée' if self.part in {'LEFT', 'RIGHT'} else 'Clé'
        context.area.header_text_set(
            f"{part} · {self._constraint_label(context)}  |  X/Y/Z : axe  ·  Shift+X/Y/Z : plan  ·  même touche : libre"
        )

    def _draw_constraint_guide(self, context):
        if not self._drag_started or self._constraint_mode == 'FREE':
            return
        if not context.scene.aemp_settings.show_constraint_guide:
            return
        anchor = self._anchor_world
        if anchor is None:
            return
        axes = self._constraint_axes(context)
        mode = self._constraint_mode
        if mode.startswith('PLANE_'):
            excluded = {'X':0,'Y':1,'Z':2}[mode[-1]]
            indices = [i for i in range(3) if i != excluded]
        else:
            indices = [{'X':0,'Y':1,'Z':2}[mode]]
        colors = [(0.95,0.20,0.20,0.95), (0.25,0.85,0.30,0.95), (0.25,0.50,1.00,0.95)]
        rv3d = context.region_data
        length = max(1.0, float(getattr(rv3d, 'view_distance', 10.0)) * 1.5) if rv3d else 10.0
        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        gpu.state.line_width_set(2.0)
        shader.bind()
        for i in indices:
            axis = axes[i]
            a = anchor - axis * length
            b = anchor + axis * length
            shader.uniform_float('color', colors[i])
            batch_for_shader(shader, 'LINES', {'pos': [a, b]}).draw(shader)
        gpu.state.line_width_set(1.0)

    def _world_pos(self, context):
        obj = self._obj()
        if obj is None:
            return None
        data = _get_cache(context, obj, build_if_missing=True)
        if not data:
            return None
        rec = data.get("handles", {}).get(float(self.frame))
        if rec is None:
            # Float keys may differ by tiny rounding.
            for k, cand in data.get("handles", {}).items():
                if abs(float(k) - float(self.frame)) <= 0.001:
                    rec = cand
                    break
        if rec is None:
            return None
        if self.part == 'KEY':
            return rec["key"].copy()
        return rec[self.part.lower()].copy()

    def draw(self, context):
        pos = self._world_pos(context)
        if pos is None:
            return
        settings = context.scene.aemp_settings
        size = settings.key_size if self.part == 'KEY' else settings.handle_size
        selected = _is_multi_selected(self.obj_name, self.frame)
        active_selected = (_EDIT_SELECTION["object_name"] == self.obj_name and
                    _EDIT_SELECTION["frame"] is not None and
                    abs(float(_EDIT_SELECTION["frame"]) - float(self.frame)) <= 0.001)
        if self.part != 'KEY' and not active_selected:
            return

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.depth_test_set('NONE')
        extra = 4.0 if selected and _EDIT_SELECTION["part"] == self.part else 0.0
        if self.is_highlight:
            color = (1.0, 1.0, 1.0, 1.0)
        elif self.part == 'KEY':
            if selected:
                color = tuple(settings.selected_key_color)
            elif _spatial_key_mode(self._obj(), self.frame) == 'VECTOR':
                color = tuple(settings.corner_key_color)
            else:
                color = tuple(settings.key_color)
        else:
            color = tuple(settings.handle_color)
        if self.part == 'KEY' and settings.key_outline:
            _draw_screen_disc(context, shader, pos, size + settings.key_outline_size * 2.0 + extra, (0.02, 0.02, 0.02, 0.90))
        _draw_screen_disc(context, shader, pos, size + extra, color)
        self._draw_constraint_guide(context)
        gpu.state.blend_set('NONE')

    def test_select(self, context, location):
        settings = context.scene.aemp_settings
        if not settings.show_path or not settings.direct_edit:
            return -1
        pos = self._world_pos(context)
        if pos is None:
            return -1
        active_selected = (_EDIT_SELECTION["object_name"] == self.obj_name and
                    _EDIT_SELECTION["frame"] is not None and
                    abs(float(_EDIT_SELECTION["frame"]) - float(self.frame)) <= 0.001)
        if self.part != 'KEY' and (not settings.show_handles or not active_selected):
            return -1
        p2d = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, pos)
        if p2d is None:
            return -1
        d = (Vector(location) - p2d).length
        radius = float(settings.pick_radius)
        if self.part != 'KEY':
            # The key itself always wins in its visual core. This removes the
            # "lottery" where a short handle steals a click intended for the key.
            data = _get_cache(context, self._obj(), build_if_missing=True)
            rec = data.get("handles", {}).get(float(self.frame)) if data else None
            if rec is not None:
                key2d = view3d_utils.location_3d_to_region_2d(context.region, context.region_data, rec["key"])
                if key2d is not None:
                    key_core = max(7.0, float(settings.key_size) * 0.85)
                    if (Vector(location) - key2d).length <= key_core:
                        return -1
            radius = max(radius, float(settings.handle_size) + 6.0)
        return 0 if d <= radius else -1

    def invoke(self, context, event):
        obj = self._obj()
        if obj is None:
            return {'CANCELLED'}
        pos = self._world_pos(context)
        if pos is None:
            return {'CANCELLED'}

        # Double-click stays immediate. Alt is deferred so Alt-click toggles
        # Corner/Smooth while Alt-drag shapes the tangent manually.
        if self.part == 'KEY' and event.value == 'DOUBLE_CLICK':
            _toggle_corner_smooth(obj, self.frame)
            _set_edit_selection(obj, self.frame, 'KEY')
            _build_path_cache(context, obj)
            _tag_redraw_all_view3d()
            return {'FINISHED'}
        self._alt_shape = bool(self.part == 'KEY' and event.alt)

        # Shift-click is additive/toggle selection. Normal click isolates.
        if self.part == 'KEY' and event.shift:
            _set_edit_selection(obj, self.frame, 'KEY', extend=True, toggle=True)
        else:
            _set_edit_selection(obj, self.frame, self.part)

        self._snapshot = _snapshot_key_safe(obj, self.frame)
        if not self._snapshot:
            return {'CANCELLED'}
        self._multi_snapshots = {}
        if self.part == 'KEY':
            frames = _selected_frames_for_object(obj) or [float(self.frame)]
            for f in frames:
                snap = _snapshot_key_safe(obj, f)
                if snap:
                    self._multi_snapshots[float(f)] = snap
        self._start_mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._anchor_world = pos.copy()
        data = _get_cache(context, obj, build_if_missing=True)
        self._mapping = data["mapping"] if data else _world_mapping(obj)

        if self.part in {'LEFT', 'RIGHT'}:
            rec = data.get("handles", {}).get(float(self.frame)) if data else None
            if rec:
                self._visual_dt = max(1.0e-6, float(rec["left_visual_dt"] if self.part == 'LEFT' else rec["right_visual_dt"]))
            # Do NOT change handle type on click. Conversion to a manual handle
            # happens only after the pointer crosses the drag threshold.
            self._pending_handle_convert = any(
                ((_safe_key_for_axis(obj, item["axis"], self.frame)[1] is not None) and
                 ((getattr(_safe_key_for_axis(obj, item["axis"], self.frame)[1],
                           'handle_left_type' if self.part == 'LEFT' else 'handle_right_type')) in {'AUTO','AUTO_CLAMPED','VECTOR'}))
                for item in self._snapshot
            )
        self._drag_started = False
        self._constraint_mode = 'FREE'
        self._last_mouse = self._start_mouse.copy()
        _tag_redraw_all_view3d()
        return {'RUNNING_MODAL'}

    def modal(self, context, event, tweak):
        obj = self._obj()
        if obj is None or self._start_mouse is None or self._anchor_world is None:
            return {'CANCELLED'}

        mouse = Vector((event.mouse_region_x, event.mouse_region_y))
        self._last_mouse = mouse.copy()

        # Blender-style spatial constraints while dragging. Repeating the same
        # axis/plane key returns to free movement. Shift+axis constrains to the
        # complementary plane (Shift+X -> YZ, etc.).
        if self._drag_started and event.value == 'PRESS' and event.type in {'X', 'Y', 'Z'}:
            requested = f"PLANE_{event.type}" if event.shift else event.type
            self._constraint_mode = 'FREE' if self._constraint_mode == requested else requested
            self._update_header(context)
            _tag_redraw_all_view3d()
            return {'RUNNING_MODAL'}

        # A click is selection only. Motion editing starts only after a real
        # pointer drag, preventing tiny hand jitter from moving a key or handle.
        pixel_delta = (mouse - self._start_mouse).length
        if not self._drag_started:
            if pixel_delta < self._drag_threshold_px:
                return {'RUNNING_MODAL'}
            self._drag_started = True
            if self.part == 'KEY' and self._alt_shape:
                for item in self._snapshot:
                    fc, kp = _safe_key_for_axis(obj, item["axis"], self.frame)
                    if kp is None:
                        continue
                    kp.handle_left_type = 'ALIGNED'
                    kp.handle_right_type = 'ALIGNED'
                    if fc is not None:
                        fc.update()
            if self.part in {'LEFT', 'RIGHT'} and self._pending_handle_convert:
                for item in self._snapshot:
                    fc, kp = _safe_key_for_axis(obj, item["axis"], self.frame)
                    if kp is None:
                        continue
                    side_type = kp.handle_left_type if self.part == 'LEFT' else kp.handle_right_type
                    if side_type in {'AUTO', 'AUTO_CLAMPED', 'VECTOR'}:
                        kp.handle_left_type = 'ALIGNED'
                        kp.handle_right_type = 'ALIGNED'
                        if fc is not None:
                            fc.update()
                self._pending_handle_convert = False
            self._update_header(context)

        if context.region is None or context.region_data is None:
            return {'RUNNING_MODAL'}
        current = view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, mouse, self._anchor_world)
        origin = view3d_utils.region_2d_to_location_3d(
            context.region, context.region_data, self._start_mouse, self._anchor_world)
        world_delta = self._apply_constraint(context, current - origin)

        touched = []
        if self.part == 'KEY':
            if self._alt_shape:
                desired_world = self._anchor_world + world_delta
                desired_local = _world_to_local(desired_world, self._mapping)
                key_local = _eval_location_base(obj, _location_fcurves(obj), float(self.frame))
                tangent = desired_local - key_local
                data = _get_cache(context, obj, build_if_missing=True)
                rec = data.get("handles", {}).get(float(self.frame)) if data else None
                vldt = max(1.0e-6, float(rec.get("left_visual_dt", 1.0))) if rec else 1.0
                vrdt = max(1.0e-6, float(rec.get("right_visual_dt", 1.0))) if rec else 1.0
                for item in self._snapshot:
                    fc, kp = _safe_key_for_axis(obj, item["axis"], self.frame)
                    if fc is None or kp is None:
                        continue
                    axis = item["axis"]
                    ldt = max(1.0e-6, float(kp.co.x - kp.handle_left.x))
                    rdt = max(1.0e-6, float(kp.handle_right.x - kp.co.x))
                    kp.handle_left.y = float(kp.co.y) - (tangent[axis] / vldt) * ldt
                    kp.handle_right.y = float(kp.co.y) + (tangent[axis] / vrdt) * rdt
                    touched.append(fc)
            else:
                local_delta = self._mapping[0].inverted_safe() @ world_delta
                if 'SNAP' in tweak and context.scene.aemp_settings.snap_increment > 0.0:
                    inc = context.scene.aemp_settings.snap_increment
                    local_delta = Vector(tuple(round(v / inc) * inc for v in local_delta))
                snapshots = self._multi_snapshots or {float(self.frame): self._snapshot}
                for frame, snapshot in snapshots.items():
                    for item in snapshot:
                        fc, kp = _safe_key_for_axis(obj, item["axis"], frame)
                        if fc is None or kp is None:
                            continue
                        axis = item["axis"]
                        delta = local_delta[axis]
                        kp.co.y = item["co"][1] + delta
                        kp.handle_left.y = item["left"][1] + delta
                        kp.handle_right.y = item["right"][1] + delta
                        touched.append(fc)
        else:
            desired_world = self._anchor_world + world_delta
            desired_local = _world_to_local(desired_world, self._mapping)
            key_local = _eval_location_base(obj, _location_fcurves(obj), float(self.frame))
            if self.part == 'LEFT':
                desired_slope = (key_local - desired_local) / self._visual_dt
            else:
                desired_slope = (desired_local - key_local) / self._visual_dt
            for item in self._snapshot:
                fc, kp = _safe_key_for_axis(obj, item["axis"], self.frame)
                if fc is None or kp is None:
                    continue
                axis = item["axis"]
                if self.part == 'LEFT':
                    dt = max(1.0e-6, float(kp.co.x - kp.handle_left.x))
                    kp.handle_left.y = float(kp.co.y) - desired_slope[axis] * dt
                else:
                    dt = max(1.0e-6, float(kp.handle_right.x - kp.co.x))
                    kp.handle_right.y = float(kp.co.y) + desired_slope[axis] * dt
                touched.append(fc)

        for fc in touched:
            fc.update()
        _mark_dirty()
        _build_path_cache(context, obj)
        return {'RUNNING_MODAL'}

    def exit(self, context, cancel):
        obj = self._obj()
        if cancel and obj is not None:
            if self.part == 'KEY' and self._multi_snapshots:
                for frame, snapshot in self._multi_snapshots.items():
                    _restore_snapshot_safe(obj, frame, snapshot)
            elif self._snapshot:
                _restore_snapshot_safe(obj, self.frame, self._snapshot)
        if obj is not None:
            if (not cancel) and self.part == 'KEY' and self._alt_shape and not self._drag_started:
                _toggle_corner_smooth(obj, self.frame)
                _set_edit_selection(obj, self.frame, 'KEY')
            _mark_dirty()
            _build_path_cache(context, obj)
        self._snapshot = []
        self._multi_snapshots = {}
        self._start_mouse = None
        self._anchor_world = None
        self._drag_started = False
        self._pending_handle_convert = False
        self._constraint_mode = 'FREE'
        self._last_mouse = None
        self._alt_shape = False
        if context.area is not None:
            context.area.header_text_set(None)
        _tag_redraw_all_view3d()


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
        obj = context.active_object
        return bool(settings and settings.show_path and settings.direct_edit and obj and _has_location_animation(obj))

    def setup(self, context):
        self._signature = None
        self._obj_name = ""
        self._rebuild(context)

    def _has_modal_gizmo(self):
        # Never destroy/recreate a gizmo while Blender's gizmo_tweak operator
        # is using it.  Doing so invalidates Blender's active gizmo pointer and
        # can crash in gizmo_tweak_modal.
        try:
            return any(gizmo.is_modal for gizmo in self.gizmos)
        except (ReferenceError, RuntimeError):
            return False

    def _structure_signature(self, context):
        obj = context.active_object
        if obj is None or not _has_location_animation(obj):
            return "", ()
        return obj.name, tuple(float(f) for f in _location_keyframes(obj))

    def _rebuild(self, context):
        if self._has_modal_gizmo():
            return
        self.gizmos.clear()
        obj = context.active_object
        if obj is None or not _has_location_animation(obj):
            self._signature = ()
            self._obj_name = ""
            return
        data = _get_cache(context, obj, build_if_missing=True)
        if not data:
            self._signature = ()
            self._obj_name = obj.name
            return
        self._obj_name = obj.name
        frames = tuple(float(f) for f, _ in data.get("keys", []))
        self._signature = frames
        for frame in frames:
            for part in ('KEY', 'LEFT', 'RIGHT'):
                gz = self.gizmos.new(AEMP_GT_path_point.bl_idname)
                gz.obj_name = obj.name
                gz.frame = frame
                gz.part = part

    def _sync_structure(self, context):
        obj_name, frames = self._structure_signature(context)
        if obj_name == self._obj_name and frames == self._signature:
            return
        if self._has_modal_gizmo():
            return
        self._rebuild(context)

    def refresh(self, context):
        # refresh() may be called for every depsgraph/RNA update, including each
        # mouse move while a gizmo is being dragged.  Only rebuild if the actual
        # set of keys changed.  Position changes are read dynamically by draw().
        self._sync_structure(context)

    def draw_prepare(self, context):
        self._sync_structure(context)

# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------

class AEMP_Settings(PropertyGroup):
    show_path: BoolProperty(name="Afficher la trajectoire", default=True, update=lambda s,c: _mark_dirty())
    direct_edit: BoolProperty(name="Édition directe", default=True, description="Clés de trajectoire directement interactives", update=lambda s,c: _tag_redraw_all_view3d())
    display_mode: EnumProperty(
        name="Trajectoires",
        items=[
            ('ACTIVE',"Objet actif","Afficher uniquement la trajectoire de l'objet actif"),
            ('SELECTED',"Objets sélectionnés","Afficher les trajectoires de tous les objets sélectionnés"),
        ],
        default='ACTIVE',
        update=lambda s,c:_mark_dirty(),
    )
    show_samples: BoolProperty(name="Points intermédiaires", default=False, update=lambda s,c:_tag_redraw_all_view3d())
    show_handles: BoolProperty(name="Poignées Bézier", default=True, update=lambda s,c:_tag_redraw_all_view3d())
    show_direction: BoolProperty(name="Sens de l'animation", default=True, update=lambda s,c:_tag_redraw_all_view3d())
    show_time_split: BoolProperty(name="Distinguer passé / futur", default=True, update=lambda s,c:_tag_redraw_all_view3d())
    show_frame_labels: BoolProperty(name="Numéros de frame", default=False, update=lambda s,c:_tag_redraw_all_view3d())
    show_key_type_badges: BoolProperty(name="Badge type de clé", default=True, description="V=Vector, S=Alignée, A=Auto, F=Libre", update=lambda s,c:_tag_redraw_all_view3d())
    xray: BoolProperty(name="X-Ray", default=False, description="Afficher la trajectoire à travers la géométrie", update=lambda s,c:_tag_redraw_all_view3d())
    path_color: FloatVectorProperty(name="Trajectoire future", subtype='COLOR', size=4, min=0,max=1, default=(0.35,0.75,1.0,0.95), update=lambda s,c:_tag_redraw_all_view3d())
    past_color: FloatVectorProperty(name="Trajectoire passée", subtype='COLOR', size=4, min=0,max=1, default=(0.20,0.38,0.55,0.55), update=lambda s,c:_tag_redraw_all_view3d())
    key_color: FloatVectorProperty(name="Clé lissée", subtype='COLOR', size=4, min=0,max=1, default=(1.0,0.58,0.10,1.0), update=lambda s,c:_tag_redraw_all_view3d())
    corner_key_color: FloatVectorProperty(name="Clé angle", subtype='COLOR', size=4, min=0,max=1, default=(1.0,0.25,0.08,1.0), update=lambda s,c:_tag_redraw_all_view3d())
    selected_key_color: FloatVectorProperty(name="Clé sélectionnée", subtype='COLOR', size=4, min=0,max=1, default=(1.0,0.86,0.22,1.0), update=lambda s,c:_tag_redraw_all_view3d())
    handle_color: FloatVectorProperty(name="Poignées", subtype='COLOR', size=4, min=0,max=1, default=(0.95,0.95,0.95,1.0), update=lambda s,c:_tag_redraw_all_view3d())
    handle_line_color: FloatVectorProperty(name="Lignes poignées", subtype='COLOR', size=4, min=0,max=1, default=(0.8,0.8,0.8,0.7), update=lambda s,c:_tag_redraw_all_view3d())
    label_color: FloatVectorProperty(name="Labels", subtype='COLOR', size=4, min=0,max=1, default=(0.92,0.92,0.92,0.9), update=lambda s,c:_tag_redraw_all_view3d())
    arrow_spacing: IntProperty(name="Espacement flèches", default=8, min=2,max=100, update=lambda s,c:_tag_redraw_all_view3d())
    arrow_size: FloatProperty(name="Taille flèches", default=7.0, min=3,max=24, subtype='PIXEL', update=lambda s,c:_tag_redraw_all_view3d())
    range_mode: EnumProperty(name="Plage", items=[('KEYS',"Entre les clés","Première à dernière clé"),('WINDOW',"Autour de la frame","Fenêtre avant/après la frame courante"),('SCENE',"Scène","Start/End de la scène")], default='KEYS', update=lambda s,c:_mark_dirty())
    frames_before: IntProperty(name="Avant", default=24, min=0,max=10000, update=lambda s,c:_mark_dirty())
    frames_after: IntProperty(name="Après", default=24, min=0,max=10000, update=lambda s,c:_mark_dirty())
    sample_step: IntProperty(name="Pas minimum", default=1, min=1,max=50, update=lambda s,c:_mark_dirty())
    adaptive_sampling: BoolProperty(name="Échantillonnage adaptatif", default=True, update=lambda s,c:_mark_dirty())
    max_samples: IntProperty(name="Max échantillons", default=500, min=32,max=10000, update=lambda s,c:_mark_dirty())
    line_width: FloatProperty(name="Épaisseur", default=2.0, min=1,max=8, update=lambda s,c:_tag_redraw_all_view3d())
    sample_size: FloatProperty(name="Taille points", default=3.0, min=1,max=12, update=lambda s,c:_tag_redraw_all_view3d())
    key_size: FloatProperty(name="Taille clés", default=9.0, min=3,max=24, update=lambda s,c:_tag_redraw_all_view3d())
    handle_size: FloatProperty(name="Taille poignées", default=10.0, min=3,max=24, update=lambda s,c:_tag_redraw_all_view3d())
    pick_radius: FloatProperty(name="Tolérance clic", default=20.0, min=4,max=40, subtype='PIXEL')
    label_size: IntProperty(name="Taille labels", default=12, min=8,max=30, update=lambda s,c:_tag_redraw_all_view3d())
    snap_increment: FloatProperty(name="Pas de snap", default=0.1, min=0.001,max=100.0, precision=3)
    constraint_space: EnumProperty(
        name="Espace des contraintes",
        items=[('GLOBAL',"Global","X/Y/Z du monde"),('LOCAL',"Local","Axes locaux de l'objet animé")],
        default='GLOBAL',
    )
    show_constraint_guide: BoolProperty(name="Guide d'axe pendant le drag", default=True)
    show_advanced: BoolProperty(name="Réglages avancés", default=False)
    key_outline: BoolProperty(name="Contour des clés", default=True, description="Améliore la lisibilité sur écrans Retina/HiDPI", update=lambda s,c:_tag_redraw_all_view3d())
    key_outline_size: FloatProperty(name="Épaisseur contour", default=2.0, min=0.5, max=6.0, subtype='PIXEL', update=lambda s,c:_tag_redraw_all_view3d())
    show_selected_section: BoolProperty(name="Sélection", default=False)
    show_display_section: BoolProperty(name="Affichage", default=True)
    show_appearance_section: BoolProperty(name="Apparence", default=True)
    show_range_section: BoolProperty(name="Plage", default=False)
    show_help_section: BoolProperty(name="Aide", default=False)


class VIEW3D_PT_editable_motion_path(Panel):
    bl_label = "Editable Motion Paths"
    bl_idname = "VIEW3D_PT_editable_motion_path"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Path"

    @staticmethod
    def _accordion(layout, settings, prop_name, label, icon='NONE', enabled=True):
        row = layout.row(align=True)
        row.enabled = enabled
        opened = bool(getattr(settings, prop_name))
        row.prop(settings, prop_name, text="", icon='TRIA_DOWN' if opened else 'TRIA_RIGHT', emboss=False)
        row.label(text=label, icon=icon)
        return opened

    def draw(self, context):
        layout = self.layout
        s = context.scene.aemp_settings
        obj = context.active_object
        has_selection = bool(obj and _EDIT_SELECTION["object_name"] == obj.name and _EDIT_SELECTION["frame"] is not None)

        row = layout.row(align=True)
        row.prop(s, "show_path", text="Trajectoire")
        row.prop(s, "direct_edit", text="Éditable")
        layout.prop(s, "display_mode", text="Trajectoires")

        opened = self._accordion(layout, s, "show_selected_section", "Édition de la sélection", 'RESTRICT_SELECT_OFF', True)
        if opened:
            box = layout.box()
            box.enabled = has_selection
            if not has_selection:
                box.label(text="Sélectionne une clé ou une poignée", icon='INFO')
            else:
                frame = float(_EDIT_SELECTION["frame"])
                mode = _spatial_key_mode(obj, frame)
                box.label(text=f"Frame {frame:g} · {mode if mode and mode != 'NONE' else 'Clé'}")
                box.operator("aemp.toggle_selected_corner", text="Angle ↔ Courbe", icon='IPO_BEZIER')
                box.label(text="Alt + clic : bascule rapide")
                box.label(text="Alt + glisser : règle la tangente manuellement")
                if _EDIT_SELECTION["part"] in {'LEFT', 'RIGHT'}:
                    htype = _selection_handle_type(obj, frame, _EDIT_SELECTION["part"])
                    box.label(text=f"Poignée : {htype or '-'}")

        opened = self._accordion(layout, s, "show_display_section", "Affichage", 'HIDE_OFF')
        if opened:
            box = layout.box()
            box.prop(s, "show_direction")
            if s.show_direction:
                r=box.row(align=True); r.prop(s,"arrow_spacing"); r.prop(s,"arrow_size")
            box.prop(s, "show_time_split")
            box.prop(s, "show_frame_labels")
            box.prop(s, "show_key_type_badges")
            box.prop(s, "show_samples")
            box.prop(s, "show_handles")
            box.prop(s, "xray")

        opened = self._accordion(layout, s, "show_appearance_section", "Apparence", 'COLOR')
        if opened:
            box = layout.box()
            box.prop(s, "key_size", slider=True)
            box.prop(s, "handle_size", slider=True)
            box.label(text="Taille/couleurs rendues en pixels écran (PC + Mac)", icon='INFO')
            box.prop(s, "line_width", slider=True)
            box.prop(s, "path_color")
            if s.show_time_split:
                box.prop(s, "past_color")
            box.prop(s, "key_color")
            box.prop(s, "corner_key_color")
            box.prop(s, "selected_key_color")
            box.prop(s, "key_outline")
            if s.key_outline:
                box.prop(s, "key_outline_size", slider=True)

        opened = self._accordion(layout, s, "show_range_section", "Plage", 'PREVIEW_RANGE')
        if opened:
            box = layout.box()
            box.prop(s, "range_mode")
            if s.range_mode == 'WINDOW':
                r=box.row(align=True); r.prop(s,"frames_before"); r.prop(s,"frames_after")

        opened = self._accordion(layout, s, "show_advanced", "Réglages avancés", 'PREFERENCES')
        if opened:
            box = layout.box()
            box.prop(s,"sample_size")
            box.prop(s,"pick_radius")
            box.prop(s,"label_size")
            box.prop(s,"sample_step")
            box.prop(s,"adaptive_sampling")
            if s.adaptive_sampling: box.prop(s,"max_samples")
            box.prop(s,"snap_increment")
            box.prop(s,"constraint_space")
            box.prop(s,"show_constraint_guide")
            box.prop(s,"handle_color")
            box.prop(s,"handle_line_color")
            box.prop(s,"label_color")

        if obj is None:
            layout.label(text="Aucun objet sélectionné", icon='INFO')
        elif not _has_location_animation(obj):
            layout.label(text="Aucune animation Location", icon='INFO')

        opened = self._accordion(layout, s, "show_help_section", "Aide / Gestes", 'QUESTION')
        if opened:
            box = layout.box()
            box.label(text="Clic : sélectionner sans déplacer")
            box.label(text="Glisser une clé : déplacer")
            box.label(text="Glisser une poignée : régler la courbe")
            box.label(text="Alt + clic : angle ↔ courbe")
            box.label(text="Alt + glisser sur une clé : régler l'arrondi")
            box.label(text="Shift + clic : multi-sélection")
            box.label(text="X / Y / Z : contraindre à un axe")
            box.label(text="Shift + X/Y/Z : plan opposé")
            box.label(text="Ctrl pendant glisser : snap")


# -----------------------------------------------------------------------------
# Registration
# -----------------------------------------------------------------------------

CLASSES = (
    AEMP_Settings,
    AEMP_OT_toggle_path,
    AEMP_OT_refresh_path,
    AEMP_OT_insert_current_location_key,
    AEMP_OT_add_key_on_path,
    AEMP_OT_set_handle_type,
    AEMP_MT_handle_type,
    AEMP_OT_toggle_selected_corner,
    AEMP_OT_modifier_click,
    AEMP_OT_clear_cache,
    AEMP_GT_path_point,
    AEMP_GGT_motion_path,
    VIEW3D_PT_editable_motion_path,
)


def _register_keymaps():
    # Modifier-clicks are scoped to the 3D View and PASS_THROUGH unless the
    # pointer is actually over a motion-path key, so Blender keeps its normal
    # Alt/Shift-click behaviour everywhere else.
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon if wm else None
    if kc is None:
        return
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    for mode, kwargs in (('ALT', {'alt': True}), ('SHIFT', {'shift': True})):
        kmi = km.keymap_items.new('aemp.modifier_click', 'LEFTMOUSE', 'PRESS', **kwargs)
        kmi.properties.mode = mode
        _ADDON_KEYMAPS.append((km, kmi))


def _unregister_keymaps():
    for km, kmi in _ADDON_KEYMAPS:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            continue
    _ADDON_KEYMAPS.clear()


def register():
    global _DRAW_HANDLE, _DRAW_HANDLE_2D
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.aemp_settings = PointerProperty(type=AEMP_Settings)
    _register_keymaps()

    for handler, fn in (
        (bpy.app.handlers.undo_post, _on_undo_redo),
        (bpy.app.handlers.redo_post, _on_undo_redo),
        (bpy.app.handlers.load_post, _on_load),
        (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
    ):
        if fn not in handler:
            handler.append(fn)

    if _DRAW_HANDLE is None:
        _DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(_draw_motion_path, (), 'WINDOW', 'POST_VIEW')
    if _DRAW_HANDLE_2D is None:
        _DRAW_HANDLE_2D = bpy.types.SpaceView3D.draw_handler_add(_draw_motion_path_2d, (), 'WINDOW', 'POST_PIXEL')
    if not bpy.app.timers.is_registered(_live_update_timer):
        bpy.app.timers.register(_live_update_timer, first_interval=_TIMER_INTERVAL, persistent=True)


def unregister():
    global _DRAW_HANDLE, _DRAW_HANDLE_2D
    _unregister_keymaps()
    for handler, fn in (
        (bpy.app.handlers.undo_post, _on_undo_redo),
        (bpy.app.handlers.redo_post, _on_undo_redo),
        (bpy.app.handlers.load_post, _on_load),
        (bpy.app.handlers.depsgraph_update_post, _on_depsgraph),
    ):
        if fn in handler:
            handler.remove(fn)
    if bpy.app.timers.is_registered(_live_update_timer):
        bpy.app.timers.unregister(_live_update_timer)
    _clear_cache()
    _set_edit_selection(None, None, 'NONE')
    _MULTI_SELECTION.clear()

    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE, 'WINDOW')
        except (ReferenceError, RuntimeError):
            pass
        _DRAW_HANDLE = None
    if _DRAW_HANDLE_2D is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_DRAW_HANDLE_2D, 'WINDOW')
        except (ReferenceError, RuntimeError):
            pass
        _DRAW_HANDLE_2D = None
    if hasattr(bpy.types.Scene, "aemp_settings"):
        del bpy.types.Scene.aemp_settings
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
