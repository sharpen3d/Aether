# blender_ops/render_ops.py
# Author: Luke Stilson / sharpen3d

import bpy
import os
from bpy.types import Operator
from ..core import material_builder
from ..utils.shader_links import link_switcher_output


class EXPORTMAP_OT_render_all_maps(Operator):
    bl_idname = "exportmap.render_all_maps"
    bl_label = "Render All Maps"

    def execute(self, context):
        scene = context.scene
        export_list = scene.export_map_list
        
        revert_index = bpy.context.scene.export_map_index

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

        for item in export_list:
            # Socket relink
            if not link_switcher_output(item.map_type):
                self.report({'WARNING'}, f"Skipped '{item.map_name}': No output socket")
                continue

            # Set view transform
            scene.view_settings.view_transform = 'Raw' if item.map_type == 'NORMAL' else 'Standard'
            scene.render.image_settings.color_depth = item.bit_depth
            scene.render.image_settings.color_mode = {
                'R': 'BW',
                'RGB': 'RGB',
                'RGBA': 'RGBA',
            }[item.channel_format]
            scene.render.image_settings.file_format = 'PNG'

            filename = f"{scene.custom_object_name}{scene.delimiter}{item.map_name}.png"
            scene.render.filepath = os.path.join(output_dir, filename)
            self.report({'INFO'}, f"Rendering: {filename}")
            bpy.ops.render.render(write_still=True)

        # Restore original settings
        scene.view_settings.view_transform = original_view_transform
        scene.render.image_settings.color_depth = original_color_depth
        scene.render.image_settings.color_mode = original_color_mode
        scene.render.image_settings.file_format = original_file_format
        scene.render.filepath = original_filepath
        
        bpy.ops.exportmap.apply_map_settings(index=revert_index)

        preview_obj = next((o for o in scene.objects if ".stx_preview" in o.name), None)
        mat = material_builder.apply_rendered_maps_to_material(scene)
        if mat and preview_obj:
            #preview_obj.active_material = mat
            preview_obj.modifiers["GeometryNodes"]["Socket_3"] = mat

        self.report({'INFO'}, "All maps rendered")
        return {'FINISHED'}


def register():
    bpy.utils.register_class(EXPORTMAP_OT_render_all_maps)


def unregister():
    bpy.utils.unregister_class(EXPORTMAP_OT_render_all_maps)
