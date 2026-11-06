import bpy
import os
import platform
import subprocess
import json
import numpy as np
from mathutils import Vector

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


def snapshot_multires(*objs):
    """For each object, find every Multires modifier and snapshot its
    `levels` / `render_levels` / `sculpt_levels`. Then push the modifier
    to viewport=0 + render_levels=total so the bake reads the
    fully-detailed sculpted surface while UVs stay anchored to the base
    mesh.

    Returns a list of (modifier, prev_levels, prev_render_levels,
    prev_sculpt_levels) tuples to be passed back to `restore_multires`.

    Works for both common workflows:
        - Multires on the lowpoly target (single-object mode): bake
          reads multires-displaced surface, writes to base UVs.
        - Multires on the highpoly source (selected-to-active): the
          highpoly's full sculpt detail is sampled when projecting from
          source -> target.

    Edge case noted but not addressed here: position bake combined with
    multires on the lowpoly will produce position values outside [0,1]
    for sculpted areas, because `normalize_to_unit_cube` measures only
    the base mesh bounds. The EMIT bake won't clamp, so the EXR will
    contain the extended values, but the importer's Map Range decode
    assumes [0,1] input. Sculpt on the highpoly for accurate positions.
    """
    snapshots = []
    for obj in objs:
        if obj is None:
            continue
        for mod in obj.modifiers:
            if mod.type == 'MULTIRES':
                snapshots.append((
                    mod,
                    mod.levels,
                    mod.render_levels,
                    mod.sculpt_levels,
                ))
                mod.levels = 0
                mod.render_levels = mod.total_levels
    return snapshots


def restore_multires(snapshots):
    for mod, lv, rlv, slv in snapshots:
        try:
            mod.levels = lv
            mod.render_levels = rlv
            mod.sculpt_levels = slv
        except Exception:
            # Modifier may have been removed by user code mid-bake; we'd
            # rather swallow than surface a confusing restore error after
            # the bakes already succeeded.
            pass


def _combined_bounds_diag(*objs):
    mins = []
    maxs = []
    for obj in objs:
        if obj is None:
            continue
        min_corner, max_corner = compute_local_bounds(obj)
        mins.append(min_corner)
        maxs.append(max_corner)
    if not mins:
        return 1.0
    min_corner = Vector((min(v[i] for v in mins) for i in range(3)))
    max_corner = Vector((max(v[i] for v in maxs) for i in range(3)))
    return max((max_corner - min_corner).length, 1e-6)


def _apply_selected_to_active_ray_settings(scene, target, source):
    bake = scene.render.bake
    diag = _combined_bounds_diag(target, source)
    extrusion_scale = float(getattr(scene, "aether_bake_cage_extrusion_scale", 0.0025))
    ray_scale = float(getattr(scene, "aether_bake_max_ray_distance_scale", 0.01))

    bake.use_cage = False
    bake.cage_extrusion = diag * extrusion_scale
    bake.max_ray_distance = diag * ray_scale

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

def bake_image(scene, bake_type='NORMAL', normal_space='TANGENT',
               use_selected_to_active=False, target=None, source=None):
    scene.cycles.bake_type = bake_type
    bake = scene.render.bake
    bake.use_selected_to_active = use_selected_to_active
    bake.use_pass_direct = False
    bake.use_pass_indirect = False

    # UV-island padding. Default `EXTEND` smears the last edge texel
    # outward as a flat ramp, which lights up as a hard step under
    # downstream derivatives (the curvature pass especially picks it up
    # as a UV-island outline). `ADJACENT_FACES` walks across the
    # topological seam and fills the margin with samples from the
    # neighboring face, which is what we want — seamless across UV
    # islands at the cost of slightly slower bakes. Available in 4.x.
    # Margin of 16 px covers our curvature blur radius (default 4 px)
    # plus comfortable headroom; bump only if soft_radius gets cranked.
    bake.margin = 16
    bake.margin_type = 'ADJACENT_FACES'

    # Cage / ray-projection controls govern how rays start from the lowpoly
    # surface and how far they march before terminating. They apply to ANY
    # selected-to-active bake (NORMAL, AO, custom EMIT/DIFFUSE), not just
    # NORMAL. Previously these were only set on the NORMAL branch, which is
    # why AO came out solid black under highpoly→lowpoly: rays started at
    # cage_extrusion=0 (i.e. exactly on the lowpoly surface, often inside
    # the highpoly cage) and self-occluded immediately.
    if use_selected_to_active:
        _apply_selected_to_active_ray_settings(scene, target, source)
    if bake_type == 'NORMAL':
        bake.normal_space = normal_space
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
    elif map_type == 'NORMAL':
        # 1 sample per texel = no AA at polygon edges within a texel,
        # so vertex-normal interpolation steps appear as visible polygon
        # facets in the EXR (and get amplified into "polygons showing
        # through" in the curvature derivative). Cycles supersamples
        # the bake by `samples` and averages, so 16 dilutes the step
        # function to a smooth ramp. Cheap — NORMAL bake itself is
        # essentially deterministic per shading point, so the cost is
        # purely in extra ray casts at texel edges.
        scene.cycles.samples = 16

    # AO needs a real Surface link on whichever material Cycles is sampling
    # at the shading point, otherwise the surface is treated as transparent
    # and the AO integrator returns 0 (solid black EXR). For NORMAL and
    # OBJECT-space normal bakes Cycles synthesizes the geometry surface
    # internally, so the empty material is fine.
    #   - selected_to_active AO: shading point lives on the highpoly, so
    #     the white-diffuse goes on `source` and the lowpoly carries only
    #     the image receiver.
    #   - single-object AO: same material does both.
    shader_mat = None
    if is_ao:
        if source:
            shader_mat, _ = assign_bake_material(source, None, shader_white_diffuse)
            mat, img_node = assign_bake_material(obj, img)
        else:
            mat, img_node = assign_bake_material(obj, img, shader_white_diffuse)
    else:
        mat, img_node = assign_bake_material(obj, img)

    prepare_bake_selection(obj, source, use_selected_to_active=bool(source))
    bake_image(
        scene,
        bake_type=map_type,
        normal_space=normal_space,
        use_selected_to_active=bool(source),
        target=obj,
        source=source,
    )
    img.save()
    bpy.data.images.remove(img)
    bpy.data.materials.remove(mat)
    if shader_mat is not None:
        bpy.data.materials.remove(shader_mat)

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


