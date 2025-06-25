# Aether

Aether is a Blender add-on focused on streamlined PBR material authoring. It bundles tools for baking texture maps, converting materials and quickly setting up scenes for texture export.

## Features

- **Scene setup tools** to create dedicated bake scenes with linked objects and optimized render settings.
- **Map export pipeline** for configuring and rendering multiple texture maps in one click.
- **Material builder** that automatically assigns rendered maps to an Aether material and links shader outputs.
- **Geometry node utilities** including triplanar setups and projection conversion helpers.
- **Source map baking** for generating normal, AO, curvature and position maps from high resolution meshes.
- **Material conversion** utilities for converting between standard Principled materials and the Aether shader.

## Installation

1. Download the latest `aether-vX.Y.Z.zip` from the repository root or from a release.
   Older versions can be found in the `Builds` directory.
2. In Blender, open **Edit → Preferences → Add-ons**.
3. Choose **Install…** and select the downloaded zip file.
4. Enable the **Aether** add-on in the list.

After installing, new panels named **Scene Setup** and **Texture Output** will appear in the 3D View sidebar under the **Aether** tab.

## Usage

1. Select a target mesh and open the **Scene Setup** panel.
2. Use *Create Aether Scene* to generate a bake scene with the correct render settings.
3. Configure export maps in the **Texture Output** panel and click *Render All Maps*.
4. The add-on will render each map and assign them to a material named `<ObjectName>.stxmat`.

Additional utilities such as adding seamless layers, baking source maps or converting materials can be found in the same sidebar menus and the node editor.

## Development

This repository contains the source code for the add-on. The packaged zip in the repository root mirrors the contents of the `aether/` directory.

## License

Aether is provided under the terms of the **GNU General Public License v3.0 or later** as stated in `blender_manifest.toml`.

## Maintainer

Luke Stilson (<stilson.luke@gmail.com>)
