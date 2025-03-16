from collections import defaultdict

import breakneck.conversions as bnc
import build123d as bd
import kipy
import kipy.board
import kipy.board_types as kbt
import shapely
import shapely.geometry as sg
from kipy.board import BoardLayer as BL
from loguru import logger

import kitfg.config as kfc


def get_annotation_footprints(board: kipy.board.Board) -> list[kbt.FootprintInstance]:
    footprints = board.get_footprints()
    annotations = [
        fp for fp in footprints if fp.definition.id.name.startswith("TestFixture_")
    ]
    return annotations


def get_test_point_smd_pads(board: kipy.board.Board) -> list[kbt.Pad]:
    """
    Get all test point SMD pads located on the bottom side of the board.
    """

    # First get all footprints with the name starting with "TestPoint_" which
    # are located on the bottom side of the board.
    test_point_footprints = [
        fp
        for fp in board.get_footprints()
        if fp.definition.id.name.startswith("TestPoint_") and fp.layer == BL.BL_B_Cu
    ]

    # Then get all SMD pads from these footprints.
    pads = [
        pad
        for fp in test_point_footprints
        for pad in fp.definition.pads
        if pad.pad_type == kbt.PadType.PT_SMD
    ]

    return pads


def get_tht_pads(board: kipy.board.Board) -> list[kbt.Pad]:
    """
    Get all PTH THT pads.
    """

    # Disregard mounting hole pads

    footprints = [
        fp
        for fp in board.get_footprints()
        if not fp.definition.id.name.startswith("MountingHole_")
    ]

    pads: list[kbt.Pad] = []

    for fp in footprints:
        try:
            for pad in fp.definition.pads:
                if pad.pad_type == kbt.PadType.PT_PTH:
                    pads.append(pad)
        except ValueError:
            # kicad-python throws a ValueError if the footprint has no pads
            pass

    return pads


def get_unannotated(
    pads: list[kbt.Pad],
    annotation_footprints: list[kbt.FootprintInstance],
    radius_mm=1.0,
) -> list[kbt.Pad]:
    """
    Get all pads that don't have an annotation footprint within
    a radius of radius mm.
    """
    unannotated_pads: list[kbt.Pad] = []

    for pad in pads:
        pad_pos_nm = pad.position
        for annotation in annotation_footprints:
            annotation_pos_nm = annotation.position
            distance = (annotation_pos_nm - pad_pos_nm).length()
            if distance < radius_mm * 1e6:
                break
        else:
            unannotated_pads.append(pad)

    return unannotated_pads


def get_edge(board: kipy.board.Board) -> sg.LinearRing:
    edge_shapes = [
        shape for shape in board.get_shapes() if shape.layer == BL.BL_Edge_Cuts
    ]
    edges = bnc.as_polygons(edge_shapes, 1000)

    assert len(edges) == 1
    outline = sg.LinearRing(edges[0].exterior.coords)

    # Transform outline from nm to mm
    outline_mm = shapely.affinity.scale(
        outline, xfact=1.0e-6, yfact=1.0e-6, origin=(0, 0)
    )

    outline_mm = shapely.simplify(outline_mm, 0.01)

    return outline_mm


def get_annotation_positions(
    annotation_footprints: list[kbt.FootprintInstance],
) -> defaultdict[str, list[kbt.Vector2]]:
    """
    Return the positions of the annotation footprints, grouped by annotation type.
    """
    annotation_positions: defaultdict[str, list[kbt.Vector2]] = defaultdict(list)

    for annotation in annotation_footprints:
        annotation_type = annotation.definition.id.name
        annotation_positions[annotation_type].append(annotation.position)

    return annotation_positions