def compute_local_bounds(obj):
    import bmesh
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    local_coords = [v.co.copy() for v in bm.verts]
    bm.free()
    min_corner = Vector((min(v[i] for v in local_coords) for i in range(3)))
    max_corner = Vector((max(v[i] for v in local_coords) for i in range(3)))
    return min_corner, max_corner


def normalize_to_bounds(obj, min_corner, max_corner):
    import bmesh
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    dims = max_corner - min_corner
    scale = Vector((
        1.0 / max(dims.x, 1e-6),
        1.0 / max(dims.y, 1e-6),
        1.0 / max(dims.z, 1e-6),
    ))
    for v in bm.verts:
        v.co -= min_corner
        v.co.x *= scale.x
        v.co.y *= scale.y
        v.co.z *= scale.z
    bm.to_mesh(mesh)
    bm.free()

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

def bake_custom_map(obj, resolution, filepath, shader_fn, source=None,
                    grayscale=False, debug=False, bake_type='DIFFUSE'):
    """Bake a custom shader output to an EXR.

    bake_type:
        'DIFFUSE' - reads BSDF Base Color via the diffuse color pass.
                    Suitable for shaders that already constrain output to
                    [0,1] (e.g. curvature). DO NOT use for raw position
                    output; Principled BSDF clamps Base Color to [0,1].
        'EMIT'    - reads ShaderNodeEmission.Color directly with no
                    BSDF interaction or color-pass scaling. Use this for
                    position, world normals, or anything where the shader
                    produces values that must pass through unmodified.
    """
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
        bake_image(
            scene,
            bake_type=bake_type,
            use_selected_to_active=bool(source),
            target=obj,
            source=source,
        )
        img.save()
        bpy.data.images.remove(img)
        bpy.data.materials.remove(shader_mat)
    else:
        print("[DEBUG] Shader preview active")
        bpy.context.space_data.shading.type = 'MATERIAL'

    restore_material_data(obj, original_materials, poly_indices)
    if source and source_materials and source_indices:
        restore_material_data(source, source_materials, source_indices)


def _cotangent(a, b):
    cross_len = a.cross(b).length
    if cross_len < 1e-12:
        return 0.0
    return a.dot(b) / cross_len


def _smooth_vertex_scalar(values, adjacency, iterations):
    if iterations <= 0:
        return values.astype(np.float32)
    out = values.astype(np.float32).copy()
    for _ in range(iterations):
        nxt = out.copy()
        for i, nbrs in enumerate(adjacency):
            if not nbrs:
                continue
            avg = sum(out[j] for j in nbrs) / float(len(nbrs))
            nxt[i] = 0.5 * out[i] + 0.5 * avg
        out = nxt
    return out


