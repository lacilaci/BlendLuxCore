import bpy
import mathutils
from bpy.props import EnumProperty, PointerProperty, StringProperty, IntProperty
from ..base import LuxCoreNodeTexture
from ... import utils
from ...bin import pyluxcore
from ...utils import node as utils_node
from ...ui import icons
from ...utils.errorlog import LuxCoreErrorLog



class LuxCoreNodeTexOpenVDB(bpy.types.Node, LuxCoreNodeTexture):
    bl_label = "OpenVDB File"
    bl_width_default = 200

    def update_file_path(self, context):
        names = []
        if self.file_path != "":
            self.outputs.clear()
            pyluxcore.GetOpenVDBGridNames(bpy.path.abspath(self.file_path), names)
            for n in names:
                bbox, gridtype = pyluxcore.GetOpenVDBGridInfo(bpy.path.abspath(self.file_path), n)
                if gridtype == "float":
                    self.outputs.new("LuxCoreSocketFloatPositive", n)
                else:
                    self.outputs.new("LuxCoreSocketColor", n)

                self.nx = abs(bbox[0][0]-bbox[1][0])
                self.ny = abs(bbox[0][1]-bbox[1][1])
                self.nz = abs(bbox[0][2]-bbox[1][2])


    domain: PointerProperty(name="Domain", type=bpy.types.Object)

    def update_source(self, context):
        value_output = self.outputs["Value"]
        color_output = self.outputs["Color"]
        was_value_enabled = value_output.enabled

        value_output.enabled = self.source in {"density", "fire", "heat"}
        color_output.enabled = self.source in {"color", "velocity"}

        utils_node.copy_links_after_socket_swap(value_output, color_output, was_value_enabled)

    precision_items = [
        ("byte", "Byte", "Only 1 byte per value. Required memory is 1/2 of Half and 1/4 of Float", 0),
        ("half", "Half", "2 bytes per value. Required memory is 1/2 of Float, but 2 times the size of Byte", 1),
        (
        "float", "Float", "4 bytes per value. Required memory is 2 times the size of half and 4 times the size of Byte",
        2),
    ]
    precision: EnumProperty(name="Precision", items=precision_items, default="half",
                            description="How many bytes to use per value. The floating point precision "
                                        "increases/decreases when more/less bytes are used. Low floating "
                                        "point precision can lead to artifacts when the smoke resolution is low")

    file_path: StringProperty(name="OpenVDB File", subtype="FILE_PATH", update=update_file_path, description="Specify path to OpenVDB file. Only portable if a relative path is used")

    frame_start: IntProperty(name="StartFrame", description="Start frame for simulation", default=1)
    frame_end: IntProperty(name="EndFrame", description="End frame for simulation", default=250)

    nx: IntProperty(name="nx", description="Number of cells in x direction", default=32)
    ny: IntProperty(name="ny", description="Number of cells in y direction", default=32)
    nz: IntProperty(name="nz", description="Number of cells in z direction", default=32)

    gridtype: StringProperty(name="Grid type", description="data type of grid data")


    def init(self, context):
        #self.outputs.new("LuxCoreSocketFloatPositive", "Value")
        #color = self.outputs.new("LuxCoreSocketColor", "Color")
        #color.enabled = False
        names = []
        if self.file_path != "":
            self.outputs.clear()
            pyluxcore.GetOpenVDBGridNames(bpy.path.abspath(self.file_path), names)
            for n in names:
                bbox = []
                gridtype = []
                pyluxcore.GetOpenVDBGridInfo(bpy.path.abspath(self.file_path), n, bbox, gridtype)
                if gridtype[0] == "float":
                    self.outputs.new("LuxCoreSocketFloatPositive", n)
                else:
                    self.outputs.new("LuxCoreSocketColor", n)


    def draw_buttons(self, context, layout):
        layout.use_property_split = True
        layout.use_property_decorate = False

        layout.prop(self, "domain")

        if self.domain != None and utils.find_smoke_domain_modifier(self.domain):
            mod = utils.find_smoke_domain_modifier(self.domain)
            settings = mod.domain_settings
            layout.prop(settings.point_cache, "frame_start")
            layout.prop(settings.point_cache, "frame_end")
        else:
            layout.prop(self, "file_path")
            layout.prop(self, "frame_start")
            layout.prop(self, "frame_end")

        if self.domain is None:
            layout.label(text="Select the smoke domain object", icon=icons.WARNING)


    def sub_export(self, exporter, depsgraph, props, luxcore_name=None, output_socket=None):
        if not self.domain or self.file_path == "":
            error = "No Domain object selected."
            msg = 'Node "%s" in tree "%s": %s' % (self.name, self.id_data.name, error)
            LuxCoreErrorLog.add_warning(msg)

            definitions = {
                "type": "constfloat3",
                "value": [0, 0, 0],
            }
            return self.create_props(props, definitions, luxcore_name)

        domain = self.domain.evaluated_get(depsgraph)

        scale = domain.dimensions
        translate = domain.matrix_world @ mathutils.Vector([v for v in domain.bound_box[0]])
        rotate = domain.rotation_euler

        # create a location matrix
        tex_loc = mathutils.Matrix.Translation(translate)

        # create an identitiy matrix
        tex_sca = mathutils.Matrix()
        tex_sca[0][0] = scale[0]  # X
        tex_sca[1][1] = scale[1]  # Y
        tex_sca[2][2] = scale[2]  # Z

        # create a rotation matrix
        tex_rot0 = mathutils.Matrix.Rotation(rotate[0], 4, 'X')
        tex_rot1 = mathutils.Matrix.Rotation(rotate[1], 4, 'Y')
        tex_rot2 = mathutils.Matrix.Rotation(rotate[2], 4, 'Z')
        tex_rot = tex_rot2 @ tex_rot1 @ tex_rot0

        # combine transformations
        mapping_type = 'globalmapping3d'
        matrix_transformation = utils.matrix_to_list(tex_loc @ tex_rot @ tex_sca,
                                                     scene=exporter.scene,
                                                     apply_worldscale=True,
                                                     invert=True)

        definitions = {
            "type": "densitygrid",
            "wrap": "black",
            "storage": self.precision,
            "nx": self.nx,
            "ny": self.ny,
            "nz": self.nz,
            "openvdb.file": bpy.path.abspath(self.file_path),
            "openvdb.grid": output_socket.name,
            # Mapping
            "mapping.type": mapping_type,
            "mapping.transformation": matrix_transformation,
        }

        return self.create_props(props, definitions, luxcore_name)
