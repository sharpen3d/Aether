# mapping_conversion.py
# Author: Luke Stilson / sharpen3d

import bpy


def find_or_create_node(tree, type_idname, label=None):
    """Find or create a node by type."""
    node = next((n for n in tree.nodes if n.type == type_idname), None)
    if node:
        return node
    node = tree.nodes.new(type=f"ShaderNode{type_idname}")
    if label:
        node.label = label
    return node


def clear_upstream_chain(tree, socket, visited=None):
    """Recursively deletes all upstream nodes and links into the given socket"""
    if visited is None:
        visited = set()

    for link in list(socket.links):
        from_socket = link.from_socket
        from_node = from_socket.node

        # Remove the link
        tree.links.remove(link)

        # Only delete the node if:
        # - It's not already visited (prevent infinite loops)
        # - It has no other outputs connected
        # - It's not a Group Output or Material Output node
        if from_node not in visited and from_node.type not in {'OUTPUT_MATERIAL', 'GROUP_OUTPUT'}:
            visited.add(from_node)

            # Recurse into inputs of the upstream node
            for input_sock in from_node.inputs:
                clear_upstream_chain(tree, input_sock, visited)

            # Check if the node has no more output links before removing
            if all(len(out.links) == 0 for out in from_node.outputs):
                tree.nodes.remove(from_node)



def setup_common_mapping_chain(tree, img_nodes, input_socket):
    """Creates Mapping + Scale value node, returns the mapping node"""
    mapping_node = tree.nodes.new(type="ShaderNodeMapping")
    mapping_node.vector_type = 'POINT'
    mapping_node.location = (min(n.location.x for n in img_nodes) - 150,
                             sum(n.location.y for n in img_nodes) / len(img_nodes))

    # Create Scale control
    scale_node = tree.nodes.new(type="ShaderNodeValue")
    scale_node.label = "Scale"
    scale_node.name = "Scale"
    scale_node.outputs[0].default_value = 1.0
    scale_node.location = (mapping_node.location.x - 200, mapping_node.location.y - 250)

    tree.links.new(scale_node.outputs[0], mapping_node.inputs['Scale'])

    return mapping_node


class NODE_OT_convert_to_box_projection(bpy.types.Operator):
    """Set image textures to Box projection using Geometry(Position)"""
    bl_idname = "node.convert_to_box_projection"
    bl_label = "Convert to Box Projection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        tree = context.space_data.edit_tree
        selected_nodes = context.selected_nodes
        blend_value = context.scene.aether_box_blend

        image_nodes = [n for n in selected_nodes if n.type == 'TEX_IMAGE']
        if not image_nodes:
            self.report({'WARNING'}, "No Image Texture nodes selected.")
            return {'CANCELLED'}

        mapping_node = setup_common_mapping_chain(tree, image_nodes, 'Vector')

        # Create or find Geometry node
        geometry_node = find_or_create_node(tree, 'NewGeometry')
        geometry_node.location = (mapping_node.location.x - 300, mapping_node.location.y)

        # Link Geometry(Position) → Mapping(Vector)
        tree.links.new(geometry_node.outputs['Position'], mapping_node.inputs['Vector'])

        for img_node in image_nodes:
            img_node.projection = 'BOX'
            img_node.projection_blend = blend_value
            clear_upstream_chain(tree, img_node.inputs['Vector'])

            tree.links.new(mapping_node.outputs['Vector'], img_node.inputs['Vector'])

        return {'FINISHED'}


class NODE_OT_convert_to_flat_projection(bpy.types.Operator):
    """Set image textures to Flat projection using Texture Coordinate (UV)"""
    bl_idname = "node.convert_to_flat_projection"
    bl_label = "Convert to Flat Projection"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        tree = context.space_data.edit_tree
        selected_nodes = context.selected_nodes

        image_nodes = [n for n in selected_nodes if n.type == 'TEX_IMAGE']
        if not image_nodes:
            self.report({'WARNING'}, "No Image Texture nodes selected.")
            return {'CANCELLED'}

        mapping_node = setup_common_mapping_chain(tree, image_nodes, 'Vector')

        # Create or find Texture Coordinate node
        texcoord_node = find_or_create_node(tree, 'TexCoord')
        texcoord_node.location = (mapping_node.location.x - 300, mapping_node.location.y)

        # Link TextureCoordinate(UV) → Mapping(Vector)
        tree.links.new(texcoord_node.outputs['UV'], mapping_node.inputs['Vector'])

        for img_node in image_nodes:
            img_node.projection = 'FLAT'
            clear_upstream_chain(tree, img_node.inputs['Vector'])
            tree.links.new(mapping_node.outputs['Vector'], img_node.inputs['Vector'])

        return {'FINISHED'}


class NODE_PT_projection_tools_panel(bpy.types.Panel):
    bl_label = "Projection Tools"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Aether'
    bl_context = "material"

    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == 'ShaderNodeTree'

    def draw(self, context):
        layout = self.layout
        layout.label(text="Box Projection:")
        layout.prop(context.scene, "aether_box_blend", slider=True)
        layout.operator("node.convert_to_box_projection", icon='CUBE')

        layout.separator()
        layout.label(text="Flat Projection:")
        layout.operator("node.convert_to_flat_projection", icon='IMAGE_DATA')


def register():
    bpy.utils.register_class(NODE_OT_convert_to_box_projection)
    bpy.utils.register_class(NODE_OT_convert_to_flat_projection)
    bpy.utils.register_class(NODE_PT_projection_tools_panel)
    bpy.types.Scene.aether_box_blend = bpy.props.FloatProperty(
        name="Blend",
        description="Blend factor for Box projection",
        min=0.0, max=1.0,
        default=0.2
    )


def unregister():
    bpy.utils.unregister_class(NODE_OT_convert_to_box_projection)
    bpy.utils.unregister_class(NODE_OT_convert_to_flat_projection)
    bpy.utils.unregister_class(NODE_PT_projection_tools_panel)
    del bpy.types.Scene.aether_box_blend


if __name__ == "__main__":
    register()