def _compute_mesh_curvature_values(obj, contrast=2.0, hard_weight=0.65, soft_radius=4):
    import bmesh

    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    tri_bm = bm.copy()
    bmesh.ops.triangulate(tri_bm, faces=tri_bm.faces[:])
    tri_bm.verts.ensure_lookup_table()
    tri_bm.faces.ensure_lookup_table()

    vert_count = len(tri_bm.verts)
    weights = {}
    area = np.zeros(vert_count, dtype=np.float64)
    adjacency = [set() for _ in range(vert_count)]

    for face in tri_bm.faces:
        if len(face.verts) != 3:
            continue
        i0, i1, i2 = [v.index for v in face.verts]
        p0, p1, p2 = [v.co.copy() for v in face.verts]

        e0 = p1 - p0
        tri_area = (e0.cross(p2 - p0)).length * 0.5
        share = tri_area / 3.0
        area[i0] += share
        area[i1] += share
        area[i2] += share

        cot0 = _cotangent(p1 - p0, p2 - p0)
        cot1 = _cotangent(p2 - p1, p0 - p1)
        cot2 = _cotangent(p0 - p2, p1 - p2)

        for a, b, w in (
            (i1, i2, cot0),
            (i2, i0, cot1),
            (i0, i1, cot2),
        ):
            key = tuple(sorted((a, b)))
            weights[key] = weights.get(key, 0.0) + w
            adjacency[a].add(b)
            adjacency[b].add(a)

    acc = [Vector((0.0, 0.0, 0.0)) for _ in range(vert_count)]
    for (i, j), w in weights.items():
        pi = tri_bm.verts[i].co
        pj = tri_bm.verts[j].co
        acc[i] += w * (pi - pj)
        acc[j] += w * (pj - pi)

    raw = np.zeros(vert_count, dtype=np.float32)
    for i in range(vert_count):
        a = max(area[i], 1e-12)
        hn = acc[i] / (2.0 * a)
        raw[i] = hn.length

    tri_bm.free()
    bm.free()

    soft_iters = max(int(soft_radius), 0)
    soft = _smooth_vertex_scalar(raw, adjacency, soft_iters)
    mixed = raw * float(hard_weight) + soft * float(1.0 - hard_weight)

    p95 = float(np.percentile(mixed, 95.0)) if len(mixed) else 1.0
    scale = max(p95, 1e-8)
    mixed = np.clip((mixed / scale) * float(contrast), 0.0, 1.0).astype(np.float32)
    return mixed


def _write_curvature_attribute(obj, attr_name, values):
    mesh = obj.data
    color_attrs = mesh.color_attributes
    attr = color_attrs.get(attr_name)
    if attr is not None:
        color_attrs.remove(attr)
    attr = color_attrs.new(name=attr_name, type='FLOAT_COLOR', domain='POINT')
    for i, value in enumerate(values):
        attr.data[i].color = (value, value, value, 1.0)
    return attr


def shader_color_attribute(attribute_name):
    def _shader(nodes, links, output_node):
        attr = nodes.new("ShaderNodeAttribute")
        attr.attribute_name = attribute_name
        emission = nodes.new("ShaderNodeEmission")
        links.new(attr.outputs["Color"], emission.inputs["Color"])
        links.new(emission.outputs["Emission"], output_node.inputs["Surface"])
    return _shader


def bake_curvature_from_geometry(obj, resolution, filepath, source=None,
                                 contrast=2.0, hard_weight=0.65, soft_radius=4):
    curvature_obj = source if source else obj
    attr_name = "__aether_curvature__"
    attr = None
    try:
        values = _compute_mesh_curvature_values(
            curvature_obj,
            contrast=contrast,
            hard_weight=hard_weight,
            soft_radius=soft_radius,
        )
        attr = _write_curvature_attribute(curvature_obj, attr_name, values)
        bake_custom_map(
            obj,
            resolution,
            filepath,
            shader_color_attribute(attr_name),
            source=source,
            grayscale=True,
            bake_type='EMIT',
        )
    finally:
        if attr is not None:
            existing = curvature_obj.data.color_attributes.get(attr_name)
            if existing is not None:
                curvature_obj.data.color_attributes.remove(existing)


