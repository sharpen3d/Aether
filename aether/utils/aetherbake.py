import bpy
import os
import platform
import subprocess
import json
from mathutils import Vector
from ..utils import append_content

# ---------- Utility Functions ----------

def store_render_settings(scene):
    return {
        'engine': scene.render.engine,
        'resolution_x': scene.render.resolution_x,
        'resolution_y': scene.render.resolution_y,
        'samples': scene.cycles.samples,
        'view_transform': scene.view_settings.view_transform,
        'color_mode': scene.render.image_settings.color_mode,
        'color_depth': scene.render.image_settings.color_depth,
        'file_format': scene.render.image_settings.file_format,
        'use_denoising': scene.cycles.use_denoising,
        'use_motion_blur': scene.render.use_motion_blur,
        'film_transparent': scene.render.film_transparent,
    }

def store_material_data(obj):
    mesh = obj.data
    material_slots = list(mesh.materials)
    poly_material_indices = [poly.material_index for poly in mesh.polygons]
    return material_slots, poly_material_indices

def restore_material_data(obj, material_slots, poly_material_indices):
    mesh = obj.data
    mesh.materials.clear()
    for mat in material_slots:
        mesh.materials.append(mat)
    for poly, mat_index in zip(mesh.polygons, poly_material_indices):
        poly.material_index = mat_index


def restore_render_settings(scene, settings):
    for key, value in settings.items():
        if hasattr(scene.render, key):
            setattr(scene.render, key, value)
        elif hasattr(scene.cycles, key):
            setattr(scene.cycles, key, value)
        elif key == 'view_transform':
            scene.view_settings.view_transform = value

def apply_bake_render_settings(scene, resolution):
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.render.use_motion_blur = False
    scene.render.film_transparent = True
    scene.render.resolution_x = resolution
    scene.render.resolution_y = resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '16'
    scene.render.image_settings.file_format = 'OPEN_EXR'
    scene.view_settings.view_transform = 'Raw'

def should_use_selected_to_active(scene, obj, source):
    return scene.aether_use_highpoly and source and source != obj

def prepare_bake_selection(target, source=None, use_selected_to_active=False):
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='DESELECT')
    if use_selected_to_active and source and source != target:
        source.hide_set(False)
        target.hide_set(False)
        source.select_set(True)
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
    else:
        target.hide_set(False)
        target.select_set(True)
        bpy.context.view_layer.objects.active = target

def create_bake_image(name, resolution, float_buffer=True):
    img = bpy.data.images.new(name, width=resolution, height=resolution, float_buffer=float_buffer)
    img.colorspace_settings.name = 'Non-Color'
    img.alpha_mode = 'NONE'
    return img

def assign_bake_material(obj, img, shader_fn=None):
    mat = bpy.data.materials.new("__AetherBakeTemp")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()

    img_node = nodes.new("ShaderNodeTexImage")
    img_node.image = img
    img_node.select = True
    nodes.active = img_node

    output = nodes.new("ShaderNodeOutputMaterial")

    if shader_fn:
        shader_fn(nodes, links, output)

    obj.data.materials.clear()
    obj.data.materials.append(mat)
    return mat, img_node

def bake_image(scene, bake_type='NORMAL', normal_space='TANGENT', use_selected_to_active=False):
    scene.cycles.bake_type = bake_type
    scene.render.bake.use_selected_to_active = use_selected_to_active
    scene.render.bake.use_pass_direct = False
    scene.render.bake.use_pass_indirect = False
    if bake_type == 'NORMAL':
        scene.render.bake.use_cage = False
        scene.render.bake.cage_extrusion = 0.4
        scene.render.bake.max_ray_distance = 0.8
        scene.render.bake.normal_space = normal_space
    bpy.ops.object.bake(type=bake_type)

def bake_map(obj, resolution, filepath, map_type, normal_space='TANGENT', source=None):
    scene = bpy.context.scene
    
    original_materials, poly_indices = store_material_data(obj)
    if source:
        source_materials, source_indices = store_material_data(source)
    else:
        source_materials, source_indices = None, None

    
    is_tangent_normal = map_type == 'NORMAL' and normal_space == 'TANGENT'
    is_object_normal = map_type == 'NORMAL' and normal_space == 'OBJECT'
    is_ao = map_type == 'AO'

    use_float = not is_tangent_normal
    img = create_bake_image(obj.name + "_" + map_type, resolution, float_buffer=True)
    img.filepath_raw = filepath
    img.file_format = 'OPEN_EXR'
    scene.render.image_settings.file_format = img.file_format
    scene.render.image_settings.color_depth = '16'
    scene.render.image_settings.color_mode = 'RGB'
    img.colorspace_settings.name = 'Non-Color'

    if is_ao:
        scene.cycles.samples = 256
        scene.cycles.use_denoising = True

    mat, img_node = assign_bake_material(obj, img)
    prepare_bake_selection(obj, source, use_selected_to_active=bool(source))
    bake_image(scene, bake_type=map_type, normal_space=normal_space, use_selected_to_active=bool(source))
    img.save()
    bpy.data.images.remove(img)
    bpy.data.materials.remove(mat)
    
    restore_material_data(obj, original_materials, poly_indices)
    if source and source_materials and source_indices:
        restore_material_data(source, source_materials, source_indices)


