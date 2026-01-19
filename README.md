# crown_visualizer
Plugin for QGIS to generate realisitic crown diameters

<img width="460" height="240" alt="{744B5149-2673-4A58-B6CB-71703AC7A9B1}" src="https://github.com/user-attachments/assets/8657b8ae-5ac4-4d3a-a873-843cc64e55f5" />


Purpose:
This QGIS plugin generates realistic crown polygons based on directional crown diameters stored in tree point data.

How It Works:
Select the input point layer

The layer must contain trees with known crown radii in 4 directions: North, East, South, West.

Select the diameter fields

Default field names: crown_radius_1 to crown_radius_4

You can change them if your layer uses different field names.

Choose the target coordinate system (CRS)

Must be a projected CRS with meters as units (e.g. EPSG:25832).

If a geographic CRS (like EPSG:4326) is selected, the plugin will warn you.

(Optional) Select features

If you select features in the map canvas, only those will be processed.

If no features are selected, all features in the layer are processed.

Run the tool

The plugin creates a new temporary layer called "Crown" with the resulting crown polygons.

Each crown polygon is smoothed using cosine interpolation between the four directional radii.

Output:

A memory layer named Crown

Contains one polygon per tree

Geometry is calculated based on the four directional crown radii
