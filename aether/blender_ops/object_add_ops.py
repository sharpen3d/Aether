# blender_ops/object_add_ops.py
# Author: Luke Stilson / sharpen3d

import bpy
from bpy.types import Operator, Menu
from ..utils import append_content

class AETHER_OT_add_seamless_layer(Operator):
    bl_idname = "aether.add_seamless_layer"
    bl_label = "Add Seamless Layer"
    bl_description = "Add a 1x1 base mesh with Aether setup"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh = bpy.data.meshes.new("aether_baselayer")
        obj = bpy.data.objects.new("aether_baselayer", mesh)
        context.collection.objects.link(obj)

        # Create quad geometry
        verts = [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)]
        faces = [(0, 1, 2, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj.location = (0, 0, 1)

        # Add UV map
        uv_layer = mesh.uv_layers.new(name="UVMap")
        uv_data = uv_layer.data
        uv_coords = [(0, 0), (1, 0), (1, 1), (0, 1)]
        for i, loop in enumerate(mesh.loops):
            uv_data[i].uv = uv_coords[loop.vertex_index]

        # Create material
        mat = bpy.data.materials.new("ae_seamlessMAT")
        mat.use_nodes = True
        mat.blend_method = 'BLEND'
        obj.data.materials.append(mat)

        # Ensure node groups
        append_content.ensure_node_group("aether_master")
        append_content.ensure_node_group("aether_seamless")
        append_content.ensure_node_group("aether_seamless_tile")

        # Build node tree
        ntree = mat.node_tree
        nodes = ntree.nodes
        links = ntree.links
        nodes.clear()

        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (600, 0)

        dmmt = nodes.new("ShaderNodeGroup")
        dmmt.node_tree = bpy.data.node_groups["aether_master"]
        dmmt.location = (0, 0)

        seamless = nodes.new("ShaderNodeGroup")
        seamless.node_tree = bpy.data.node_groups["aether_seamless"]
        seamless.location = (300, 0)

        # Wire: aether_master → aether_seamless → Output
        if "Output" in dmmt.outputs and "Surface" in seamless.inputs:
            links.new(dmmt.outputs["Output"], seamless.inputs["Surface"])
        if "Surface" in seamless.outputs and "Surface" in output.inputs:
            links.new(seamless.outputs["Surface"], output.inputs["Surface"])
        if "Displacement" in dmmt.outputs and "Displacement" in output.inputs:
            links.new(dmmt.outputs["Displacement"], output.inputs["Displacement"])

        # Add Geometry Nodes modifier
        modifier = obj.modifiers.new(name="Aether_Tile", type='NODES')
        modifier.node_group = bpy.data.node_groups["aether_seamless_tile"]


        bpy.ops.object.select_all(action='DESELECT')
        obj.select_set(True)
        context.view_layer.objects.active = obj
        
        bpy.context.object.modifiers["Aether_Tile"]["Socket_3"] = mat

        return {'FINISHED'}

# Placeholder operators
class AETHER_OT_add_uv_layer(Operator):
    bl_idname = "aether.add_uv_layer"
    bl_label = "Add UV Layer"
    def execute(self, context):
        self.report({'INFO'}, "UV Layer added (placeholder)")
        return {'FINISHED'}

class AETHER_OT_add_beveled_object(Operator):
    bl_idname = "aether.add_beveled_object"
    bl_label = "Add Beveled Object"
    def execute(self, context):
        self.report({'INFO'}, "Beveled Object added (placeholder)")
        return {'FINISHED'}

class AETHER_OT_add_image_decal(Operator):
    bl_idname = "aether.add_image_decal"
    bl_label = "Add Image Decal"
    def execute(self, context):
        self.report({'INFO'}, "Image Decal added (placeholder)")
        return {'FINISHED'}

# Custom Add menu
class VIEW3D_MT_aether_menu(Menu):
    bl_idname = "VIEW3D_MT_aether_menu"
    bl_label = "Aether"

    def draw(self, context):
        layout = self.layout
        layout.operator("aether.add_seamless_layer", icon='MESH_GRID')
        layout.operator("aether.add_uv_layer", icon='UV')
        layout.operator("aether.add_beveled_object", icon='MOD_BEVEL')
        layout.operator("aether.add_image_decal", icon='IMAGE_DATA')

def menu_func_add(self, context):
    self.layout.menu("VIEW3D_MT_aether_menu", icon='MOD_FLUIDSIM')


classes = (
    AETHER_OT_add_seamless_layer,
    AETHER_OT_add_uv_layer,
    AETHER_OT_add_beveled_object,
    AETHER_OT_add_image_decal,
    VIEW3D_MT_aether_menu,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.VIEW3D_MT_add.append(menu_func_add)

def unregister():
    bpy.types.VIEW3D_MT_add.remove(menu_func_add)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
