import bpy
import os
from ..utils import append_content

def create_triplanar_instance_from_template(image_node):
    image = image_node.image
    if not image:
        print("Selected node has no image.")
        return None

    base_name = os.path.splitext(image.name)[0]
    template_name = "triplanar"
    new_group_name = f"{base_name}_triplanar"

    append_content.ensure_node_group(template_name)
    # Find the template node group
    template = bpy.data.node_groups.get(template_name)
    if not template:
        print(f"Template node group '{template_name}' not found.")
        return None

    # Duplicate node group
    new_group = template.copy()
    new_group.name = new_group_name

    # Replace internal image nodes
    img_nodes = [n for n in new_group.nodes if n.type == 'TEX_IMAGE']
    if not img_nodes:
        print(f"No image nodes found in '{template_name}'.")
    for n in img_nodes:
        n.image = image

    return new_group


class NODE_OT_add_triplanar_from_template(bpy.types.Operator):
    bl_idname = "node.add_triplanar_from_template"
    bl_label = "Instance Triplanar Group"
    bl_description = "Duplicate triplanar template group, assign image, wire sourcemaps, delete old image node"

    def execute(self, context):
        tree = context.space_data.edit_tree
        selected = [n for n in tree.nodes if n.select and n.type == 'TEX_IMAGE']
        if not selected:
            self.report({'ERROR'}, "Select an Image Texture node.")
            return {'CANCELLED'}

        image_node = selected[0]
        image = image_node.image
        location = image_node.location.copy()

        # Find sourcemaps group
        source_group = next(
            (n for n in tree.nodes if n.type == 'GROUP' and "sourcemaps" in n.node_tree.name.lower()),
            None
        )
        if not source_group:
            self.report({'ERROR'}, "No group with 'sourcemaps' in the name found.")
            return {'CANCELLED'}

        new_group = create_triplanar_instance_from_template(image_node)
        if not new_group:
            self.report({'ERROR'}, "Failed to create triplanar group.")
            return {'CANCELLED'}

        # Add new group node at same position
        ng_node = tree.nodes.new("ShaderNodeGroup")
        ng_node.node_tree = new_group
        ng_node.label = new_group.name
        ng_node.location = location

        # Connect sourcemaps outputs
        for name in ['Position', 'Normal']:
            src_name = f"{name.lower()}_vector"
            if src_name in source_group.outputs and name in ng_node.inputs:
                tree.links.new(source_group.outputs[src_name], ng_node.inputs[name])

        # Remove original image node
        tree.nodes.remove(image_node)

        return {'FINISHED'}


class NODE_PT_triplanar_loader(bpy.types.Panel):
    bl_label = "Triplanar Loader"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Aether'
    bl_context = 'material'
    
    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == 'ShaderNodeTree'

    def draw(self, context):
        self.layout.operator("node.add_triplanar_from_template", icon="GROUP")


def register():
    bpy.utils.register_class(NODE_OT_add_triplanar_from_template)
    bpy.utils.register_class(NODE_PT_triplanar_loader)


def unregister():
    bpy.utils.unregister_class(NODE_OT_add_triplanar_from_template)
    bpy.utils.unregister_class(NODE_PT_triplanar_loader)


if __name__ == "__main__":
    register()