def derive_curvature_from_source_maps(normal_filepath, position_filepath,
                                      bounds_filepath, curvature_filepath,
                                      contrast=2.0, hard_weight=0.65,
                                      soft_radius=4):
    """Compute a curvature map from object-space normal + world-position
    bakes. Post-process only — no Cycles bake — modeled on Substance
    Painter's "Curvature from Mesh" workflow but driven entirely from the
    texture-space derivatives of the already-baked source maps.

    Why this and not Geometry.Pointiness:
        Pointiness is a per-shading-point edge-angle measurement, so its
        resolution is bounded by mesh density. Object-space normals are
        continuous across the texture grid, so spatial derivatives produce
        a clean per-texel curvature regardless of underlying mesh density.
        Identical pathway for single-object and highpoly→lowpoly bakes
        since it only consumes the EXRs.

    Math:
        κ ≈ (∂N/∂u · ∂P/∂u) / |∂P/∂u|² + (∂N/∂v · ∂P/∂v) / |∂P/∂v|²

        Equivalent to the trace of the Weingarten map (= 2 · mean curvature
        in surface parameterization). Positive → convex ridges, negative →
        concave creases. Every term is a 3D dot product of vectors that
        co-rotate with the surface, so the result is *rotation- and
        mirror-invariant*: a mirrored model half produces matching
        curvature on shared UV territory. The earlier "∂N.x/∂u + ∂N.y/∂v"
        formulation read world X/Y components of N directly, which broke
        symmetry — mirroring across X flipped Nx and inverted curvature on
        the mirrored half.

        ∂P/∂u is the world-space surface tangent at each texel: literally
        "the direction in 3D the surface moves when texel U increments by
        one." We bake this as `_position.exr` (unit-cube-normalized in
        [0,1]); multiplying by per-axis (max - min) from the bounds JSON
        recovers world units. The constant min-corner offset cancels under
        differentiation.

        After computing κ we multiply by the AABB diagonal so the scalar
        is dimensionless — `contrast=2.0` reads the same on a thumbnail
        prop as on a building.

    Inputs:
        normal_filepath:   EXR with object-space normal in [0,1] encoding
        position_filepath: EXR with unit-cube-normalized object position
        bounds_filepath:   JSON with {"min":[x,y,z], "max":[x,y,z]}

    Notes / caveats:
        - Inherits seam/cage artifacts from the source bakes. If they're
          visible in the EXRs, they'll be visible (and amplified) in
          curvature.
        - Validity is determined from the normal map (|N| ≈ 1). Pixels
          outside the bake margin are clamped to neutral 0.5 in the output
          so downstream sampling outside an island reads as flat.
    """
    n_img = bpy.data.images.load(normal_filepath, check_existing=False)
    n_img.colorspace_settings.name = 'Non-Color'
    p_img = bpy.data.images.load(position_filepath, check_existing=False)
    p_img.colorspace_settings.name = 'Non-Color'
    try:
        w, h = n_img.size
        if w == 0 or h == 0:
            raise RuntimeError(f"Normal map {normal_filepath} has zero size")
        if (p_img.size[0], p_img.size[1]) != (w, h):
            raise RuntimeError(
                f"Position map size {tuple(p_img.size)} doesn't match "
                f"normal map size {(w, h)}; rebake at a single resolution."
            )

        n_buf = np.empty(w * h * 4, dtype=np.float32)
        n_img.pixels.foreach_get(n_buf)
        # Decode unsigned [0,1] → signed [-1,1]. Object-space normals are
        # stored that way per Cycles' OBJECT bake convention. Immediately
        # renormalize to unit length; EXR quantization and bake filtering
        # can drift the magnitude slightly, and the curvature solve assumes
        # N is a unit normal field.
        n = n_buf.reshape((h, w, 4))[:, :, :3] * 2.0 - 1.0
        n = _safe_normalize_vectors(n)

        p_buf = np.empty(w * h * 4, dtype=np.float32)
        p_img.pixels.foreach_get(p_buf)
        p_encoded = p_buf.reshape((h, w, 4))[:, :, :3]
    finally:
        bpy.data.images.remove(n_img)
        bpy.data.images.remove(p_img)

    with open(bounds_filepath, 'r') as fh:
        bounds = json.load(fh)
    pmin = np.array(bounds["min"], dtype=np.float32)
    pmax = np.array(bounds["max"], dtype=np.float32)
    pscale = pmax - pmin                                # (3,) world-units span
    diag = float(np.linalg.norm(pscale))                # AABB diagonal length
    if diag < 1e-6:
        # Degenerate bounds (all-coincident verts?). Fall back to unit
        # scale so we still emit a deterministic image rather than divide
        # by zero downstream.
        diag = 1.0

    # Recover world-units position. The constant `pmin` offset cancels in
    # the central difference, but include it so any future use of `p`
    # outside the differential picks up correct values.
    p = p_encoded * pscale[None, None, :] + pmin[None, None, :]

    # Bake canvas outside UV islands + margin is (0,0,0) in the encoded
    # normal, decoding to (-1,-1,-1) — magnitude √3, not a real surface
    # normal. Real baked normals are unit length. Without filtering, the
    # box blur drags those invalid pixels inward and the derivative reads
    # the resulting step as a phantom curvature edge around every island.
    mag = np.linalg.norm(n, axis=2)
    valid = np.abs(mag - 1.0) < 0.3

    # Inpaint both fields outward by enough pixels that the central
    # difference (1 px) and the soft-pass box blur (`soft_radius` px)
    # sample only valid-ish data right up to the edge of the original
    # bake. The inpainted band is numerical padding for the derivative;
    # we mask it out below before writing the final EXR.
    inpaint_iters = max(soft_radius + 2, 4)
    n = _safe_normalize_vectors(_inpaint_outward(n, valid, iterations=inpaint_iters))
    p = _inpaint_outward(p, valid, iterations=inpaint_iters)

    curvature = _unsigned_curvature_from_normal_position(
        n, p, diag=diag, hard_weight=hard_weight, soft_radius=soft_radius
    )

    # Unsigned edge/cavity mask: flat = 0, features > 0. This dedicates
    # the full value range to useful signal instead of wasting half the
    # range on signed negative curvature, which was reading as blotchy
    # black/white ink rather than smooth Painter-style gradients.
    curvature = curvature * contrast * 0.35
    np.clip(curvature, 0.0, 1.0, out=curvature)

    # Past the original bake-valid region the curvature is extrapolation
    # — useful as derivative padding, meaningless as a final value. Force
    # to 0 so anything sampling outside the bake margin reads as flat.
    curvature = np.where(valid, curvature, 0.0)

    out = np.empty((h, w, 4), dtype=np.float32)
    out[:, :, 0] = curvature
    out[:, :, 1] = curvature
    out[:, :, 2] = curvature
    out[:, :, 3] = 1.0

    out_img = bpy.data.images.new(
        "__curvature_temp", width=w, height=h, float_buffer=True,
    )
    out_img.colorspace_settings.name = 'Non-Color'
    out_img.alpha_mode = 'NONE'
    out_img.pixels.foreach_set(out.ravel())
    out_img.filepath_raw = curvature_filepath
    out_img.file_format = 'OPEN_EXR'

    scene = bpy.context.scene
    prev_color_mode = scene.render.image_settings.color_mode
    scene.render.image_settings.color_mode = 'BW'
    try:
        out_img.save()
    finally:
        scene.render.image_settings.color_mode = prev_color_mode
        bpy.data.images.remove(out_img)


