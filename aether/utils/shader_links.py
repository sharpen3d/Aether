# utils/shader_links.py
# Author: Luke Stilson / sharpen3d

import bpy


def link_switcher_output(map_type: str) -> bool:
    """
    Connects the correct output from DMMT_Switcher to the Output socket of DMMT_Master.

    Returns True if successful, False otherwise.
    """
    master_tree = bpy.data.node_groups.get('DMMT_Master')
    if not master_tree:
        print("❌ DMMT_Master node group not found")
        return False

    switcher = next(
        (n for n in master_tree.nodes if n.type == 'GROUP' and n.node_tree and n.node_tree.name == 'DMMT_Switcher'),
        None
    )
    if not switcher:
        print("❌ DMMT_Switcher not found inside DMMT_Master")
        return False

    output_node = next((n for n in master_tree.nodes if n.type == 'GROUP_OUTPUT'), None)
    if not output_node:
        print("❌ Group Output not found in DMMT_Master")
        return False

    def normalize(name):
        return name.replace("_", "").replace(" ", "").lower()

    target_name = normalize(map_type)
    target_socket = next(
        (s for s in switcher.outputs if normalize(s.name) == target_name),
        None
    )
    if not target_socket:
        print(f"⚠️ No matching output socket for '{map_type}'")
        return False

    # Remove existing links to Output
    for link in list(master_tree.links):
        if link.to_node == output_node and link.to_socket.name == 'Output':
            master_tree.links.remove(link)

    master_tree.links.new(target_socket, output_node.inputs['Output'])
    print(f"✅ Linked DMMT_Switcher.{target_socket.name} to Output")
    return True


def register():
    pass


def unregister():
    pass
