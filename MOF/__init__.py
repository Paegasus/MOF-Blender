# Blender MOF Wrapper for UV Unwrapper - Copyright (C) 2025 Ultikynnys
#
# This file is part of Blender MOF Wrapper for UV Unwrapper.
#
# Blender MOF Wrapper for UV Unwrapper is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3
#
# Blender MOF Wrapper for UV Unwrapper is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Blender MOF Wrapper for UV Unwrapper.  If not, see <https://www.gnu.org/licenses/>.

import bpy, os, subprocess, tempfile, shutil, re
import mathutils
import bmesh
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty, PointerProperty, EnumProperty
from bpy.types import Operator, Panel, AddonPreferences, PropertyGroup

# Global variable to store the last target UV‐map name
last_target_uv_map = ""

bl_info = {
    "name": "Blender Wrapper for MOF UV Unwrapper",
    "blender": (4, 4, 0),
    "category": "UV",
    "version": (1, 0, 3),
    "author": "Ultikynnys",
    "description": "Wrapper that makes the MOF Unwrapper work in Blender",
    "tracker_url": "https://github.com/Ultikynnys/MinistryOfBlender",
}

# -------------------------------------------------------------------
# EnumProperty for UV map selection
# -------------------------------------------------------------------

def uv_map_items(self, context):
    # 1) a “none” entry with a valid ID
    items = [
        ('NONE', 'Select UV Map…', 'No UV map selected yet'),
    ]
    obj = context.selected_objects[0] if context.selected_objects else None

    # 2) gather any real UV names
    uv_names = []
    if obj and obj.type == 'MESH':
        uv_names = [uv.name for uv in obj.data.uv_layers]

    # 3) if the stored value is something other than "NONE" but it no longer exists,
    #    show it as “Missing” — but never for "NONE" itself.
    current = getattr(self, 'target_uv_map', 'NONE')
    if current != 'NONE' and current not in uv_names:
        items.append(
            (current,
             f"{current} (Missing)",
             "Previously selected UV map is no longer on this mesh")
        )

    # 4) append all the real ones
    items.extend((name, name, "") for name in uv_names)
    return items