def _surface_divergence(n, p):
    """Compatibility wrapper for the old name."""
    return _mean_curvature_from_fields(n, p)


def _mean_curvature_from_fields(n, p):
    """Approximate signed mean curvature from position + normal fields.

    This uses the first and second fundamental forms instead of the old
    shortcut:

        H = (eG - 2fF + gE) / (2 * (E G - F^2))

    with
        E = Pu·Pu, F = Pu·Pv, G = Pv·Pv
        e = -Nu·Pu
        f = -0.5 * (Nu·Pv + Nv·Pu)
        g = -Nv·Pv

    The previous implementation assumed F≈0 (an orthogonal texture
    parameterization) and reduced to a simple trace-like estimate. Real UV
    unwraps often have heavy skew, so ignoring F creates large false edges
    and polygon/facet artifacts even when the baked normal map is fine.

    Inputs:
        n: (H, W, 3) unit normal field
        p: (H, W, 3) world-units position field

    Returns:
        (H, W) float32 signed mean curvature proxy.
    """
    dn_du = np.zeros_like(n)
    dn_dv = np.zeros_like(n)
    dp_du = np.zeros_like(p)
    dp_dv = np.zeros_like(p)

    dn_du[:, 1:-1, :] = (n[:, 2:, :] - n[:, :-2, :]) * 0.5
    dn_dv[1:-1, :, :] = (n[2:, :, :] - n[:-2, :, :]) * 0.5
    dp_du[:, 1:-1, :] = (p[:, 2:, :] - p[:, :-2, :]) * 0.5
    dp_dv[1:-1, :, :] = (p[2:, :, :] - p[:-2, :, :]) * 0.5

    E = np.sum(dp_du * dp_du, axis=2)
    F = np.sum(dp_du * dp_dv, axis=2)
    G = np.sum(dp_dv * dp_dv, axis=2)

    e = -np.sum(dn_du * dp_du, axis=2)
    f = -0.5 * (
        np.sum(dn_du * dp_dv, axis=2) +
        np.sum(dn_dv * dp_du, axis=2)
    )
    g = -np.sum(dn_dv * dp_dv, axis=2)

    denom = (E * G - F * F)

    # Degenerate metric -> no reliable tangent frame. Fall back to flat.
    eps = 1e-10
    mean_curvature = np.where(
        denom > eps,
        (e * G - 2.0 * f * F + g * E) / np.maximum(2.0 * denom, eps),
        0.0,
    )

    return mean_curvature.astype(np.float32)


