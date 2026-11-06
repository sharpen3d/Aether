# core/material_builder.py
# Author: Luke Stilson / sharpen3d

import bpy
import os
from ..utils import append_content


def map_image_name(scene, item, preview=False):
    base_name = f"{scene.custom_object_name}{scene.delimiter}{item.map_name}.png"
    if preview:
        return f"{base_name}.preview"
    return base_name


def preview_cache_dir(scene):
    output_dir = bpy.path.abspath(scene.export_output_directory)
    return os.path.join(output_dir, ".aether_preview_cache")


def preview_cache_filepath(scene, item=None, active=False):
    cache_dir = preview_cache_dir(scene)
    if active:
        filename = f"{scene.custom_object_name}.active_preview.png"
    elif item is not None:
        filename = map_image_name(scene, item, preview=False)
    else:
        filename = f"{scene.custom_object_name}.preview.png"
    return os.path.join(cache_dir, filename)


def get_preview_object(scene):
    return next((obj for obj in scene.objects if ".stx_preview" in obj.name), None)


def assign_material_to_preview(scene, mat):
    preview_obj = get_preview_object(scene)
    if not preview_obj or not mat:
        return False

    modifier = preview_obj.modifiers.get("GeometryNodes")
    if not modifier:
        return False

    try:
        modifier["Socket_3"] = mat
        return True
    except (KeyError, TypeError):
        return False


def build_gpu_preview_material(scene, image):
    if image is None:
        return None

    mat_name = scene.custom_object_name + ".stx_gpu_preview"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True

    mat.use_nodes = True
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = 'DITHERED'

    ntree = mat.node_tree
    nodes = ntree.nodes
    links = ntree.links
    nodes.clear()

    output_node = nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (400, 0)

    emission_node = nodes.new("ShaderNodeEmission")
    emission_node.location = (180, 0)

    image_node = nodes.new("ShaderNodeTexImage")
    image_node.location = (-220, 0)
    image_node.image = image
    image_node.interpolation = 'Linear'

    texcoord_node = nodes.new("ShaderNodeTexCoord")
    texcoord_node.location = (-620, 0)

    mapping_node = nodes.new("ShaderNodeMapping")
    mapping_node.location = (-420, 0)

    links.new(texcoord_node.outputs['UV'], mapping_node.inputs['Vector'])
    links.new(mapping_node.outputs['Vector'], image_node.inputs['Vector'])
    links.new(image_node.outputs['Color'], emission_node.inputs['Color'])
    links.new(emission_node.outputs['Emission'], output_node.inputs['Surface'])

    return mat


def load_or_reload_image(image_name, filepath):
    image = bpy.data.images.get(image_name)
    if image is None:
        try:
            image = bpy.data.images.load(filepath, check_existing=False)
        except Exception:
            return None
        image.name = image_name
        return image

    try:
        image.filepath = filepath
        image.filepath_raw = filepath
        image.reload()
        return image
    except Exception:
        try:
            bpy.data.images.remove(image, do_unlink=True)
            image = bpy.data.images.load(filepath, check_existing=False)
            image.name = image_name
            return image
        except Exception:
            return None


def apply_rendered_maps_to_material(scene, use_preview_cache=False):
    output_dir = bpy.path.abspath(scene.export_output_directory)
    obj_name = scene.custom_object_name
    mat_name = obj_name + ".stxmat"

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
        filename = map_image_name(scene, item, preview=use_preview_cache)
        disk_filename = map_image_name(scene, item, preview=False)
        filepath = os.path.join(output_dir, disk_filename)
        image = bpy.data.images.get(filename)
        if use_preview_cache:
            preview_path = preview_cache_filepath(scene, item=item)
            if not os.path.exists(preview_path):
                print(f"⚠️ Missing preview cache: {preview_path}")
                continue
            image = load_or_reload_image(filename, preview_path)
            if image is None:
                print(f"❌ Failed to load preview cache: {preview_path}")
                continue
        else:
            if image is None:
                if not os.path.exists(filepath):
                    print(f"⚠️ Missing: {disk_filename} (no image and no disk file)")
                    continue
                try:
                    image = bpy.data.images.load(filepath)
                except Exception:
                    print(f"❌ Failed to load: {filepath}")
                    continue
            elif os.path.exists(filepath):
                try:
                    image.filepath = filepath
                    image.filepath_raw = filepath
                    image.reload()
                except Exception:
                    try:
                        bpy.data.images.remove(image, do_unlink=True)
                        image = bpy.data.images.load(filepath)
                    except Exception:
                        print(f"❌ Failed to reload from disk: {filepath}")
                        continue

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
