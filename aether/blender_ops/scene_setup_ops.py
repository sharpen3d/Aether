# blender_ops/scene_setup_ops.py
# Author: Luke Stilson / sharpen3d

import bpy
from bpy.types import Operator
from ..utils import append_content


class EXPORTMAP_OT_create_bake_scene(Operator):
    bl_idname = "exportmap.create_bake_scene"
    bl_label = "Create Bake Scene"
    bl_description = "Creates a new scene with linked objects, GN preview, camera, and render settings"

    def execute(self, context):
        src_obj = context.scene.export_settings.source_object
        if not src_obj or src_obj.type != 'MESH':
            self.report({'ERROR'}, "Target object must be a mesh")
            return {'CANCELLED'}

        original_scene = context.scene
        new_scene = bpy.data.scenes.new(original_scene.custom_object_name)
        context.window.scene = new_scene

        # Copy base render settings
        new_scene.render.engine = 'BLENDER_EEVEE_NEXT'
        new_scene.render.film_transparent = True
        new_scene.render.resolution_x = 2048
        new_scene.render.resolution_y = 2048
        new_scene.render.resolution_percentage = 100
        new_scene.render.image_settings.file_format = 'PNG'
        new_scene.render.image_settings.color_mode = 'RGBA'
        new_scene.render.image_settings.color_depth = '8'
        new_scene.render.image_settings.compression = 0
        new_scene.view_settings.view_transform = 'Standard'
        new_scene.display_settings.display_device = 'sRGB'
        new_scene.eevee.taa_render_samples = 1
        new_scene.eevee.taa_samples = 1

        # Transfer scene-level props
        new_scene.custom_object_name = original_scene.custom_object_name
        new_scene.export_settings.source_object = original_scene.export_settings.source_object
        new_scene.export_settings.uv_map = original_scene.export_settings.uv_map
        new_scene.export_map_index = original_scene.export_map_index

        # Copy export map list
        new_scene.export_map_list.clear()
        for item in original_scene.export_map_list:
            new_item = new_scene.export_map_list.add()
            for attr in ["map_type", "map_name", "color_space", "channel_format", "bit_depth"]:
                setattr(new_item, attr, getattr(item, attr))
        

        ## Temp
        def create_stx_variant(suffix, location, socket_4):
            obj = src_obj.copy()
            obj.data = src_obj.data
            obj.name = src_obj.name + suffix
            obj.location = location
            # Reset rotation (Euler angles in radians)
            obj.rotation_euler = (0.0, 0.0, 0.0)

            # Reset scale
            obj.scale = (1.0, 1.0, 1.0)
            new_scene.collection.objects.link(obj)

            append_content.ensure_node_group("stx_preview")

            mod = obj.modifiers.new(name="GeometryNodes", type='NODES')
            gn_group = bpy.data.node_groups.get("stx_preview")
            if not gn_group:
                self.report({'ERROR'}, "Node group 'stx_preview' not found")
                return None
            mod.node_group = gn_group
            try:
                mod["Socket_4"] = socket_4
            except:
                self.report({'WARNING'}, "'Socket_4' not found on Geometry Nodes input")
            return obj


        # Build default base plane
        '''
        mesh = bpy.data.meshes.new(new_scene.custom_object_name + "_baselayer")
        obj = bpy.data.objects.new(mesh.name, mesh)
        new_scene.collection.objects.link(obj)
        mesh.from_pydata(
            [(-0.5, -0.5, 0), (0.5, -0.5, 0), (0.5, 0.5, 0), (-0.5, 0.5, 0)],
            [], [(0, 1, 2, 3)]
        )
        obj.location = (0.5, 0.5, 0)
        '''
        
        # Assign aether_master material
        append_content.ensure_node_group("aether_master")
        mat = bpy.data.materials.new(new_scene.custom_object_name + "aether")
        mat.use_nodes = True
       # obj.data.materials.append(mat)

        tree = mat.node_tree
        tree.nodes.clear()
        output = tree.nodes.new("ShaderNodeOutputMaterial")
        output.location = (400, 0)

        group = bpy.data.node_groups.get("aether_master")
        if not group:
            self.report({'ERROR'}, "Node group 'aether_master' not found")
            return {'CANCELLED'}

        group_node = tree.nodes.new("ShaderNodeGroup")
        group_node.node_tree = group
        group_node.location = (0, 0)
        tree.links.new(group_node.outputs.get("Output"), output.inputs.get("Surface"))
        tree.links.new(group_node.outputs.get("Displacement"), output.inputs.get("Displacement"))

        # Create both object variants
        obj_uv = create_stx_variant(".stx_uv", (0, 0, 0), False)
        obj_preview = create_stx_variant(".stx_preview", (100, 100, 100), True)
        

        # Add camera
        cam_data = bpy.data.cameras.new("Bake_Camera")
        cam_data.type = 'ORTHO'
        cam_data.ortho_scale = 1.0
        cam_data.show_passepartout = True
        cam_data.passepartout_alpha = 1.0
        cam_obj = bpy.data.objects.new("Bake_Camera", cam_data)
        cam_obj.location = (0.5, 0.5, 10)
        new_scene.collection.objects.link(cam_obj)
        new_scene.camera = cam_obj
        
        append_content.ensure_workspace("Aether")
        switch_to_workspace("Aether")

        # Viewport configuration
        view_areas = [area for area in context.window.screen.areas if area.type == 'VIEW_3D']
        if len(view_areas) >= 2:
            cam_area = view_areas[1]
            preview_area = view_areas[0]

            # Left: camera view
            for space in cam_area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'MATERIAL'
                    space.region_3d.view_perspective = 'CAMERA'

            # Right: focus .stx_preview
            for space in preview_area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.type = 'MATERIAL'
                    space.region_3d.view_location = obj_preview.location
                    space.region_3d.view_distance = 10
                    space.region_3d.view_perspective = 'PERSP'
        

        #trigger_texture_context_safely()
        bpy.context.scene.export_output_directory = '//' + bpy.context.scene.custom_object_name + '/'
        setup_inpaint_compositor()
            
        self.report({'INFO'}, "Bake scene created")
        return {'FINISHED'}