def normalize_to_unit_cube(obj):
    import bmesh
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    local_coords = [v.co.copy() for v in bm.verts]
    min_corner = Vector((min(v[i] for v in local_coords) for i in range(3)))
    max_corner = Vector((max(v[i] for v in local_coords) for i in range(3)))
    dims = max_corner - min_corner
    scale = Vector((1.0 / max(dims.x, 1e-6), 1.0 / max(dims.y, 1e-6), 1.0 / max(dims.z, 1e-6)))
    for v in bm.verts:
        v.co -= min_corner
        v.co.x *= scale.x
        v.co.y *= scale.y
        v.co.z *= scale.z
    bm.to_mesh(mesh)
    bm.free()
    return min_corner, max_corner

def unnormalize_from_bounds(obj, min_corner, max_corner):
    import bmesh
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    dims = max_corner - min_corner
    for v in bm.verts:
        v.co.x *= dims.x
        v.co.y *= dims.y
        v.co.z *= dims.z
        v.co += min_corner
    bm.to_mesh(mesh)
    bm.free()

def bake_custom_map(obj, resolution, filepath, shader_fn, source=None, grayscale=False, debug=False):
    scene = bpy.context.scene
    
    original_materials, poly_indices = store_material_data(obj)
    if source:
        source_materials, source_indices = store_material_data(source)
    else:
        source_materials, source_indices = None, None

    use_float = True
    img = create_bake_image(obj.name + "_Bake", resolution, float_buffer=use_float)
    img.filepath_raw = filepath
    img.file_format = 'OPEN_EXR' if use_float else 'PNG'
    scene.render.image_settings.file_format = img.file_format
    scene.render.image_settings.color_depth = '16' if use_float else '8'
    scene.render.image_settings.color_mode = 'RGB' if not grayscale else 'BW'
    img.colorspace_settings.name = 'Non-Color'

    if source:
        shader_mat, _ = assign_bake_material(source, None, shader_fn)
        _, img_node = assign_bake_material(obj, img)
    else:
        shader_mat, _ = assign_bake_material(obj, img, shader_fn)

    prepare_bake_selection(obj, source, use_selected_to_active=bool(source))
    bpy.ops.object.editmode_toggle()
    bpy.ops.object.editmode_toggle()

    if not debug:
        scene.cycles.use_denoising = grayscale
        bake_image(scene, bake_type='DIFFUSE', use_selected_to_active=bool(source))
        img.save()
        bpy.data.images.remove(img)
        bpy.data.materials.remove(shader_mat)
    else:
        print("[DEBUG] Shader preview active")
        bpy.context.space_data.shading.type = 'MATERIAL'
        
    restore_material_data(obj, original_materials, poly_indices)
    if source and source_materials and source_indices:
        restore_material_data(source, source_materials, source_indices)


