# ui_panels/export_panel.py
# Author: Luke Stilson / sharpened

import bpy
from bpy.types import Panel


class EXPORTMAP_PT_export_panel(Panel):
    bl_label = "Scene Setup"
    bl_idname = "EXPORTMAP_PT_export_panel"
    bl_space_type = 'VIEW_3D' 
    bl_region_type = 'UI'  
    bl_category = 'Aether'      
    

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.export_settings

        layout.operator("exportmap.create_bake_scene", text="Create Aether Scene", icon='SCENE_DATA')
        layout.label(text="Target Mesh:")
        layout.prop(settings, "source_object")

        if settings.source_object and settings.source_object.type == 'MESH':
            layout.prop(settings, "uv_map")

        layout.prop(scene, "custom_object_name")
        #layout.prop(scene, "delimiter")


def register():
    bpy.utils.register_class(EXPORTMAP_PT_export_panel)


def unregister():
    bpy.utils.unregister_class(EXPORTMAP_PT_export_panel)
