# blender_ops/export_map_ops.py
# Author: Luke Stilson / sharpen3d

import bpy
import os
from bpy.types import Operator, UIList


class EXPORTMAP_UL_map_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row(align=True)
        row.operator("exportmap.apply_map_settings", text="", icon='HIDE_OFF').index = index
        row.prop(item, "map_type", text="", icon='TEXTURE')
        row.prop(item, "map_name", text="")


class EXPORTMAP_OT_add_map(Operator):
    bl_idname = "exportmap.add_map"
    bl_label = "Add Map"

    def execute(self, context):
        item = context.scene.export_map_list.add()
        item.map_type = 'BASECOLOR'
        item.map_name = "BaseColor"
        context.scene.export_map_index = len(context.scene.export_map_list) - 1
        return {'FINISHED'}


class EXPORTMAP_OT_remove_map(Operator):
    bl_idname = "exportmap.remove_map"
    bl_label = "Remove Map"

    def execute(self, context):
        index = context.scene.export_map_index
        if index >= 0:
            context.scene.export_map_list.remove(index)
            context.scene.export_map_index = min(len(context.scene.export_map_list) - 1, index)
        return {'FINISHED'}


class EXPORTMAP_OT_apply_map_settings(Operator):
    bl_idname = "exportmap.apply_map_settings"
    bl_label = "Apply Settings for Selected Map"
    index: bpy.props.IntProperty()
    
    def execute(self, context):
        scene = context.scene
        index = self.index
        scene.export_map_index = index
        
        item = scene.export_map_list[index]

        # Set scene color management
        if item.color_space == 'SRGB':
            scene.view_settings.view_transform = 'Standard'
        elif item.map_type == 'NORMAL':
            scene.view_settings.view_transform = 'Raw'
        else:
            scene.view_settings.view_transform = 'Standard'

        # Set render output path
        filename = f"{scene.custom_object_name}{scene.delimiter}{item.map_name}.png"
        output_dir = bpy.path.abspath(scene.export_output_directory)
        scene.render.filepath = bpy.path.abspath(os.path.join(output_dir, filename))

        # Optional: Set bit depth
        if item.bit_depth == '8':
            scene.render.image_settings.color_depth = '8'
        elif item.bit_depth == '16':
            scene.render.image_settings.color_depth = '16'
        elif item.bit_depth == '32':
            scene.render.image_settings.color_depth = '32'
            
        # Set color mode from channel format
        if item.channel_format == 'R':
            scene.render.image_settings.color_mode = 'BW'
        elif item.channel_format == 'RGB':
            scene.render.image_settings.color_mode = 'RGB'
        elif item.channel_format == 'RGBA':
            scene.render.image_settings.color_mode = 'RGBA'


        # Optional: Force file format
        scene.render.image_settings.file_format = 'PNG'  # Replace with logic if needed
        
        
        # Normalize helper
        def normalize_name(name):
            return name.replace(" ", "").replace("_", "").lower()

        # Direct access to the DMMT_Master node group
        master_tree = bpy.data.node_groups.get('DMMT_Master')
        if not master_tree:
            self.report({'ERROR'}, "Node group 'DMMT_Master' not found in bpy.data.node_groups")
            return {'CANCELLED'}

        # Find DMMT_Switcher node inside the master group
        switcher_node = next(
            (n for n in master_tree.nodes if n.type == 'GROUP' and n.node_tree and n.node_tree.name == 'DMMT_Switcher'),
            None
        )
        if not switcher_node:
            self.report({'ERROR'}, "DMMT_Switcher node not found in DMMT_Master")
            return {'CANCELLED'}

        # Find group output node in DMMT_Master
        output_node = next((n for n in master_tree.nodes if n.type == 'GROUP_OUTPUT'), None)
        if not output_node:
            self.report({'ERROR'}, "Group Output not found in DMMT_Master")
            return {'CANCELLED'}

        # Remove existing link to 'Output' if any
        for link in list(master_tree.links):
            if link.to_node == output_node and link.to_socket.name == 'Output':
                master_tree.links.remove(link)

        # Find matching output socket in DMMT_Switcher based on normalized map_type
        target_name = normalize_name(item.map_type)
        target_socket = next(
            (s for s in switcher_node.outputs if normalize_name(s.name) == target_name),
            None
        )

        if not target_socket:
            self.report({'ERROR'}, f"No matching output for map type '{item.map_type}' in DMMT_Switcher")
            return {'CANCELLED'}

        # Create new link from switcher output to group output 'Output'
        master_tree.links.new(target_socket, output_node.inputs['Output'])

        self.report({'INFO'}, f"Switched shader output to: {item.map_type}")
        self.report({'INFO'}, f"Scene prepared for: {item.map_name}")

        return {'FINISHED'}


