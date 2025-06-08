# blender_ops/object_add_ops.py
# Author: Luke Stilson / sharpen3d

import bpy
from bpy.types import Operator, Menu

class AETHER_OT_add_seamless_layer(Operator):
    bl_idname = "aether.add_seamless_layer"
    bl_label = "Add Seamless Layer"
    bl_description = "Add a 1x1 base mesh with Aether setup"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        mesh = bpy.data.meshes.new("aether_baselayer")
        obj = bpy.data.objects.new("aether_baselayer", mesh)
        context.collection.objects.link(obj)

        verts = [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)]
        faces = [(0, 1, 2, 3)]
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        obj.location = (0.5, 0.5, 0)

        mat = bpy.data.materials.new("Aether_Material")
        mat.use_nodes = True
        obj.data.materials.append(mat)

        ntree = mat.node_tree
        nodes = ntree.nodes
        links = ntree.links
        nodes.clear()

        output = nodes.new("ShaderNodeOutputMaterial")
        output.location = (400, 0)

        group = bpy.data.node_groups.get("DMMT_Master")
        if not group:
            self.report({'WARNING'}, "Node group 'DMMT_Master' not found")
            return {'CANCELLED'}

        group_node = nodes.new("ShaderNodeGroup")
        group_node.node_tree = group
        group_node.location = (0, 0)

        if "Output" in group_node.outputs and "Surface" in output.inputs:
            links.new(group_node.outputs["Output"], output.inputs["Surface"])
        if "Displacement" in group_node.outputs and "Displacement" in output.inputs:
            links.new(group_node.outputs["Displacement"], output.inputs["Displacement"])

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

class AETHER_OT_add_geometry_mask(Operator):
    bl_idname = "aether.add_geometry_mask"
    bl_label = "Add Geometry Mask"
    def execute(self, context):
        self.report({'INFO'}, "Geometry Mask added (placeholder)")
        return {'FINISHED'}

class AETHER_OT_add_seamless_scatter(Operator):
    bl_idname = "aether.add_seamless_scatter"
    bl_label = "Add Seamless Scatter"
    def execute(self, context):
        self.report({'INFO'}, "Seamless Scatter added (placeholder)")
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
        layout.operator("aether.add_geometry_mask", icon='MOD_MASK')
        layout.operator("aether.add_seamless_scatter", icon='PARTICLES')
        layout.operator("aether.add_image_decal", icon='IMAGE_DATA')

def menu_func_add(self, context):
    self.layout.menu("VIEW3D_MT_aether_menu", icon='MOD_FLUIDSIM')


classes = (
    AETHER_OT_add_seamless_layer,
    AETHER_OT_add_uv_layer,
    AETHER_OT_add_beveled_object,
    AETHER_OT_add_geometry_mask,
    AETHER_OT_add_seamless_scatter,
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