# -------------------------------------------------------------------
# Property Group for operator parameters
# -------------------------------------------------------------------
class MOFProperties(PropertyGroup):
    """
    PropertyGroup that holds all the parameters for the MOF UV Unwrapper.

    Each property corresponds to a parameter used by the external UV unwrapping tool.
    All integer and float properties are clamped with a minimum value of 0.
    """
    resolution: IntProperty(
        name="Texture Resolution", 
        default=1024, 
        min=0,
        description="Set the texture resolution (in pixels) for the UV unwrap"
    )

    separate_hard_edges: BoolProperty(
        name="Separate Hard Edges",
        default=False,
        description="Split edges that are both marked as seam and set as hard (non-smooth)"
    )
    separate_marked_edges: BoolProperty(
        name="Separate Marked Edges",
        default=False,
        description="Split the mesh along all marked (seam) edges regardless of sharpness"
    )
    aspect: FloatProperty(
        name="Aspect", 
        default=1.0, 
        min=0.0,
        description="Set the aspect ratio used in the UV unwrapping process"
    )
    use_normals: BoolProperty(
        name="Use Normals", 
        default=False,
        description="Enable the use of vertex normals during UV calculation"
    )
    udims: IntProperty(
        name="UDIMs", 
        default=1, 
        min=0,
        description="Number of UDIM tiles to generate for the UV layout"
    )
    overlap_identical: BoolProperty(
        name="Overlap Identical Parts", 
        default=False,
        description="Allow identical mesh parts to overlap in the UV space"
    )
    overlap_mirrored: BoolProperty(
        name="Overlap Mirrored Parts", 
        default=False,
        description="Allow mirrored mesh parts to overlap in the UV space"
    )
    world_scale: BoolProperty(
        name="World Scale UV", 
        default=False,
        description="Apply the world scale to the UV coordinates"
    )
    texture_density: IntProperty(
        name="Texture Density", 
        default=1024, 
        min=0,
        description="Define the density (pixels per unit) for texturing"
    )
    seam_x: FloatProperty(
        name="Seam X", 
        default=0.0, 
        min=0.0,
        description="Offset the seam in the X direction"
    )
    seam_y: FloatProperty(
        name="Seam Y", 
        default=0.0, 
        min=0.0,
        description="Offset the seam in the Y direction"
    )
    seam_z: FloatProperty(
        name="Seam Z", 
        default=0.0, 
        min=0.0,
        description="Offset the seam in the Z direction"
    )
    suppress_validation: BoolProperty(
        name="Suppress Validation", 
        default=False,
        description="Disable validation checks in the external tool"
    )
    quads: BoolProperty(
        name="Quads", 
        default=True,
        description="Prefer quad faces in the UV unwrap for better topology"
    )
    flat_soft_surface: BoolProperty(
        name="Flat Soft Surface", 
        default=True,
        description="Flatten soft surfaces for improved UV layout"
    )
    cones: BoolProperty(
        name="Cones", 
        default=True,
        description="Enable cone calculations for shading correction"
    )
    cone_ratio: FloatProperty(
        name="Cone Ratio", 
        default=0.5, 
        min=0.0,
        description="Set the ratio used for cone calculations"
    )
    grids: BoolProperty(
        name="Grids", 
        default=True,
        description="Enable grid processing for the UV layout"
    )
    strips: BoolProperty(
        name="Strips", 
        default=True,
        description="Enable strip processing for more efficient UV packing"
    )
    patches: BoolProperty(
        name="Patches", 
        default=True,
        description="Use patch-based processing in the UV layout"
    )
    planes: BoolProperty(
        name="Planes", 
        default=True,
        description="Enable detection of planar regions for the UV unwrap"
    )
    flatness: FloatProperty(
        name="Flatness", 
        default=0.9, 
        min=0.0,
        description="Threshold for determining flatness during UV flattening"
    )
    merge: BoolProperty(
        name="Merge", 
        default=True,
        description="Merge similar UV islands after unwrapping"
    )
    merge_limit: FloatProperty(
        name="Merge Limit", 
        default=0.0, 
        min=0.0,
        description="Set the distance threshold for merging UV islands"
    )
    pre_smooth: BoolProperty(
        name="Pre-Smooth", 
        default=True,
        description="Smooth the mesh before unwrapping to improve UV results"
    )
    soft_unfold: BoolProperty(
        name="Soft Unfold", 
        default=True,
        description="Apply a soft unfolding algorithm to reduce distortions"
    )
    tubes: BoolProperty(
        name="Tubes", 
        default=True,
        description="Enable tube-like processing for cylindrical mesh parts"
    )
    junctions: BoolProperty(
        name="Junctions", 
        default=True,
        description="Detect and process junctions in the mesh during unwrapping"
    )
    extra_debug: BoolProperty(
        name="Extra Debug Point", 
        default=False,
        description="Enable extra debugging information for troubleshooting"
    )
    angle_based_flattening: BoolProperty(
        name="Angle-based Flattening", 
        default=True,
        description="Use angle-based flattening for a more natural UV layout"
    )
    smooth: BoolProperty(
        name="Smooth", 
        default=True,
        description="Apply smoothing to the final UV layout"
    )
    repair_smooth: BoolProperty(
        name="Repair Smooth", 
        default=True,
        description="Smooth out repair areas in the UV layout for better transitions"
    )
    repair: BoolProperty(
        name="Repair", 
        default=True,
        description="Perform repair operations on the UV layout to fix errors"
    )
    squares: BoolProperty(
        name="Squares", 
        default=True,
        description="Enforce square UV islands where possible"
    )
    relax: BoolProperty(
        name="Relax", 
        default=True,
        description="Relax the UV islands to reduce texture stretching"
    )
    relax_iterations: IntProperty(
        name="Relax Iterations", 
        default=50, 
        min=0,
        description="Number of iterations to run during the UV relaxation process"
    )
    expand: FloatProperty(
        name="Expand", 
        default=0.25, 
        min=0.0,
        description="Factor by which to expand the UV islands before packing"
    )
    cut: BoolProperty(
        name="Cut", 
        default=True,
        description="Enable cutting in the UV layout to separate islands"
    )
    stretch: BoolProperty(
        name="Stretch", 
        default=True,
        description="Allow UV islands to stretch to better fill the UV space"
    )
    match: BoolProperty(
        name="Match", 
        default=True,
        description="Match adjacent UV islands to minimize seams"
    )
    packing: BoolProperty(
        name="Packing", 
        default=True,
        description="Enable packing of UV islands into the texture space"
    )
    rasterization: IntProperty(
        name="Rasterization Resolution", 
        default=64, 
        min=0,
        description="Resolution for rasterizing UV islands during packing"
    )
    packing_iterations: IntProperty(
        name="Packing Iterations", 
        default=4, 
        min=0,
        description="Number of iterations to optimize the packing of UV islands"
    )
    scale_to_fit: FloatProperty(
        name="Scale To Fit", 
        default=0.5, 
        min=0.0,
        description="Scale factor to fit the UV islands within the texture space"
    )
    validate: BoolProperty(
        name="Validate", 
        default=False,
        description="Run validation on the final UV layout for errors"
    )
    uv_margin: FloatProperty(
        name="UV Margin", 
        default=0.1, 
        min=0.0,
        description="Margin between UV islands in the texture space"
    )
    pixel_padding: IntProperty(
        name="Pixel Padding", 
        default=2, 
        min=0,
        description="Padding in pixels applied during UV tile scaling"
    )

    target_uv_map: StringProperty(
        name="Target UV Map",
        description="Name of the UV map to write the unwrapped UVs into",
        default=""
    )