def render_plates(
    config: kfc.Config,
    annotation_positions: defaultdict[str, list[kbt.Vector2]],
    outline: sg.LinearRing,
) -> list[bd.Compound]:
    plates: list[bd.Compound] = []
    top_planes: list[bd.Plane] = []
    num_plates = 3

    plate_size = config.plate.size
    plate_thicknesses = config.plate.thicknesses_mm
    plate_alignment_pins = config.plate_alignment_pins
    annotations = config.annotations

    centroid = outline.centroid

    for i in range(num_plates):
        plate = bd.Part() + bd.Box(plate_size.w, plate_size.h, plate_thicknesses[i])
        top_plane = bd.Plane(plate.faces().sort_by(bd.Axis.Z)[-1])

        # Fillet corners
        pve = plate.edges().filter_by(bd.Axis.Z).sort_by(bd.Axis.Z)[0:4]
        plate = plate.fillet(3.0, pve)

        plates.append(plate)
        top_planes.append(top_plane)

    # Add alignment pins to the plates

    alignment_pin_locations = bd.Locations(
        bd.Rectangle(
            plate_size.w - 2 * plate_alignment_pins.alignment_pin_corner_offset.x,
            plate_size.h - 2 * plate_alignment_pins.alignment_pin_corner_offset.y,
        ).vertices()
    )

    plate_alignment_pin_annotation = annotations[
        plate_alignment_pins.plate_alignment_pin_type
    ]
    for i, plate in enumerate(plates):
        plates[i] = apply_operation(
            plate,
            top_planes[i].location * alignment_pin_locations,
            plate_alignment_pin_annotation[i],
            plate_thicknesses[i],
        )

    # Add alignment pressure pins
    pressure_pin_locations = bd.Locations(
        bd.Rectangle(
            plate_size.w - 2 * plate_alignment_pins.pressure_pin_corner_offset.x,
            plate_size.h - 2 * plate_alignment_pins.pressure_pin_corner_offset.y,
        ).vertices()
    )

    pressure_pin_annotation = annotations[plate_alignment_pins.pressure_pin_type]
    for i, plate in enumerate(plates):
        plates[i] = apply_operation(
            plate,
            top_planes[i].location * pressure_pin_locations,
            pressure_pin_annotation[i],
            plate_thicknesses[i],
        )

    # Add tester board mounting holes
    tester_board = config.tester_board
    mount_pillar_type = tester_board.mount_pillar_type
    mount_pillar_annotation = annotations[mount_pillar_type]
    mount_pillar_locations = bd.Locations(
        [(loc.x, loc.y) for loc in tester_board.mount_pillar_locations]
    )
    for i, plate in enumerate(plates):
        plates[i] = apply_operation(
            plate,
            top_planes[i].location * mount_pillar_locations,
            mount_pillar_annotation[i],
            plate_thicknesses[i],
        )

    # Process each footprint type
    for name, positions in annotation_positions.items():
        # Collect all location coordinates for this annotation
        def get_location_mm(pos_vector):
            pos = bnc.as_coords2d(pos_vector)
            # Convert pos from nm to mm
            pos = (pos[0] / 1e6, pos[1] / 1e6)
            pos = (pos[0] - centroid.x, pos[1] - centroid.y)
            return pos

        points = bd.Locations([get_location_mm(pos) for pos in positions])

        operations = annotations[name]
        for i, plate in enumerate(plates):
            plates[i] = apply_operation(
                plate,
                top_planes[i].location * points,
                operations[i],
                plate_thicknesses[i],
            )

    # Emboss board outline to the first two plates

    outline = shapely.affinity.translate(outline, xoff=-centroid.x, yoff=-centroid.y)

    outline_buffer_mm = outline.buffer(0.5)
    exterior = zip(*outline_buffer_mm.exterior.coords.xy)
    interiors = [zip(*interior.coords.xy) for interior in outline_buffer_mm.interiors]

    out_polyline = bd.Polyline(list(exterior))
    in_polylines = [bd.Polyline(list(interior)) for interior in interiors]

    face = bd.make_face(out_polyline)  # type: ignore

    for inp in in_polylines:
        face -= bd.make_face(inp)  # type: ignore

    for i, plate in enumerate(plates[:2]):
        top_plane = top_planes[i]
        face_plane = top_plane * face
        plate -= bd.extrude(face_plane, amount=-0.6)  # type: ignore
        plates[i] = plate

    # Emboss project name to all plates

    for i, plate in enumerate(plates):
        top_plane = top_planes[i]
        sketch = (
            top_plane
            * bd.Location((0, plate_size.h / 2 - 10))
            * bd.Text(
                f"{config.project.name} Plate {'ABC'[i]}",
                font_size=10.0,
            )
        )
        plate -= bd.extrude(sketch, amount=-0.6)  # type: ignore
        plates[i] = plate

    return plates


def apply_operation(plate, locations, operation, plate_thickness):
    if operation is None:
        return plate
    if isinstance(operation, kfc.CounterboreHole):
        logger.debug(
            f"Adding counterbore hole with diameter {operation.diameter_mm} and counterbore parameters {(operation.counterbore_diameter_mm, operation.counterbore_depth_mm, plate_thickness)}"
        )
        plate -= locations * bd.CounterBoreHole(
            radius=operation.diameter_mm / 2,
            counter_bore_radius=operation.counterbore_diameter_mm / 2,
            counter_bore_depth=operation.counterbore_depth_mm,
            depth=plate_thickness,
            mode=bd.Mode.SUBTRACT,
        )
    elif isinstance(operation, kfc.SimpleHole):
        plate -= locations * bd.Hole(
            radius=operation.diameter_mm / 2, depth=plate_thickness
        )

    return plate


def render_tester_board_mounts(config: kfc.Config) -> bd.Compound:
    """
    Render the tester board mounts.

    The tester board mounts are cylinders with dimensions specified in the config.
    """

    part = bd.Part()
    part += bd.Cylinder(
        radius=config.tester_board.diameter_mm / 2,
        height=config.tester_board.offset_mm,
    )
    part -= bd.Cylinder(
        radius=config.tester_board.screw_hole_diameter_mm / 2,
        height=config.tester_board.offset_mm,
    )

    return part


def render_pressure_pin(
    length_mm: float,
    hole_diam_mm,
    hole_height_mm=10.0,
    base_width_mm=6.0,
    tip_width_mm=3.0,
    chamfer_mm=1.0,
) -> bd.Compound:
    """
    Render a pressure pin with a length of length_mm.
    """

    plane = bd.Plane.XY

    faces = bd.Sketch() + [
        plane * bd.Rectangle(base_width_mm, base_width_mm),
        plane.offset(length_mm) * bd.Rectangle(tip_width_mm, tip_width_mm),
    ]  # type: ignore

    part = bd.Part()
    part += bd.loft(faces)

    part -= bd.Cylinder(
        radius=hole_diam_mm / 2,
        height=hole_height_mm,
    )

    # Chamfer non-parallel edges
    edges = part.edges()
    edges = edges - edges.filter_by(bd.Plane.XY)

    part = bd.chamfer(edges, chamfer_mm)
    return part