def _unsigned_curvature_from_normal_position(n, p, diag, hard_weight, soft_radius):
    """Unsigned multi-scale curvature proxy from normal variation.

    This is intentionally closer to a practical texturing mask than to a
    mathematically signed curvature field:

      - small blur  -> sharp edge response
      - large blur  -> broader cavity response
      - no convex/concave sign split

    The earlier signed version spent a lot of effort recovering sign from
    position, but in practice that made the result blotchy and unstable.
    For Painter-style utility bakes, a smooth unsigned feature mask is
    often much more usable.
    """
    small_radius = 1
    large_radius = max(int(soft_radius), 2)

    n_small = _safe_normalize_vectors(_box_blur_2d(n, small_radius))
    n_large = _safe_normalize_vectors(_box_blur_2d(n, large_radius))

    hard = np.linalg.norm(n - n_small, axis=2)
    soft = np.linalg.norm(n - n_large, axis=2)
    response = hard * hard_weight + soft * (1.0 - hard_weight)

    # Normalize by local world-units-per-texel so UV density/stretch
    # doesn't dominate the signal.
    dp_du = np.zeros_like(p)
    dp_dv = np.zeros_like(p)
    dp_du[:, 1:-1, :] = (p[:, 2:, :] - p[:, :-2, :]) * 0.5
    dp_dv[1:-1, :, :] = (p[2:, :, :] - p[:-2, :, :]) * 0.5
    step_u = np.linalg.norm(dp_du, axis=2)
    step_v = np.linalg.norm(dp_dv, axis=2)
    local_step = np.maximum(0.5 * (step_u + step_v), 1e-8)
    response = response / local_step

    # Make dimensionless across object scale, then lightly smooth to
    # suppress texel chatter without erasing broad gradients.
    unsigned_curvature = response * float(diag)
    unsigned_curvature = _box_blur_2d(
        unsigned_curvature[:, :, None], 1
    )[:, :, 0]
    return unsigned_curvature.astype(np.float32)


def _safe_normalize_vectors(v):
    """Normalize a vector field while leaving near-zero vectors at 0.

    Curvature assumes the normal field is unit length. Any blur/inpaint on
    the baked normal map turns unit vectors into arbitrary-length averages,
    which biases the divergence solve toward polygon/facet artifacts.
    """
    mag = np.linalg.norm(v, axis=2, keepdims=True)
    return np.where(mag > 1e-8, v / mag, 0.0).astype(np.float32)


def _inpaint_outward(n, mask, iterations):
    """Iteratively spread valid normal data into invalid regions.

    Each pass replaces an invalid pixel that has at least one valid
    4/8-neighbor with the weighted average of its valid neighbors.
    Implemented as a masked 3×3 box blur — `_box_blur_2d` of (n * w)
    divided by `_box_blur_2d` of (w) collapses to "average of where w>0",
    which is exactly the masked mean we need.

    The inpaint isn't trying to invent plausible surface normals beyond
    the bake; it's just stretching the boundary outward so a downstream
    convolution kernel doesn't see a hard step into invalid pixels. The
    caller masks the final curvature back to the original valid region.
    """
    if iterations <= 0:
        return n.copy()
    n_filled = n.copy()
    m = mask.copy()
    for _ in range(iterations):
        weight = m.astype(np.float32)[..., None]   # (H,W,1)
        b_n = _box_blur_2d(n_filled * weight, 1)
        b_w = _box_blur_2d(weight, 1)
        # Ratio collapses the /9 normalization in box_blur_2d, so the
        # result is the actual average over only valid neighbors.
        b_w_safe = np.maximum(b_w, 1e-6)
        avg_n = b_n / b_w_safe
        # Promote pixels that were previously invalid but now have at
        # least one valid neighbor contributing to the average. The
        # 0.01 threshold rejects floating-point noise from b_w being
        # technically nonzero but effectively empty.
        new_valid = ~m & (b_w[..., 0] > 0.01)
        n_filled = np.where(new_valid[..., None], avg_n, n_filled)
        m = m | new_valid
    return n_filled


def _box_blur_2d(img, radius):
    """Separable box blur via cumulative sum — O(N) per axis regardless
    of `radius`. Matches scipy.ndimage.uniform_filter for kernel size
    2*radius+1, but without the dependency.

    `img` shape (H, W, C). Edge-extends rather than zero-pads so the
    blur doesn't darken texture borders.
    """
    if radius <= 0:
        return img.copy()

    k = 2 * radius + 1

    pad = np.pad(img, ((0, 0), (radius + 1, radius), (0, 0)), mode='edge')
    csum = np.cumsum(pad, axis=1, dtype=np.float32)
    h_blurred = (csum[:, k:, :] - csum[:, :-k, :]) / k

    pad = np.pad(h_blurred, ((radius + 1, radius), (0, 0), (0, 0)), mode='edge')
    csum = np.cumsum(pad, axis=0, dtype=np.float32)
    blurred = (csum[k:, :, :] - csum[:-k, :, :]) / k

    return blurred



