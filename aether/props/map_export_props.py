# props/map_export_props.py
# Author: Luke Stilson / sharpen3d

import bpy
from bpy.types import PropertyGroup


class MapExportSettings(PropertyGroup):
    source_object: bpy.props.PointerProperty(
        name="Target Object",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'MESH'
    )

    detail_object: bpy.props.PointerProperty(
        name="Highpoly Object",
        type=bpy.types.Object,
        poll=lambda self, obj: obj.type == 'MESH'
    )

    def get_uv_map_items(self, context):
        obj = self.source_object
        if not obj or obj.type != 'MESH' or not obj.data.uv_layers:
            return [("NONE", "No UVs", "")]
        return [(uv.name, uv.name, "") for uv in obj.data.uv_layers]

    uv_map: bpy.props.EnumProperty(
        name="UV Map",
        items=get_uv_map_items
    )


class MapExportItem(PropertyGroup):
    map_type: bpy.props.EnumProperty(
        name="Map Type",
        description="Type of map to export",
        items=[
            ('BASECOLOR', "Base Color", ""),
            ('NORMAL', "Normal", ""),
            ('ROUGHNESS', "Roughness", ""),
            ('METALLIC', "Metallic", ""),
            ('AO', "Ambient Occlusion", ""),
            ('OPACITY', "Opacity", ""),
            ('CUSTOM', "Custom", ""),
        ],
        default='BASECOLOR',
    )

    color_space: bpy.props.EnumProperty(
        name="Color Space",
        items=[
            ('SRGB', "sRGB", ""),
            ('LINEAR', "Linear", ""),
        ],
        default='SRGB',
    )

    channel_format: bpy.props.EnumProperty(
        name="Channel Format",
        items=[
            ('R', "Grayscale (R)", ""),
            ('RGB', "RGB", ""),
            ('RGBA', "RGBA", ""),
        ],
        default='RGB',
    )

    bit_depth: bpy.props.EnumProperty(
        name="Bit Depth",
        description="Bit depth per channel",
        items=[
            ('8', "8-bit", ""),
            ('16', "16-bit", ""),
            ('32', "32-bit (float)", ""),
        ],
        default='8',
    )

    map_name: bpy.props.StringProperty(
        name="Map Output Name",
        description="Custom name for this output",
        default="BaseColor",
    )


def register():
    bpy.utils.register_class(MapExportItem)
    bpy.utils.register_class(MapExportSettings)

    bpy.types.Scene.export_map_list = bpy.props.CollectionProperty(type=MapExportItem)
    bpy.types.Scene.export_map_index = bpy.props.IntProperty()
    bpy.types.Scene.export_settings = bpy.props.PointerProperty(type=MapExportSettings)
    bpy.types.Scene.custom_object_name = bpy.props.StringProperty(name="Object Name", default="MyObject")
    bpy.types.Scene.delimiter = bpy.props.StringProperty(name="Delimiter", default="_")
    bpy.types.Scene.export_output_directory = bpy.props.StringProperty(
        name="Output Directory",
        subtype='DIR_PATH',
        default="//exports/"
    )

    bpy.types.Scene.aether_preview_resolution_percentage = bpy.props.IntProperty(
        name="Preview Resolution",
        description=(
            "Resolution percentage used by the fast EEVEE preview render. "
            "Lower values update faster."
        ),
        default=50, min=10, soft_max=100, max=100,
        subtype='PERCENTAGE',
    )
    bpy.types.Scene.aether_inpaint_distance = bpy.props.IntProperty(
        name="Inpaint Distance",
        description=(
            "Pixel distance for the compositor inpaint pass on the standard "
            "render path. Large values are much slower; 8-16 is usually enough."
        ),
        default=16, min=0, soft_max=32, max=256,
    )
    bpy.types.Scene.aether_preview_mode = bpy.props.EnumProperty(
        name="Preview Mode",
        description="Whether fast preview renders only the active AOV or all maps into the full preview material",
        items=[
            ('ACTIVE_MAP', "Active Map", ""),
            ('ALL_MAPS', "All Maps", ""),
        ],
        default='ACTIVE_MAP',
    )
    bpy.types.Scene.aether_auto_preview_enabled = bpy.props.BoolProperty(
        name="Auto Preview",
        description=(
            "Automatically refresh fast preview after scene changes. "
            "Uses a guarded deferred update to avoid recursive refresh loops."
        ),
        default=False,
    )
    bpy.types.Scene.aether_auto_preview_delay = bpy.props.FloatProperty(
        name="Auto Preview Delay",
        description=(
            "Seconds to wait after the last edit before launching auto preview. "
            "Longer delays reduce workspace hitching while editing."
        ),
        default=0.75, min=0.05, soft_max=2.0, max=10.0,
        subtype='TIME',
    )


def unregister():
    del bpy.types.Scene.aether_auto_preview_delay
    del bpy.types.Scene.aether_auto_preview_enabled
    del bpy.types.Scene.aether_preview_mode
    del bpy.types.Scene.aether_inpaint_distance
    del bpy.types.Scene.aether_preview_resolution_percentage
    del bpy.types.Scene.export_output_directory
    del bpy.types.Scene.delimiter
    del bpy.types.Scene.custom_object_name
    del bpy.types.Scene.export_settings
    del bpy.types.Scene.export_map_index
    del bpy.types.Scene.export_map_list

    bpy.utils.unregister_class(MapExportSettings)
    bpy.utils.unregister_class(MapExportItem)
