bl_info = {
    "name": "Aether",
    "author": "Luke Stilson",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "description": "PBR Material Authoring",
    "category": "Material",
}

import importlib

# Direct file-level imports from each module
from . import props, blender_ops, utils, ui_panels

modules = [
    props.map_export_props,
    blender_ops.export_map_ops,
    blender_ops.render_ops,
    blender_ops.scene_setup_ops,
    blender_ops.object_add_ops,
    utils.shader_links,
    ui_panels.export_panel,
    ui_panels.texture_panel,
]

def register():
    for m in modules:
        importlib.reload(m)
        m.register()

def unregister():
    for m in reversed(modules):
        m.unregister()

if __name__ == "__main__":
    register()
