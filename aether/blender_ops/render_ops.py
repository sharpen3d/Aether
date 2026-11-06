# blender_ops/render_ops.py
# Author: Luke Stilson / sharpen3d

import os
import tempfile
import time

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator

from ..core import material_builder
from ..utils.shader_links import link_switcher_output

_AUTO_PREVIEW_RUNNING = False
_AUTO_PREVIEW_SERIAL = {}
_AUTO_PREVIEW_PENDING = set()
_LAST_AUTO_PREVIEW_TIME = {}


def _temp_render_path(scene, suffix):
    safe_scene = "".join(c if c.isalnum() or c in "_-" else "_" for c in scene.name)
    return os.path.join(tempfile.gettempdir(), f"aether_{safe_scene}_{suffix}.png")


def _redraw_all_3d_views():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


def _force_preview_refresh(scene):
    preview_obj = material_builder.get_preview_object(scene)
    if preview_obj is not None:
        try:
            preview_obj.update_tag(refresh={'DATA', 'OBJECT', 'TIME'})
        except TypeError:
            preview_obj.update_tag()
        if preview_obj.data is not None:
            try:
                preview_obj.data.update()
            except Exception:
                pass
            try:
                preview_obj.data.update_tag()
            except Exception:
                pass

    try:
        scene.view_layers[0].update()
    except Exception:
        pass

    _redraw_all_3d_views()
    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)


def _render_single_preview_image(scene, item, image_name, final_path):
    original_view_transform = scene.view_settings.view_transform
    original_color_depth = scene.render.image_settings.color_depth
    original_color_mode = scene.render.image_settings.color_mode
    original_file_format = scene.render.image_settings.file_format
    original_filepath = scene.render.filepath
    original_resolution_pct = scene.render.resolution_percentage
    original_use_compositing = scene.render.use_compositing
    original_use_sequencer = scene.render.use_sequencer

    try:
        scene.view_settings.view_transform = 'Raw' if item.map_type == 'NORMAL' else 'Standard'
        scene.render.image_settings.color_depth = item.bit_depth
        scene.render.image_settings.color_mode = {
            'R': 'BW',
            'RGB': 'RGB',
            'RGBA': 'RGBA',
        }[item.channel_format]
        scene.render.image_settings.file_format = 'PNG'
        scene.render.resolution_percentage = int(
            getattr(scene, "aether_preview_resolution_percentage", 50)
        )
        scene.render.use_compositing = False
        scene.render.use_sequencer = False
        scene.render.filepath = final_path
        os.makedirs(os.path.dirname(final_path), exist_ok=True)

        bpy.context.view_layer.update()
        bpy.ops.render.render(write_still=True, use_viewport=False)
        image = material_builder.load_or_reload_image(image_name, final_path)
        if image is None:
            return None

        image.colorspace_settings.name = 'Non-Color' if item.map_type == 'NORMAL' else 'sRGB'
        image.reload()
        image.update()
        return image
    except Exception:
        return None
    finally:
        scene.view_settings.view_transform = original_view_transform
        scene.render.image_settings.color_depth = original_color_depth
        scene.render.image_settings.color_mode = original_color_mode
        scene.render.image_settings.file_format = original_file_format
        scene.render.filepath = original_filepath
        scene.render.resolution_percentage = original_resolution_pct
        scene.render.use_compositing = original_use_compositing
        scene.render.use_sequencer = original_use_sequencer


def _get_context_window_for_scene(scene):
    for window in bpy.context.window_manager.windows:
        if getattr(window, "scene", None) == scene:
            return window
    return bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None