def bake_curvature_map(obj, resolution, filepath, source=None, debug=False):
    scene = bpy.context.scene

    use_float = True
    img = create_bake_image(obj.name + "_Curvature", resolution, float_buffer=use_float)
    img.filepath_raw = filepath
    img.file_format = 'OPEN_EXR'
    scene.render.image_settings.file_format = img.file_format
    scene.render.image_settings.color_depth = '16'
    scene.render.image_settings.color_mode = 'BW'
    img.colorspace_settings.name = 'Non-Color'

    is_selected_to_active = source is not None
    bake_source = source if is_selected_to_active else obj
    bake_target = obj

    # Store original materials
    target_mats, target_indices = store_material_data(bake_target)
    source_mats, source_indices = (store_material_data(source) if is_selected_to_active else (None, None))

    # Assign GN modifier and curvature mat to source
    append_content.ensure_node_group("curvature_bake")
    gn_group = bpy.data.node_groups.get("curvature_bake")
    if not gn_group:
        raise RuntimeError("Missing 'curvature_bake' Geometry Nodes group")

    gn_mod = bake_source.modifiers.new(name="CurvatureBakeGN", type='NODES')
    gn_mod.node_group = gn_group

    curvature_mat = bpy.data.materials.new(name="__curvature_bake_mat__")
    curvature_mat.use_nodes = True
    ntree = curvature_mat.node_tree
    ntree.nodes.clear()
    
    output_node = ntree.nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (200, 0)


    attr = ntree.nodes.new("ShaderNodeAttribute")
    attr.attribute_name = "curvature"
    attr.location = (-400, 0)

    diffuse = ntree.nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.location = (-200, 0)

    ntree.links.new(attr.outputs['Fac'], diffuse.inputs['Color'])
    ntree.links.new(diffuse.outputs['BSDF'], output_node.inputs['Surface'])


    bake_source.data.materials.clear()
    bake_source.data.materials.append(curvature_mat)

    # Add image node to target only
    bake_target.data.materials.clear()
    mat = bpy.data.materials.new(name="__image_receiver__")
    mat.use_nodes = True
    ntree = mat.node_tree
    ntree.nodes.clear()

    output_node = ntree.nodes.new("ShaderNodeOutputMaterial")
    output_node.location = (200, 0)

    img_node = ntree.nodes.new("ShaderNodeTexImage")
    img_node.image = img
    img_node.location = (-200, 0)
    ntree.nodes.active = img_node  # Required for bake target

    ntree.links.new(img_node.outputs['Color'], output_node.inputs['Surface'])
    bake_target.data.materials.append(mat)

    # Prepare bake context
    prepare_bake_selection(bake_target, source, use_selected_to_active=is_selected_to_active)

    # Force depsgraph update
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.object.mode_set(mode='OBJECT')

    if not debug:
        scene.cycles.samples = 64
        scene.cycles.use_denoising = True
        bake_image(scene, bake_type='DIFFUSE', use_selected_to_active=is_selected_to_active)
        img.save()

        # Cleanup
        bpy.data.images.remove(img)
        bpy.data.materials.remove(curvature_mat)
        bpy.data.materials.remove(mat)
        bake_source.modifiers.remove(gn_mod)
    else:
        print("[DEBUG] Shader preview active")
        bpy.context.space_data.shading.type = 'MATERIAL'

    restore_material_data(bake_target, target_mats, target_indices)
    if is_selected_to_active:
        restore_material_data(source, source_mats, source_indices)



# ---------- Shader Templates ----------

def shader_curvature(nodes, links, output_node):
    scene = bpy.context.scene
    contrast = scene.aether_curvature_contrast
    geo = nodes.new("ShaderNodeNewGeometry")
    map_range = nodes.new("ShaderNodeMapRange")
    map_range.inputs[1].default_value = 0.25
    map_range.inputs[2].default_value = 0.75
    links.new(geo.outputs["Pointiness"], map_range.inputs[0])

    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(map_range.outputs["Result"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], output_node.inputs["Surface"])

def shader_position(nodes, links, output_node):
    geo = nodes.new("ShaderNodeNewGeometry")
    sep = nodes.new("ShaderNodeSeparateXYZ")
    combine = nodes.new("ShaderNodeCombineXYZ")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(geo.outputs["Position"], sep.inputs["Vector"])
    links.new(sep.outputs["X"], combine.inputs["X"])
    links.new(sep.outputs["Y"], combine.inputs["Y"])
    links.new(sep.outputs["Z"], combine.inputs["Z"])
    links.new(combine.outputs["Vector"], bsdf.inputs["Base Color"])
    links.new(bsdf.outputs["BSDF"], output_node.inputs["Surface"])


# ---------- Operators and UI ----------

class AETHER_OT_bake_source_maps(bpy.types.Operator):
    bl_idname = "aether.bake_source_maps"
    bl_label = "Bake Source Maps"

    def execute(self, context):
        scene = context.scene
        obj = scene.aether_target_obj
        source = scene.aether_source_obj
        resolution = int(scene.aether_bake_resolution)
        base_dir = bpy.path.abspath(f"//{obj.name}/source_maps")
        os.makedirs(base_dir, exist_ok=True)

        use_selected_to_active = should_use_selected_to_active(scene, obj, source)

        settings = store_render_settings(scene)
        apply_bake_render_settings(scene, resolution)

        try:
            prepare_bake_selection(obj)
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            if obj.type == 'MESH' and obj.data.uv_layers.active:
                bpy.ops.uv.export_layout(filepath=os.path.join(base_dir, f"{obj.name}_uv.png"), size=(resolution, resolution), opacity=1.0)
            bpy.ops.object.mode_set(mode='OBJECT')

            bake_map(obj, resolution, os.path.join(base_dir, f"{obj.name}_normal.png"), 'NORMAL', 'TANGENT', source if use_selected_to_active else None)
            bake_map(obj, resolution, os.path.join(base_dir, f"{obj.name}_normal-obj.png"), 'NORMAL', 'OBJECT', source if use_selected_to_active else None)
