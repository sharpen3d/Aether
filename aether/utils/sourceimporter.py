# Source Map Importer (Enhanced)
# Author: Luke Stilson / sharpen3d

import bpy
import os
import json

class SOURCEMAP_PT_importer(bpy.types.Panel):
    bl_label = "Import Source Maps"
    bl_idname = "SOURCEMAP_PT_importer"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Aether'
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == 'ShaderNodeTree'
    
    def draw(self, context):
        layout = self.layout
        layout.label(text="Detected Source Map Folders:")

        base_dir = os.path.dirname(bpy.data.filepath)
        for root, dirs, files in os.walk(base_dir):
            if os.path.basename(root) == "source_maps":
                if any(f.endswith(('.png', '.exr')) for f in files):
                    first_img = next((f for f in files if f.endswith(('.png', '.exr'))), None)
                    prefix = first_img.split('_')[0] if first_img else os.path.basename(os.path.dirname(root))
                    op = layout.operator("sourcemap.import_maps", text=prefix)
                    op.folder_path = root
                dirs.clear()  # prevent deep recursion


class SOURCEMAP_OT_import(bpy.types.Operator):
    bl_idname = "sourcemap.import_maps"
    bl_label = "Import Maps from Folder"
    bl_description = "Imports source maps into current material as a node group"

    folder_path: bpy.props.StringProperty(subtype='DIR_PATH')

    def execute(self, context):
        folder = bpy.path.abspath(self.folder_path)
        if not os.path.isdir(folder):
            self.report({'ERROR'}, "Invalid folder")
            return {'CANCELLED'}

        suffixes = {
            'normal': '_normal',
            'normal-obj': '_normal-obj',
            'ao': '_ao',
            'curvature': '_curvature',
            'position': '_position',
            'uv': '_uv'
        }

        images = {}
        for key, suffix in suffixes.items():
            for file in os.listdir(folder):
                if file.endswith(suffix + ".exr") or file.endswith(suffix + ".png"):
                    path = os.path.join(folder, file)
                    img = bpy.data.images.get(file)
                    if img:
                        img.reload()
                    else:
                        img = bpy.data.images.load(path)
                        img.colorspace_settings.name = 'Non-Color' if key != 'uv' else 'sRGB'
                    # Ensure half-float is disabled if available
                    if hasattr(img, 'use_half_precision'):
                        img.use_half_precision = False
                    images[key] = img
                    break

        if not images:
            self.report({'ERROR'}, "No valid maps found")
            return {'CANCELLED'}

        # Get base name for group
        first_img = next(iter(images.values()))
        base_name = first_img.name.split('_')[0]
        group_name = f"{base_name}_sourcemaps"

        # Reuse existing group if available
        if group_name in bpy.data.node_groups:
            group = bpy.data.node_groups[group_name]
            for node in group.nodes:
                if isinstance(node, bpy.types.ShaderNodeTexImage) and node.image:
                    node.image.reload()

        else:
            group = bpy.data.node_groups.new(group_name, 'ShaderNodeTree')
            group_out = group.nodes.new("NodeGroupOutput")
            group_out.location = (500, 0)

            interface = group.interface
            y = 0

            for key, img in images.items():
                if key == 'uv':
                    continue
                tex = group.nodes.new("ShaderNodeTexImage")
                tex.image = img
                tex.label = tex.name = key
                tex.location = (-400, y)
                y -= 300
                if not any(i.name == key and i.in_out == 'OUTPUT' for i in interface.items_tree):
                    interface.new_socket(socket_type='NodeSocketColor', name=key, in_out='OUTPUT')
                for i, item in enumerate(interface.items_tree):
                    if item.name == key:
                        group.links.new(tex.outputs['Color'], group_out.inputs[i])
                        break

            # position -> position_world
            if 'position' in images:
                for file in os.listdir(folder):
                    if file.endswith("_position_bounds.json"):
                        with open(os.path.join(folder, file), 'r') as f:
                            bounds = json.load(f)
                            min_vals = bounds.get("min", [0, 0, 0])
                            max_vals = bounds.get("max", [1, 1, 1])
                        break
                tex = group.nodes.get("position")
                if tex:
                    sep = group.nodes.new("ShaderNodeSeparateColor")
                    sep.location = (tex.location.x + 200, tex.location.y)
                    group.links.new(tex.outputs['Color'], sep.inputs['Color'])
                    combine = group.nodes.new("ShaderNodeCombineXYZ")
                    combine.location = (sep.location.x + 400, sep.location.y)
                    for i in range(3):
                        mapr = group.nodes.new("ShaderNodeMapRange")
                        mapr.inputs[1].default_value = 0
                        mapr.inputs[2].default_value = 1
                        mapr.inputs[3].default_value = min_vals[i]
                        mapr.inputs[4].default_value = max_vals[i]
                        mapr.location = (sep.location.x + 200, sep.location.y - i * 100)
                        group.links.new(sep.outputs[i], mapr.inputs[0])
                        group.links.new(mapr.outputs[0], combine.inputs[i])
                    if not any(i.name == "position_vector" for i in interface.items_tree):
                        interface.new_socket(socket_type='NodeSocketVector', name='position_vector', in_out='OUTPUT')
                    for i, item in enumerate(interface.items_tree):
                        if item.name == 'position_vector':
                            group.links.new(combine.outputs['Vector'], group_out.inputs[i])
                            break

            # normal -> normal_vector
            if 'normal-obj' in images:
                tex = group.nodes.get("normal-obj")
                if tex:
                    sep = group.nodes.new("ShaderNodeSeparateColor")
                    sep.location = (tex.location.x + 200, tex.location.y)
                    group.links.new(tex.outputs['Color'], sep.inputs['Color'])
                    combine = group.nodes.new("ShaderNodeCombineXYZ")
                    combine.location = (sep.location.x + 400, sep.location.y)
                    for i in range(3):
                        math = group.nodes.new("ShaderNodeMath")
                        math.operation = 'MULTIPLY_ADD'
                        math.inputs[1].default_value = 2.0
                        math.inputs[2].default_value = -1.0
                        math.location = (sep.location.x + 200, sep.location.y - i * 100)
                        group.links.new(sep.outputs[i], math.inputs[0])
                        group.links.new(math.outputs[0], combine.inputs[i])
                    if not any(i.name == "normal_vector" for i in interface.items_tree):
                        interface.new_socket(socket_type='NodeSocketVector', name='normal_vector', in_out='OUTPUT')
                    for i, item in enumerate(interface.items_tree):
                        if item.name == 'normal_vector':
                            group.links.new(combine.outputs['Vector'], group_out.inputs[i])
                            break

        # Link to material
        mat = context.object.active_material
        if not mat or not mat.use_nodes:
            self.report({'ERROR'}, "Active material with nodes required")
            return {'CANCELLED'}

        group_node = mat.node_tree.nodes.new("ShaderNodeGroup")
        group_node.node_tree = group
        group_node.location = (0, 0)

        return {'FINISHED'}


def register():
    bpy.utils.register_class(SOURCEMAP_PT_importer)
    bpy.utils.register_class(SOURCEMAP_OT_import)


def unregister():
    bpy.utils.unregister_class(SOURCEMAP_PT_importer)
    bpy.utils.unregister_class(SOURCEMAP_OT_import)


if __name__ == "__main__":
    register()