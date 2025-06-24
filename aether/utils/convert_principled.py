import bpy

def copy_input_value(source_socket, target_socket):
    if hasattr(source_socket, "default_value") and hasattr(target_socket, "default_value"):
        try:
            target_socket.default_value = source_socket.default_value
        except:
            pass

def transfer_socket(material, node_from, node_to, mapping):
    for source_name, target_name in mapping.items():
        from_sock = node_from.inputs.get(source_name)
        to_sock = node_to.inputs.get(target_name)
        if not from_sock or not to_sock:
            continue
        # Transfer links or value
        if from_sock.is_linked:
            material.node_tree.links.new(to_sock, from_sock.links[0].from_socket)
        else:
            copy_input_value(from_sock, to_sock)

def convert_to_dmmt(context):
    mat = context.object.active_material
    if not mat or not mat.use_nodes:
        return

    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    principled = next((n for n in nodes if n.type == 'BSDF_PRINCIPLED'), None)
    if not principled:
        return

    output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
    output_input = output.inputs['Surface'].links[0].from_socket if output and output.inputs['Surface'].is_linked else None

    # Add new group
    group_node = nodes.new('ShaderNodeGroup')
    group_node.node_tree = bpy.data.node_groups.get('aether_master')
    group_node.location = principled.location

    socket_map = {
        'Base Color': 'Base Color',
        'Roughness': 'Roughness',
        'Metallic': 'Metallic',
        'Alpha': 'Opacity',
        'Emission': 'Emission',
        'IOR': 'IOR',
        'Normal': 'Normal'
    }
    transfer_socket(mat, principled, group_node, socket_map)

    if output and output_input == principled.outputs['BSDF']:
        links.new(output.inputs['Surface'], group_node.outputs[0])

    nodes.remove(principled)

def convert_to_principled(context):
    mat = context.object.active_material
    if not mat or not mat.use_nodes:
        return

    tree = mat.node_tree
    nodes = tree.nodes
    links = tree.links

    dmmt = next((n for n in nodes if n.type == 'GROUP' and n.node_tree.name == 'aether_master'), None)
    if not dmmt:
        return

    output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
    output_input = output.inputs['Surface'].links[0].from_socket if output and output.inputs['Surface'].is_linked else None

    new_principled = nodes.new("ShaderNodeBsdfPrincipled")
    new_principled.location = dmmt.location

    socket_map = {
        'Base Color': 'Base Color',
        'Roughness': 'Roughness',
        'Metallic': 'Metallic',
        'Opacity': 'Alpha',
        'Emission': 'Emission',
        'IOR': 'IOR',
        'Normal': 'Normal'
    }
    transfer_socket(mat, dmmt, new_principled, socket_map)

    if output and output_input == dmmt.outputs['Output']:
        links.new(output.inputs['Surface'], new_principled.outputs[0])

    nodes.remove(dmmt)

class AETHER_PT_converter(bpy.types.Panel):
    bl_label = "Aether Material Tools"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = 'Aether'

    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == 'ShaderNodeTree'

    def draw(self, context):
        layout = self.layout
        layout.operator("aether.convert_to_dmmt", text="Convert to aether_master")
        layout.operator("aether.convert_to_principled", text="Convert to Principled BSDF")

class AETHER_OT_convert_to_dmnt(bpy.types.Operator):
    bl_idname = "aether.convert_to_dmmt"
    bl_label = "Convert to aether_master"

    def execute(self, context):
        convert_to_dmmt(context)
        return {'FINISHED'}

class AETHER_OT_convert_to_principled(bpy.types.Operator):
    bl_idname = "aether.convert_to_principled"
    bl_label = "Convert to Principled BSDF"

    def execute(self, context):
        convert_to_principled(context)
        return {'FINISHED'}

classes = (
    AETHER_PT_converter,
    AETHER_OT_convert_to_dmnt,
    AETHER_OT_convert_to_principled
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