def _run_fast_preview(scene):
    global _AUTO_PREVIEW_RUNNING

    if _AUTO_PREVIEW_RUNNING:
        return False, "Preview already running"
    if material_builder.get_preview_object(scene) is None:
        return False, "No .stx_preview object found in the current scene"
    if not scene.export_map_list:
        return False, "No maps in export list"

    preview_mode = getattr(scene, "aether_preview_mode", "ACTIVE_MAP")
    _AUTO_PREVIEW_RUNNING = True
    try:
        if preview_mode == "ALL_MAPS":
            revert_index = scene.export_map_index
            for item in scene.export_map_list:
                if not link_switcher_output(item.map_type):
                    continue
                preview_name = material_builder.map_image_name(scene, item, preview=True)
                preview_path = material_builder.preview_cache_filepath(scene, item=item)
                image = _render_single_preview_image(scene, item, preview_name, preview_path)
                if image is None:
                    return False, f"Fast preview failed for {item.map_name}"

            if 0 <= revert_index < len(scene.export_map_list):
                bpy.ops.exportmap.apply_map_settings(index=revert_index)
                scene.aether_preview_mode = "ALL_MAPS"

            mat = material_builder.apply_rendered_maps_to_material(scene, use_preview_cache=True)
            if mat is None or not material_builder.assign_material_to_preview(scene, mat):
                return False, "Failed to assign full preview material"
            _force_preview_refresh(scene)
            return True, "Preview updated: all maps"

        index = scene.export_map_index
        if not (0 <= index < len(scene.export_map_list)):
            return False, "No active map selected"

        item = scene.export_map_list[index]
        if not link_switcher_output(item.map_type):
            return False, f"No output socket found for '{item.map_type}'"

        preview_name = material_builder.map_image_name(scene, item, preview=True)
        preview_path = material_builder.preview_cache_filepath(scene, item=item)
        image = _render_single_preview_image(scene, item, preview_name, preview_path)
        if image is None:
            return False, "Fast preview render did not produce an image"

        # Reuse the same file-backed preview cache approach as all-maps mode.
        # This avoids a separate one-off image path that had been turning up blank.
        mat = material_builder.build_gpu_preview_material(scene, image)
        if mat is None or not material_builder.assign_material_to_preview(scene, mat):
            return False, "Failed to assign preview material"
        _force_preview_refresh(scene)
        return True, f"Preview updated: {item.map_name}"
    finally:
        _AUTO_PREVIEW_RUNNING = False


def _queue_auto_preview(scene_name):
    token = _AUTO_PREVIEW_SERIAL.get(scene_name, 0) + 1
    _AUTO_PREVIEW_SERIAL[scene_name] = token

    def _timer_callback():
        scene = bpy.data.scenes.get(scene_name)
        if scene is None:
            return None
        if _AUTO_PREVIEW_SERIAL.get(scene_name) != token:
            return None
        if not getattr(scene, "aether_auto_preview_enabled", False):
            return None
        if _AUTO_PREVIEW_RUNNING:
            _AUTO_PREVIEW_PENDING.add(scene_name)
            return 0.35

        now = time.monotonic()
        min_interval = max(
            0.35,
            float(getattr(scene, "aether_auto_preview_delay", 0.75)) * 0.75,
        )
        last_time = _LAST_AUTO_PREVIEW_TIME.get(scene_name, 0.0)
        if now - last_time < min_interval:
            _AUTO_PREVIEW_PENDING.add(scene_name)
            return min_interval - (now - last_time)

        window = _get_context_window_for_scene(scene)
        if window is None:
            return 0.5

        with bpy.context.temp_override(window=window, scene=scene, view_layer=scene.view_layers[0]):
            _run_fast_preview(scene)
        _LAST_AUTO_PREVIEW_TIME[scene_name] = time.monotonic()
        if scene_name in _AUTO_PREVIEW_PENDING:
            _AUTO_PREVIEW_PENDING.discard(scene_name)
            _queue_auto_preview(scene_name)
        return None

    delay = float(getattr(bpy.data.scenes.get(scene_name), "aether_auto_preview_delay", 0.75))
    bpy.app.timers.register(_timer_callback, first_interval=delay)