# ---------- Shader Templates ----------

def shader_white_diffuse(nodes, links, output_node):
    """Neutral surface used for AO bake.

    Cycles AO bake computes hemispheric occlusion *at* a surface point.
    Without a Surface link on the bake material, the object is treated as
    transparent — rays pass through without producing a shading point,
    AO integrates to zero, and the EXR comes out solid black. A simple
    white Diffuse gives Cycles a valid surface to bake AO at; the diffuse
    color isn't sampled by the AO pass itself, only its existence matters.
    """
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    links.new(diffuse.outputs["BSDF"], output_node.inputs["Surface"])


def shader_position(nodes, links, output_node):
    # Object-space position via Texture Coordinate, not world-space via
    # Geometry. `normalize_to_unit_cube` mutates the LOCAL mesh data to
    # [0,1]; Geometry.Position would re-introduce obj.matrix_world (any
    # rotation, scale, or location offset) and push channels out of range.
    # In particular, a flipping rotation (180° around Y or Z) puts world X
    # in [-1, 0], which reads as solid black on a Raw EXR viewer even
    # though the data is technically present.
    #
    # Emission rather than Principled BSDF for the same reason as before:
    # Principled.Base Color is internally clamped to [0,1] before
    # contributing to the diffuse pass. EMIT bake samples emission color
    # directly with no BSDF or color-pass interaction, so the [0,1]
    # object-space coords pass through unmodified into the float EXR and
    # the importer's Map Range nodes decode them back to world coords via
    # the bounds JSON.
    texcoord = nodes.new("ShaderNodeTexCoord")
    emission = nodes.new("ShaderNodeEmission")
    links.new(texcoord.outputs["Object"], emission.inputs["Color"])
    links.new(emission.outputs["Emission"], output_node.inputs["Surface"])


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

        # Push any Multires modifier on target/source to its render level
        # so the bake samples the fully-sculpted surface. Restored in the
        # finally below regardless of how the bake block exits.
        multires_snapshots = snapshot_multires(obj, source)

        try:
            prepare_bake_selection(obj)
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            if obj.type == 'MESH' and obj.data.uv_layers.active:
                bpy.ops.uv.export_layout(filepath=os.path.join(base_dir, f"{obj.name}_uv.png"), size=(resolution, resolution), opacity=1.0)
            bpy.ops.object.mode_set(mode='OBJECT')

            # Filenames mirror file_format='OPEN_EXR' set in bake_map /
            # bake_custom_map. Importer at sourceimporter.py:60 already
            # accepts both .png and .exr suffixes, so renaming is non-
            # breaking for existing source_maps folders that still hold
            # the old (mislabeled) .png files.
            bake_source = source if use_selected_to_active else None
            bake_map(obj, resolution, os.path.join(base_dir, f"{obj.name}_normal.exr"),
                     'NORMAL', 'TANGENT', bake_source)
            bake_map(obj, resolution, os.path.join(base_dir, f"{obj.name}_normal-obj.exr"),
                     'NORMAL', 'OBJECT', bake_source)
            bake_map(obj, resolution, os.path.join(base_dir, f"{obj.name}_ao.exr"),
                     'AO', 'TANGENT', bake_source)

            # Position pipeline: curvature later combines derivatives of
            # object-space normal with derivatives of position. In
            # selected-to-active mode the normal bake samples the source
            # (highpoly) surface, so the position bake must sample that
            # SAME surface or curvature mixes N from one shape with P from
            # another. To keep the emitted position in [0,1], temporarily
            # normalize both receiver and source into a shared unit cube
            # defined by the sampled surface's bounds.
            #
            # Single-object mode:
            #   - normalize target only, bake target position.
            # Selected-to-active mode:
            #   - compute bounds from source
            #   - normalize BOTH target and source with those same bounds
            #   - bake selected-to-active position from source -> target
            #   - decode later with the same source bounds JSON
            bounds_obj = bake_source if bake_source else obj
            min_bound, max_bound = compute_local_bounds(bounds_obj)
            try:
                normalize_to_bounds(obj, min_bound, max_bound)
                if bake_source and bake_source != obj:
                    normalize_to_bounds(bake_source, min_bound, max_bound)
                bake_custom_map(
                    obj, resolution,
                    os.path.join(base_dir, f"{obj.name}_position.exr"),
                    shader_position, source=bake_source, grayscale=False,
                    bake_type='EMIT',
                )
            finally:
                unnormalize_from_bounds(obj, min_bound, max_bound)
                if bake_source and bake_source != obj:
                    unnormalize_from_bounds(bake_source, min_bound, max_bound)
            bounds_data = {
                "min": list(min_bound),
                "max": list(max_bound)
            }
            with open(os.path.join(base_dir, f"{obj.name}_position_bounds.json"), 'w') as f:
                json.dump(bounds_data, f, indent=4)

            # Curvature bakes from geometry directly. This has been more
            # promising than the texel-differential post-process for clean
            # hard-surface and sculpted forms.
            bake_curvature_from_geometry(
                obj,
                resolution,
                os.path.join(base_dir, f"{obj.name}_curvature.exr"),
                source=bake_source,
                contrast=scene.aether_curvature_contrast,
                hard_weight=scene.aether_curvature_hard_weight,
                soft_radius=scene.aether_curvature_soft_radius,
            )
            
            bpy.context.scene.render.engine = 'BLENDER_EEVEE'
            bpy.context.scene.view_layers["ViewLayer"].use = False

        finally:
            restore_multires(multires_snapshots)
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

        curvature_box = layout.box()
        curvature_box.label(text="Curvature", icon='SCULPTMODE_HLT')
        curvature_box.prop(scene, "aether_curvature_contrast", slider=True)
        curvature_box.prop(scene, "aether_curvature_hard_weight", slider=True)
        curvature_box.prop(scene, "aether_curvature_soft_radius", slider=True)
        if scene.aether_use_highpoly:
            projection_box = layout.box()
            projection_box.label(text="Projection", icon='MOD_SHRINKWRAP')
            projection_box.prop(scene, "aether_bake_cage_extrusion_scale", slider=True)
            projection_box.prop(scene, "aether_bake_max_ray_distance_scale", slider=True)

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
    # Overall sensitivity multiplier on the curvature derivation. The
    # base coefficient inside derive_curvature_from_source_maps multiplies
    # against the AABB-diagonal-normalized κ, so contrast=1.0 sits in a
    # "balanced" zone independent of model scale; below 1 softens, above
    # 1 pushes mid-grey toward black/white edges. Soft cap at 4 to
    # discourage the blown-out look — hard cap at 8 for users who really
    # want it.
    bpy.types.Scene.aether_curvature_contrast = bpy.props.FloatProperty(
        name="Contrast",
        description=(
            "Curvature intensity multiplier. 1.0 is the calibrated "
            "default; higher pushes ridges/creases harder."
        ),
        min=0.0, soft_max=4.0, max=8.0,
        default=2.0,
    )
    # Mix between the unblurred (sharp) and blurred (cavity) curvature
    # passes. 1.0 = pure edge highlights, 0.0 = pure broad cavity shading,
    # 0.65 default leans on edges but keeps enough cavity to read as a
    # texture-paint mask.
    bpy.types.Scene.aether_curvature_hard_weight = bpy.props.FloatProperty(
        name="Edge / Cavity",
        description=(
            "Balance between sharp edge highlights and broad cavity "
            "shading. 1.0 = only sharp edges, 0.0 = only cavity."
        ),
        min=0.0, max=1.0,
        default=0.65,
    )
    # Box-blur radius in pixels for the soft pass. Larger values catch
    # broader concavities at the cost of bleeding across nearby UV
    # islands. Small numbers (2-8) suit ~2K bakes; bump higher only on
    # 4K+ where 4 px is barely a pixel of real surface.
    bpy.types.Scene.aether_curvature_soft_radius = bpy.props.IntProperty(
        name="Cavity Radius",
        description=(
            "Pixel radius of the soft (cavity) curvature pass. Larger = "
            "broader, smoother cavity shading. Set to 0 to disable the "
            "soft pass entirely."
        ),
        min=0, soft_max=16, max=64,
        default=4,
    )
    bpy.types.Scene.aether_bake_cage_extrusion_scale = bpy.props.FloatProperty(
        name="Cage Extrusion Scale",
        description=(
            "Selected-to-active ray start offset as a fraction of the "
            "combined source/target bounds diagonal."
        ),
        min=0.0, soft_max=0.02, max=0.25,
        default=0.0025,
    )
    bpy.types.Scene.aether_bake_max_ray_distance_scale = bpy.props.FloatProperty(
        name="Ray Distance Scale",
        description=(
            "Selected-to-active maximum ray distance as a fraction of the "
            "combined source/target bounds diagonal. Lower values reduce "
            "projection bleed into unrelated outer surfaces."
        ),
        min=0.0, soft_max=0.05, max=1.0,
        default=0.01,
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
    del bpy.types.Scene.aether_curvature_hard_weight
    del bpy.types.Scene.aether_curvature_soft_radius
    del bpy.types.Scene.aether_bake_cage_extrusion_scale
    del bpy.types.Scene.aether_bake_max_ray_distance_scale

if __name__ == "__main__":
    register()