#            if use_selected_to_active:
            bake_map(obj, resolution, os.path.join(base_dir, f"{obj.name}_ao.png"), 'AO', 'TANGENT', source if use_selected_to_active else None)
            bake_curvature_map(obj, resolution, os.path.join(base_dir, f"{obj.name}_curvature.png"),  source if use_selected_to_active else None)
            min_bound, max_bound = normalize_to_unit_cube(obj)
            bake_custom_map(obj, resolution, os.path.join(base_dir, f"{obj.name}_position.png"), shader_position, source=None, grayscale=False)
            unnormalize_from_bounds(obj, min_bound, max_bound)
            bounds_data = {
                "min": list(min_bound),
                "max": list(max_bound)
            }
            with open(os.path.join(base_dir, f"{obj.name}_position_bounds.json"), 'w') as f:
                json.dump(bounds_data, f, indent=4)
            
            bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT'
            bpy.context.scene.view_layers["ViewLayer"].use = False

        finally:
            restore_render_settings(scene, settings)
            
            # set up material authoring scene
            context.scene.export_settings.source_object = obj
            context.scene.custom_object_name = obj.name + "_mat"
            #bpy.ops.exportmap.create_bake_scene()
            
        return {'FINISHED'}

class AETHER_OT_open_export_dir(bpy.types.Operator):
    bl_idname = "aether.open_export_dir"
    bl_label = "Open Export Directory"

    def execute(self, context):
        obj = context.scene.aether_target_obj
        path = bpy.path.abspath(f"//{obj.name}/source_maps")
        if platform.system() == 'Windows':
            os.startfile(path)
        elif platform.system() == 'Darwin':
            subprocess.call(["open", path])
        else:
            subprocess.call(["xdg-open", path])
        return {'FINISHED'}

class AETHER_PT_bake_panel(bpy.types.Panel):
    bl_label = "Source Map Baking"
    bl_idname = "AETHER_PT_bake_panel"
    bl_space_type = 'VIEW_3D' 
    bl_region_type = 'UI'  
    bl_category = 'Aether'    

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        layout.prop(scene, "aether_target_obj")
        layout.prop(scene, "aether_use_highpoly")
        if scene.aether_use_highpoly:
            layout.prop(scene, "aether_source_obj")
        layout.prop(scene, "aether_bake_resolution")
#        layout.prop(scene, "aether_curvature_contrast")
        layout.operator("aether.bake_source_maps")
        layout.operator("aether.open_export_dir", icon='FILE_FOLDER')

# ---------- Registration ----------

def register():
    bpy.utils.register_class(AETHER_OT_bake_source_maps)
    bpy.utils.register_class(AETHER_OT_open_export_dir)
    bpy.utils.register_class(AETHER_PT_bake_panel)
    bpy.types.Scene.aether_target_obj = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.aether_source_obj = bpy.props.PointerProperty(type=bpy.types.Object)
    bpy.types.Scene.aether_use_highpoly = bpy.props.BoolProperty(name="From High Res", default=False)
    bpy.types.Scene.aether_bake_resolution = bpy.props.EnumProperty(
        name="Resolution",
        items=[(str(x), f"{x}x{x}", "") for x in [512, 1024, 2048, 4096]],
        default='2048'
    )
    bpy.types.Scene.aether_curvature_contrast = bpy.props.FloatProperty(
        name="Curvature Contrast",
        description="Controls the contrast range for curvature map baking",
        min=0.0,
        max=1.0,
        default=1.0
    )

def unregister():
    bpy.utils.unregister_class(AETHER_OT_bake_source_maps)
    bpy.utils.unregister_class(AETHER_OT_open_export_dir)
    bpy.utils.unregister_class(AETHER_PT_bake_panel)
    del bpy.types.Scene.aether_target_obj
    del bpy.types.Scene.aether_source_obj
    del bpy.types.Scene.aether_use_highpoly
    del bpy.types.Scene.aether_bake_resolution
    del bpy.types.Scene.aether_curvature_contrast

if __name__ == "__main__":
    register()