@persistent
def _aether_auto_preview_handler(scene, depsgraph):
    if scene is None:
        return
    if not getattr(scene, "aether_auto_preview_enabled", False):
        return
    if _AUTO_PREVIEW_RUNNING:
        return

    changed_ids = {
        update.id.original if hasattr(update.id, "original") else update.id
        for update in depsgraph.updates
    }
    non_null_ids = [id_data for id_data in changed_ids if id_data is not None]
    if non_null_ids and all(isinstance(id_data, bpy.types.Image) for id_data in non_null_ids):
        return

    # Ignore high-frequency self churn from preview objects/images/materials.
    preview_obj = material_builder.get_preview_object(scene)
    ignored_names = {f"{scene.custom_object_name}.stx_gpu_preview", f"{scene.custom_object_name}.stxmat"}
    if preview_obj is not None:
        ignored_names.add(preview_obj.name)
        if preview_obj.data is not None:
            ignored_names.add(preview_obj.data.name)
    filtered_ids = []
    for id_data in non_null_ids:
        name = getattr(id_data, "name", "")
        if name in ignored_names:
            continue
        filtered_ids.append(id_data)
    if not filtered_ids and non_null_ids:
        return

    _queue_auto_preview(scene.name)


class EXPORTMAP_OT_render_all_maps(Operator):
    bl_idname = "exportmap.render_all_maps"
    bl_label = "Render All Maps"

    def execute(self, context):
        scene = context.scene
        export_list = scene.export_map_list
        revert_index = scene.export_map_index

        if not export_list:
            self.report({'WARNING'}, "No maps in export list")
            return {'CANCELLED'}

        original_view_transform = scene.view_settings.view_transform
        original_color_depth = scene.render.image_settings.color_depth
        original_color_mode = scene.render.image_settings.color_mode
        original_file_format = scene.render.image_settings.file_format
        original_filepath = scene.render.filepath

        output_dir = bpy.path.abspath(scene.export_output_directory)
        os.makedirs(output_dir, exist_ok=True)

        try:
            for item in export_list:
                if not link_switcher_output(item.map_type):
                    self.report({'WARNING'}, f"Skipped '{item.map_name}': No output socket")
                    continue

                scene.view_settings.view_transform = 'Raw' if item.map_type == 'NORMAL' else 'Standard'
                scene.render.image_settings.color_depth = item.bit_depth
                scene.render.image_settings.color_mode = {
                    'R': 'BW',
                    'RGB': 'RGB',
                    'RGBA': 'RGBA',
                }[item.channel_format]
                scene.render.image_settings.file_format = 'PNG'

                filename = material_builder.map_image_name(scene, item, preview=False)
                scene.render.filepath = os.path.join(output_dir, filename)
                self.report({'INFO'}, f"Rendering: {filename}")
                bpy.ops.render.render(write_still=True, use_viewport=False)
        finally:
            scene.view_settings.view_transform = original_view_transform
            scene.render.image_settings.color_depth = original_color_depth
            scene.render.image_settings.color_mode = original_color_mode
            scene.render.image_settings.file_format = original_file_format
            scene.render.filepath = original_filepath

        if 0 <= revert_index < len(export_list):
            bpy.ops.exportmap.apply_map_settings(index=revert_index)
            if getattr(scene, "aether_preview_mode", "ACTIVE_MAP") == "ALL_MAPS":
                scene.aether_preview_mode = "ALL_MAPS"

        mat = material_builder.apply_rendered_maps_to_material(scene, use_preview_cache=False)
        if mat:
            material_builder.assign_material_to_preview(scene, mat)

        self.report({'INFO'}, "All maps rendered")
        return {'FINISHED'}


class EXPORTMAP_OT_render_active_map_preview(Operator):
    bl_idname = "exportmap.render_active_map_preview"
    bl_label = "Render Fast Preview"
    bl_description = (
        "Fast EEVEE preview render. Active Map shows the selected AOV; All Maps "
        "renders every map into a preview cache and rebuilds the full preview material."
    )

    def execute(self, context):
        ok, message = _run_fast_preview(context.scene)
        if not ok:
            self.report({'ERROR'}, message)
            return {'CANCELLED'}
        self.report({'INFO'}, message)
        return {'FINISHED'}


def register():
    if _aether_auto_preview_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_aether_auto_preview_handler)
    bpy.utils.register_class(EXPORTMAP_OT_render_all_maps)
    bpy.utils.register_class(EXPORTMAP_OT_render_active_map_preview)


def unregister():
    if _aether_auto_preview_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_aether_auto_preview_handler)
    bpy.utils.unregister_class(EXPORTMAP_OT_render_active_map_preview)
    bpy.utils.unregister_class(EXPORTMAP_OT_render_all_maps)