# -------------------------------------------------------------------
# Addon Preferences with version check operator
# -------------------------------------------------------------------

class MOFAddonPreferences(AddonPreferences):
    """
    Addon preferences for the Blender Wrapper for MOF UV Unwrapper.

    This class allows the user to set the path to MinistryOfFlat
    and displays the current version extracted from the documentation.txt file.
    """
    bl_idname = __package__

    mof_path: StringProperty(
        name="MinistryOfFlat Path",
        subtype='DIR_PATH',
        default="",
        description="Path to the MinistryOfFlat directory"
    )

    version: StringProperty(
        name="Version",
        default="unknown",
        description="MinistryOfFlat version"
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mof_path")
        row = layout.row(align=True)
        row.label(text=f"MinistryOFlat Version: {self.version}")
        row.operator("wm.checkmofversion", text="Check Version")
        if not self.mof_path or not os.path.exists(bpy.path.abspath(self.mof_path)):
            layout.label(text="Please download MinistryOfFlat from the official site.", icon='INFO')

# -------------------------------------------------------------------
# Operator to check/extract the version of MinistryOfFlat
# -------------------------------------------------------------------
class CheckMOFVersionOperator(Operator):
    """
    Operator that checks the version of MinistryOfFlat.
    """
    bl_idname = "wm.checkmofversion"
    bl_label = "Check MinistryOfFlat Version"

    def execute(self, context):
        prefs = context.preferences.addons[__package__].preferences
        mof_path = bpy.path.abspath(prefs.mof_path)
        doc_file_path = os.path.join(mof_path, "documentation.txt")
        
        if not os.path.isfile(doc_file_path):
            self.report({'ERROR'}, f"documentation.txt not found at {doc_file_path}")
            prefs.version = "unknown"
            return {'CANCELLED'}

        try:
            with open(doc_file_path, "rb") as doc_file:
                content = doc_file.read().decode("utf-8")
                match = re.search(r"[Vv]ersion[:\s]+([\d]+\.[\d]+(?:\.[\d]+)?)", content)
                if match:
                    prefs.version = match.group(1)
                    self.report({'INFO'}, f"Version found: {prefs.version}")
                else:
                    prefs.version = "unknown"
                    self.report({'WARNING'}, "Version string not found in documentation.txt")
        except Exception as e:
            self.report({'ERROR'}, f"Failed to read documentation.txt: {e}")
            prefs.version = "unknown"
            return {'CANCELLED'}

        return {'FINISHED'}

# -------------------------------------------------------------------
# Operator to perform auto UV unwrapping via external tool
# -------------------------------------------------------------------
class AutoUVOperator(Operator):
    bl_idname = "object.auto_uv_operator"
    bl_label = "Auto UV Unwrap"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        # 1) must have exactly one mesh selected...
        objs = [o for o in context.selected_objects if o.type == 'MESH']
        if len(objs) != 1:
            return False
        obj = objs[0]

        # 2) that mesh must have at least one UV layer
        if not obj.data.uv_layers:
            return False

        # 3) and a valid UV name must be chosen (i.e. not our 'NONE' placeholder)
        props = context.scene.mof_properties
        sel = context.scene.mof_properties.target_uv_map
        valid_uvs = [uv.name for uv in obj.data.uv_layers]
        if sel not in valid_uvs:
            return False

        # 4) finally make sure the MinistryOfFlat path contains the console executable
        prefs = context.preferences.addons[__package__].preferences
        mof_path = bpy.path.abspath(prefs.mof_path)
        exe = os.path.join(mof_path, "UnWrapConsole3.exe")
        if os.path.isfile(exe):
            return True
        else:
            self.report({'ERROR'}, f"Executable not found: {exe}")
            return False

    def execute(self, context):
        global last_target_uv_map
        last_target_uv_map = context.scene.mof_properties.target_uv_map

        # Store the previous mode (default to 'OBJECT' if no active object)
        previous_mode = context.active_object.mode if context.active_object else 'OBJECT'
        bpy.ops.object.mode_set(mode='OBJECT')

        # Process only if exactly one mesh object is selected.
        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
        if len(selected_objs) != 1:
            self.report({'ERROR'}, "Please select exactly one mesh object")
            return {"CANCELLED"}
        original_obj = selected_objs[0]

        # Set the path to the MoF executable
        
        prefs = context.preferences.addons[__package__].preferences
        mof_path = bpy.path.abspath(prefs.mof_path)
        exe = os.path.join(mof_path, "UnWrapConsole3.exe")
        if not os.path.isfile(exe):
            self.report({'ERROR'}, f"Executable not found: {exe}")
            return {'CANCELLED'}

        # Create a temporary copy of the object for processing.
        orig_matrix = original_obj.matrix_world.copy()
        temp_name = original_obj.name + "_temp"
        if temp_name in bpy.data.objects:
            bpy.data.objects.remove(bpy.data.objects[temp_name], do_unlink=True)
        temp_obj = original_obj.copy()
        temp_obj.data = original_obj.data.copy()
        temp_obj.name = temp_name
        context.collection.objects.link(temp_obj)
        # Reset matrices to Identity.
        original_obj.matrix_world = mathutils.Matrix.Identity(4)
        temp_obj.matrix_world = mathutils.Matrix.Identity(4)

        props = context.scene.mof_properties

        # If there are seam edges, split them according to the chosen method.
        if any(edge.use_seam for edge in temp_obj.data.edges):
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.context.view_layer.update()  # Force update of the view layer
            bm = bmesh.from_edit_mesh(temp_obj.data)
            # If "Separate Marked Edges" is enabled, split all edges marked as seam.
            if props.separate_marked_edges:
                marked_edges = [edge for edge in bm.edges if edge.seam]
                if marked_edges:
                    bmesh.ops.split_edges(bm, edges=marked_edges)
                    bmesh.update_edit_mesh(temp_obj.data)
            # Else if "Separate Hard Edges" is enabled, split only those seam edges that are sharp.
            elif props.separate_hard_edges:
                hard_edges = [edge for edge in bm.edges if edge.seam and not edge.smooth]
                if hard_edges:
                    bmesh.ops.split_edges(bm, edges=hard_edges)
                    bmesh.update_edit_mesh(temp_obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')

        # Deselect all and select only the temporary object.
        for obj in context.selected_objects:
            obj.select_set(False)
        temp_obj.select_set(True)
        context.view_layer.objects.active = temp_obj

        # Export the temporary object as OBJ.
        temp_dir = bpy.app.tempdir
        name_safe = temp_obj.name.replace(" ", "_")
        in_path = os.path.join(temp_dir, f"{name_safe}.obj")
        out_path = os.path.join(temp_dir, f"{name_safe}_unwrapped.obj")
        try:
            bpy.ops.wm.obj_export(
                filepath=in_path,
                export_selected_objects=True,
                export_materials=False,
                forward_axis='Y',
                up_axis='Z'
            )
        except Exception as e:
            self.report({'ERROR'}, f"Export failed for {original_obj.name}: {e}")
            bpy.app.timers.register(lambda: remove_temp(temp_obj), first_interval=1.0)
            return {"CANCELLED"}

        bpy.app.timers.register(lambda: remove_temp(temp_obj), first_interval=1.0)

        # Build the command list with parameters.
        p = context.scene.mof_properties
        cmd = [exe, in_path, out_path]
        params = [
            ("-RESOLUTION", str(p.resolution)),
            ("-SEPARATE", "TRUE" if p.separate_hard_edges else "FALSE"),
            ("-ASPECT", str(p.aspect)),
            ("-NORMALS", "TRUE" if p.use_normals else "FALSE"),
            ("-UDIMS", str(p.udims)),
            ("-OVERLAP", "TRUE" if p.overlap_identical else "FALSE"),
            ("-MIRROR", "TRUE" if p.overlap_mirrored else "FALSE"),
            ("-WORLDSCALE", "TRUE" if p.world_scale else "FALSE"),
            ("-DENSITY", str(p.texture_density)),
            ("-CENTER", str(p.seam_x), str(p.seam_y), str(p.seam_z)),
            ("-SUPRESS", "TRUE" if p.suppress_validation else "FALSE"),
            ("-QUAD", "TRUE" if p.quads else "FALSE"),
            ("-WELD", "FALSE"),  # Must be false always otherwise we can't use seams
            ("-FLAT", "TRUE" if p.flat_soft_surface else "FALSE"),
            ("-CONE", "TRUE" if p.cones else "FALSE"),
            ("-CONERATIO", str(p.cone_ratio)),
            ("-GRIDS", "TRUE" if p.grids else "FALSE"),
            ("-STRIP", "TRUE" if p.strips else "FALSE"),
            ("-PATCH", "TRUE" if p.patches else "FALSE"),
            ("-PLANES", "TRUE" if p.planes else "FALSE"),
            ("-FLATT", str(p.flatness)),
            ("-MERGE", "TRUE" if p.merge else "FALSE"),
            ("-MERGELIMIT", str(p.merge_limit)),
            ("-PRESMOOTH", "TRUE" if p.pre_smooth else "FALSE"),
            ("-SOFTUNFOLD", "TRUE" if p.soft_unfold else "FALSE"),
            ("-TUBES", "TRUE" if p.tubes else "FALSE"),
            ("-JUNCTIONSDEBUG", "TRUE" if p.junctions else "FALSE"),
            ("-EXTRADEBUG", "TRUE" if p.extra_debug else "FALSE"),
            ("-ABF", "TRUE" if p.angle_based_flattening else "FALSE"),
            ("-SMOOTH", "TRUE" if p.smooth else "FALSE"),
            ("-REPAIRSMOOTH", "TRUE" if p.repair_smooth else "FALSE"),
            ("-REPAIR", "TRUE" if p.repair else "FALSE"),
            ("-SQUARE", "TRUE" if p.squares else "FALSE"),
            ("-RELAX", "TRUE" if p.relax else "FALSE"),
            ("-RELAX_ITERATIONS", str(p.relax_iterations)),
            ("-EXPAND", str(p.expand)),
            ("-CUTDEBUG", "TRUE" if p.cut else "FALSE"),
            ("-STRETCH", "TRUE" if p.stretch else "FALSE"),
            ("-MATCH", "TRUE" if p.match else "FALSE"),
            ("-PACKING", "TRUE" if p.packing else "FALSE"),
            ("-RASTERIZATION", str(p.rasterization)),
            ("-PACKING_ITERATIONS", str(p.packing_iterations)),
            ("-SCALETOFIT", str(p.scale_to_fit)),
            ("-VALIDATE", "TRUE" if p.validate else "FALSE"),
        ]
        for tup in params:
            cmd.extend(tup)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                if not (os.path.exists(out_path) and os.path.getsize(out_path) > 0):
                    self.report({'ERROR'}, f"External tool failed on {original_obj.name} with exit code {result.returncode}")
                    return {"CANCELLED"}
        except Exception as e:
            self.report({'ERROR'}, f"Error running tool on {original_obj.name}: {e}")
            return {"CANCELLED"}
        try:
            bpy.ops.wm.obj_import(filepath=out_path, forward_axis='Y', up_axis='Z')
        except Exception as e:
            self.report({'ERROR'}, f"Import failed for {original_obj.name}: {e}")
            return {"CANCELLED"}

        # Transfer UVs from the imported object to the original object.
        imported_obj = context.active_object
        if imported_obj and imported_obj.type == 'MESH':
            imported_obj.name = original_obj.name + "_mof_Unwrapped"
            context.view_layer.objects.active = original_obj
            # ── 4) Rename imported UV and transfer into the target UV map ──
            # ensure the target UV map exists on the original
            if props.target_uv_map not in original_obj.data.uv_layers:
                self.report({'ERROR'}, f"UV map '{props.target_uv_map}' not found on {original_obj.name}")
                return {'CANCELLED'}
            original_obj.data.uv_layers.active = original_obj.data.uv_layers[props.target_uv_map]

            # rename the imported object's single UV layer to match
            if imported_obj.data.uv_layers:
                imported_obj.data.uv_layers[0].name = props.target_uv_map
            else:
                self.report({'ERROR'}, f"No UV maps found on imported mesh '{imported_obj.name}'")
                bpy.data.objects.remove(imported_obj, do_unlink=True)
                return {'CANCELLED'}

            # create & apply DataTransfer modifier, targeting that named layer
            dt_mod = original_obj.modifiers.new(name="DataTransfer", type='DATA_TRANSFER')
            dt_mod.object = imported_obj
            dt_mod.use_loop_data = True
            dt_mod.data_types_loops = {'UV'}
            dt_mod.loop_mapping = 'TOPOLOGY'
            dt_mod.layers_uv_select_src = 'ALL'
            dt_mod.layers_uv_select_dst = 'NAME'

            bpy.ops.object.mode_set(mode='OBJECT')
            print("Applying DataTransfer modifier")
            bpy.ops.object.modifier_apply(modifier=dt_mod.name)
            bpy.data.objects.remove(imported_obj, do_unlink=True)

            # Scale and center the UVs based on the pixel padding parameter.
            uv_layer = original_obj.data.uv_layers.active.data
            min_u, min_v = float('inf'), float('inf')
            max_u, max_v = float('-inf'), float('-inf')
            for loop in uv_layer:
                u, v = loop.uv.x, loop.uv.y
                if u < min_u: min_u = u
                if v < min_v: min_v = v
                if u > max_u: max_u = u
                if v > max_v: max_v = v
            range_u = max_u - min_u
            range_v = max_v - min_v
            if range_u > 0 and range_v > 0:
                padding = p.pixel_padding / p.resolution
                for loop in uv_layer:
                    loop.uv.x = padding + ((loop.uv.x - min_u) / range_u) * (1 - 2 * padding)
                    loop.uv.y = padding + ((loop.uv.y - min_v) / range_v) * (1 - 2 * padding)
        else:
            self.report({'WARNING'}, f"No valid imported mesh found for UV processing on {original_obj.name}")
        
        # Restore the original object's transform.
        original_obj.matrix_world = orig_matrix
        
        # Deselect all objects
        for obj in context.selected_objects:
            obj.select_set(False)
            
        # Select and activate the original object again
        original_obj.select_set(True)
        context.view_layer.objects.active = original_obj

        # Clean up temporary files.
        for fp in (in_path, out_path):
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except Exception:
                    pass

        self.report({'INFO'}, "UV Unwrapping complete for the selected mesh object")
        # Restore the previous mode before finishing.
        bpy.ops.object.mode_set(mode=previous_mode)
        return {"FINISHED"}


# Helper function to remove temporary objects.
def remove_temp(temp_obj):
    if temp_obj and temp_obj.name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[temp_obj.name], do_unlink=True)
    return None

# -------------------------------------------------------------------
# Main UI Panels
# -------------------------------------------------------------------
class MOFMOFPanel(Panel):
    """
    Main UI Panel for the MOF UV Unwrapper addon.

    Displays general settings and buttons for executing the auto UV unwrap.
    """
    bl_label = "MOF UV Unwrapper"
    bl_idname = "VIEW3D_PT_MOF_mof"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Blender MOF'
    
    def draw(self, context):
        layout = self.layout
        row = layout.row()
        row.operator("wm.url_open", text="Addon Creator", icon='HEART').url = "https://blendermarket.com/creators/ultikynnys"
        row.operator("wm.url_open", text="MOF Creator", icon='HEART').url = "https://www.quelsolaar.com/"
        layout.separator()
        props = context.scene.mof_properties
        
        prefs = context.preferences.addons[__package__].preferences
        if not prefs.mof_path:
            layout.label(text="MinistryOfFlat path not set", icon='ERROR')
            layout.label(text="Please download MinistryOfFlat from the official site.", icon='INFO')
            layout.prop(prefs, "mof_path")
        else:
            layout.label(text=f"MoF Version: {prefs.version}")
        
        if os.name != "nt":
            layout.label(text="UV Unwrapping is only available on Windows", icon='ERROR')
        else:
            box = layout.box()
            box.label(text="General Settings", icon='WORLD')
            for attr in ("resolution", "separate_hard_edges", "separate_marked_edges", "aspect",
                         "overlap_identical", "overlap_mirrored", "world_scale", "texture_density"):
                row = box.row()
                row.prop(props, attr)
            box.prop(props, "pixel_padding")
            
            if context.object and context.object.type == 'MESH':
                box.prop_search(
                    context.scene.mof_properties,
                    "target_uv_map",
                    context.object.data,
                    "uv_layers",
                    text="Target UV Map"
                )
            else:
                box.prop(context.scene.mof_properties, "target_uv_map", text="Target UV Map")


            layout.operator(AutoUVOperator.bl_idname, icon='MOD_UVPROJECT')
        

class MOFDebugPanel(Panel):
    """
    Debug UI Panel for advanced settings.

    This panel exposes debug and additional settings that control various
    aspects of the UV unwrapping algorithm. For further details, refer to the documentation
    contained in the MinistryOfFlat documentation.txt file.
    """
    bl_label = "MOF debug"
    bl_idname = "VIEW3D_PT_MOF_MOF_debug"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Blender MOF'
    
    def draw(self, context):
        layout = self.layout
        props = context.scene.mof_properties
        box = layout.box()
        box.label(text="Open the MinistryOfFlat path to see the documentation.txt for what these are for")
        box.label(text="Debug Settings", icon='ERROR')
        for attr in ("suppress_validation", "quads", "flat_soft_surface", "cones", "cone_ratio", "grids",
                     "strips", "patches", "planes", "flatness", "merge", "merge_limit", "pre_smooth", "soft_unfold", "tubes",
                     "junctions", "extra_debug", "angle_based_flattening", "smooth", "repair_smooth", "repair", "squares",
                     "relax", "relax_iterations", "expand", "cut", "stretch", "match", "packing", "rasterization",
                     "packing_iterations", "scale_to_fit", "validate", "uv_margin"):
            box.prop(props, attr)

classes = (
    CheckMOFVersionOperator,
    MOFProperties,
    MOFAddonPreferences,
    AutoUVOperator,
    MOFMOFPanel,
    MOFDebugPanel,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mof_properties = PointerProperty(type=MOFProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.mof_properties

if __name__ == "__main__":
    register()