def switch_to_workspace(workspace_name: str):
    for window in bpy.context.window_manager.windows:
        for workspace in bpy.data.workspaces:
            if workspace.name == workspace_name:
                window.workspace = workspace
                return
    raise ValueError(f"Workspace '{workspace_name}' not found.")


def setup_inpaint_compositor():
    scene = bpy.context.scene
    scene.use_nodes = True
    tree = scene.node_tree
    nodes = tree.nodes
    links = tree.links

    # Clear existing nodes
    nodes.clear()

    # Add nodes
    render_node = nodes.new('CompositorNodeRLayers')
    inpaint_node = nodes.new('CompositorNodeInpaint')
    composite_node = nodes.new('CompositorNodeComposite')

    # Position nodes
    render_node.location = (-300, 0)
    inpaint_node.location = (0, 0)
    composite_node.location = (300, 0)

    # Set inpaint distance to render resolution x
    inpaint_node.distance = scene.render.resolution_x

    # Create links
    links.new(render_node.outputs['Image'], inpaint_node.inputs['Image'])
    links.new(inpaint_node.outputs['Image'], composite_node.inputs['Image'])
    
def trigger_texture_context_safely():
    obj = bpy.context.active_object
    if not obj or obj.type != 'MESH':
        print("❌ No mesh object available to switch to Texture Paint mode.")
        return None

    prev_mode = obj.mode
    try:
        bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
        bpy.ops.object.mode_set(mode=prev_mode)
    except Exception as e:
        print("❌ Error entering Texture Paint:", e)
        return None

    bpy.app.timers.register(set_texture_tab_context, first_interval=0.1)
    return None


def set_texture_tab_context():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'PROPERTIES':
                for space in area.spaces:
                    if space.type == 'PROPERTIES':
                        if 'TEXTURE' in space.bl_rna.properties['context'].enum_items.keys():
                            space.context = 'TEXTURE'
                            print("✅ Texture tab activated")
    return None



def register():
    bpy.utils.register_class(EXPORTMAP_OT_create_bake_scene)
    #bpy.app.timers.register(trigger_texture_context_safely, first_interval=0.1)


def unregister():
    bpy.utils.unregister_class(EXPORTMAP_OT_create_bake_scene)
