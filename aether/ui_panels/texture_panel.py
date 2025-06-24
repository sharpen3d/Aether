# ui_panels/texture_panel.py
# Author: Luke Stilson / sharpen3d

import bpy
from bpy.types import Panel


class MYTEXTURE_PT_panel(Panel):
    bl_label = "Texture Output"
    bl_idname = "MYTEXTURE_PT_panel"

    bl_space_type = 'VIEW_3D' 
    bl_region_type = 'UI'  
    bl_category = 'Aether'    

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.export_settings
        index = scene.export_map_index

        row = layout.row()
        row.template_list("EXPORTMAP_UL_map_list", "", scene, "export_map_list", scene, "export_map_index")

        col = row.column(align=True)
        col.operator("exportmap.add_map", icon='ADD', text="")
        col.operator("exportmap.remove_map", icon='REMOVE', text="")

        layout.row().operator("exportmap.apply_default_settings", icon='FILE_REFRESH')
        layout.operator_menu_enum("exportmap.load_preset", "preset", text="Choose Preset", icon='PRESET')
        layout.separator()

        layout.prop(scene, "export_output_directory")
        layout.operator("exportmap.render_all_maps", icon='RENDER_STILL')

        if 0 <= index < len(scene.export_map_list):
            item = scene.export_map_list[index]
            box = layout.box()
            box.prop(item, "color_space")
            box.prop(item, "channel_format")
            box.prop(item, "bit_depth")


def register():
    bpy.utils.register_class(MYTEXTURE_PT_panel)


def unregister():
    bpy.utils.unregister_class(MYTEXTURE_PT_panel)
