# core/material_builder.py
# Author: Luke Stilson / sharpen3d

import bpy
import os
from ..utils import append_content

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

    append_content.ensure_node_group("stx_pbr")

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


    # Ensure shared Texture Coordinate and Mapping nodes exist
    texcoord_node = next((n for n in nodes if n.type == 'TEX_COORD'), None)
    if not texcoord_node:
        texcoord_node = nodes.new("ShaderNodeTexCoord")
        texcoord_node.location = (-800, 0)

    mapping_node = next((n for n in nodes if n.type == 'MAPPING'), None)
    if not mapping_node:
        mapping_node = nodes.new("ShaderNodeMapping")
        mapping_node.location = (-600, 0)

    # Ensure link from UV to Mapping
    if not any(l.from_node == texcoord_node and l.to_node == mapping_node for l in links):
        links.new(texcoord_node.outputs['UV'], mapping_node.inputs['Vector'])
    
    expected = {item.map_type.lower() for item in scene.export_map_list}
    existing = {
        node.name.lower(): node
        for node in nodes
        if node.type == 'TEX_IMAGE' and node.name.lower() in expected
    }

    for node in list(nodes):
        if node.type == 'TEX_IMAGE' and node.name.lower() not in expected:
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

        tex_node = existing.get(map_type.lower())
        if not tex_node:
            tex_node = nodes.new("ShaderNodeTexImage")
            tex_node.name = map_type
            tex_node.label = map_type.title()
            tex_node.location = (0, y_offset)
            y_offset -= 300

        tex_node.image = image

        # Ensure Mapping is connected to texture vector input
        if not tex_node.inputs['Vector'].is_linked:
            links.new(mapping_node.outputs['Vector'], tex_node.inputs['Vector'])


        # Set color space for normal maps
        if map_type.upper() == "NORMAL":
            tex_node.image.colorspace_settings.name = 'Non-Color'

        # Find matching socket case-insensitively
        socket = next(
            (s for s in pbr_node.inputs if s.name.lower() == map_type.lower()),
            None
        )
        if socket:
            for link in list(links):
                if link.to_node == pbr_node and link.to_socket == socket:
                    links.remove(link)
            links.new(tex_node.outputs['Color'], socket)
            print(f"✅ Linked {filename} to '{socket.name}'")
        else:
            print(f"⚠️ No matching socket for '{map_type}' in stx_pbr")

    return mat

