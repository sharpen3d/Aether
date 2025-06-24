import bpy
import os

SOURCE_BLEND_FILE = os.path.join(os.path.dirname(__file__), "aether_source_content.blend")

def append_node_group(group_name):
    with bpy.data.libraries.load(SOURCE_BLEND_FILE, link=False) as (data_from, data_to):
        if group_name in data_from.node_groups:
            data_to.node_groups.append(group_name)

def ensure_node_group(group_name):
    if group_name not in bpy.data.node_groups:
        append_node_group(group_name)
        
def append_material(material_name):
    with bpy.data.libraries.load(SOURCE_BLEND_FILE, link=False) as (data_from, data_to):
        if material_name in data_from.materials:
            data_to.materials.append(material_name)

def ensure_material(material_name):
    if material_name not in bpy.data.materials:
        append_material(material_name)

def append_workspace(workspace_name):
    with bpy.data.libraries.load(SOURCE_BLEND_FILE, link=False) as (data_from, data_to):
        if workspace_name in data_from.workspaces:
            data_to.workspaces.append(workspace_name)

def ensure_workspace(workspace_name):
    if workspace_name not in bpy.data.workspaces:
        append_workspace(workspace_name)
        
def register():
    pass


def unregister():
    pass