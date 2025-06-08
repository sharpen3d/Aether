# core/material_builder.py
# Author: Luke Stilson / sharpen3d

import bpy
import os


def apply_rendered_maps_to_material(scene):
    output_dir = bpy.path.abspath(scene.export_output_directory)
    obj_name = scene.custom_object_name
    mat_name = obj_name + ".stxmat"
    delimiter = scene.delimiter

    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True

    ntree = mat.node_tree
    nodes = ntree.nodes
    links = ntree.links

    output_node = None
    pbr_node = None
    for node in nodes:
        if node.type == 'OUTPUT_MATERIAL':
            output_node = node
        elif node.type == 'GROUP' and node.node_tree and node.node_tree.name == 'stx_pbr':
            pbr_node = node
        else:
            nodes.remove(node)

    if not output_node:
        output_node = nodes.new("ShaderNodeOutputMaterial")
        output_node.location = (800, 0)

    if not pbr_node:
        pbr_group = bpy.data.node_groups.get("stx_pbr")
        if not pbr_group:
            print("❌ Node group 'stx_pbr' not found.")
            return None
        pbr_node = nodes.new("ShaderNodeGroup")
        pbr_node.node_tree = pbr_group
        pbr_node.location = (400, 0)

    if not any(link.to_node == output_node and link.from_node == pbr_node for link in links):
        links.new(pbr_node.outputs[0], output_node.inputs[0])

    expected = {item.map_type for item in scene.export_map_list}
    existing = {
        node.name: node
        for node in nodes
        if node.type == 'TEX_IMAGE' and node.name in expected
    }

    for node in list(nodes):
        if node.type == 'TEX_IMAGE' and node.name not in expected:
            nodes.remove(node)

    y_offset = 0
    for item in scene.export_map_list:
        map_type = item.map_type
        map_name = item.map_name
        filename = f"{obj_name}{delimiter}{map_name}.png"
        filepath = os.path.join(output_dir, filename)

        if not os.path.exists(filepath):
            print(f"⚠️ Missing: {filepath}")
            continue

        image = bpy.data.images.get(filename)
        if not image:
            try:
                image = bpy.data.images.load(filepath)
            except:
                print(f"❌ Failed to load: {filepath}")
                continue
        else:
            image.reload()

        tex_node = existing.get(map_type)
        if not tex_node:
            tex_node = nodes.new("ShaderNodeTexImage")
            tex_node.name = map_type
            tex_node.label = map_type.title()
            tex_node.location = (0, y_offset)
            y_offset -= 300
        tex_node.image = image

        socket = pbr_node.inputs.get(map_type.title())
        if socket:
            for link in list(links):
                if link.to_node == pbr_node and link.to_socket == socket:
                    links.remove(link)
            links.new(tex_node.outputs['Color'], socket)
            print(f"✅ Linked {filename} to '{socket.name}'")
        else:
            print(f"⚠️ No matching socket '{map_type.title()}' in stx_pbr")

    return mat