class EXPORTMAP_OT_apply_default_settings(Operator):
    bl_idname = "exportmap.apply_default_settings"
    bl_label = "Set to Default (RGBA/sRGB/8-bit + Principled)"

    def execute(self, context):
        scene = context.scene
        index = scene.export_map_index
        if not (0 <= index < len(scene.export_map_list)):
            self.report({'ERROR'}, "No map selected")
            return {'CANCELLED'}

        item = scene.export_map_list[index]

        # Set default values
        item.color_space = 'SRGB'
        item.channel_format = 'RGBA'
        item.bit_depth = '8'

        # Access DMMT_Master node group
        master_tree = bpy.data.node_groups.get('DMMT_Master')
        if not master_tree:
            self.report({'ERROR'}, "Node group 'DMMT_Master' not found")
            return {'CANCELLED'}

        # Locate the DMMT_Switcher node inside it
        switcher_node = next((n for n in master_tree.nodes if n.type == 'GROUP' and n.node_tree and n.node_tree.name == 'DMMT_Switcher'), None)
        if not switcher_node:
            self.report({'ERROR'}, "DMMT_Switcher node not found in DMMT_Master")
            return {'CANCELLED'}

        # Find the group output node
        output_node = next((n for n in master_tree.nodes if n.type == 'GROUP_OUTPUT'), None)
        if not output_node:
            self.report({'ERROR'}, "Group Output not found in DMMT_Master")
            return {'CANCELLED'}

        # Remove existing link to the shader output
        for link in list(master_tree.links):
            if link.to_node == output_node and link.to_socket.name == 'Output':
                master_tree.links.remove(link)

        # Connect the 'Principled' output from DMMT_Switcher
        target_socket = switcher_node.outputs.get('Principled')
        if not target_socket:
            self.report({'ERROR'}, "'Principled' output not found in DMMT_Switcher")
            return {'CANCELLED'}

        master_tree.links.new(target_socket, output_node.inputs['Output'])

        self.report({'INFO'}, "Defaults applied: RGBA / sRGB / 8-bit + Principled output")
        return {'FINISHED'}



class EXPORTMAP_OT_export_single(Operator):
    bl_idname = "exportmap.export_single"
    bl_label = "Export Single Map"

    index: bpy.props.IntProperty()

    def execute(self, context):
        scene = context.scene
        if 0 <= self.index < len(scene.export_map_list):
            item = scene.export_map_list[self.index]
            print(f"Exporting Map: {item.map_name} ({item.map_type})")
            # No-op: placeholder for external export trigger
        else:
            self.report({'ERROR'}, "Invalid map index")
            return {'CANCELLED'}
        return {'FINISHED'}


class EXPORTMAP_OT_load_preset(Operator):
    bl_idname = "exportmap.load_preset"
    bl_label = "Load Map Preset"

    preset: bpy.props.EnumProperty(
        name="Preset",
        items=[
            ('PBR_DEFAULT', "PBR Default", ""),
            ('BASECOLOR_ONLY', "Basecolor Only", ""),
        ]
    )

    def execute(self, context):
        scene = context.scene
        scene.export_map_list.clear()

        presets = {
            'PBR_DEFAULT': [
                ('BASECOLOR', 'RGB', 'SRGB', '8'),
                ('NORMAL', 'RGB', 'LINEAR', '16'),
                ('ROUGHNESS', 'R', 'LINEAR', '8'),
                ('METALLIC', 'R', 'LINEAR', '8'),
                ('AO', 'R', 'LINEAR', '8'),
                ('OPACITY', 'R', 'LINEAR', '8'),
            ],
            'BASECOLOR_ONLY': [
                ('BASECOLOR', 'RGB', 'SRGB', '8'),
            ]
        }

        for map_type, channel, space, depth in presets.get(self.preset, []):
            item = scene.export_map_list.add()
            item.map_type = map_type
            item.map_name = map_type.title()
            item.channel_format = channel
            item.color_space = space
            item.bit_depth = depth

        scene.export_map_index = 0
        return {'FINISHED'}


classes = (
    EXPORTMAP_UL_map_list,
    EXPORTMAP_OT_add_map,
    EXPORTMAP_OT_remove_map,
    EXPORTMAP_OT_apply_map_settings,
    EXPORTMAP_OT_apply_default_settings,
    EXPORTMAP_OT_export_single,
    EXPORTMAP_OT_load_preset,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
