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


def get_footprints(board: kipy.board.Board) -> list[kbt.FootprintInstance]:
    footprints = board.get_footprints()
    annotations = [
        fp for fp in footprints if fp.definition.id.name.startswith("TestFixture_")
    ]
    return annotations


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


def render_plates(
    config: kfc.Config, footprints: list[kbt.FootprintInstance], outline: sg.LinearRing
) -> list[bd.Compound]:
    plates: list[bd.Compound] = []
    num_plates = 3

    plate_size = config.plate.size
    plate_thicknesses = config.plate.thicknesses_mm
    plate_alignment_pins = config.plate_alignment_pins
    annotations = config.annotations

    centroid = outline.centroid

    for i in range(num_plates):
        plate = bd.Part() + bd.Box(plate_size.w, plate_size.h, plate_thicknesses[i])

        plates.append(plate)

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
            plate, alignment_pin_locations, plate_alignment_pin_annotation[i]
        )

    # Group footprints by name
    footprints_by_name = defaultdict(list)
    for footprint in footprints:
        if footprint.definition.id.name not in annotations:
            logger.warning(f"Unknown annotation: {footprint.definition.id.name}")
            continue
        footprints_by_name[footprint.definition.id.name].append(footprint)

    # Process each footprint type
    for name, footprints in footprints_by_name.items():
        # Collect all point coordinates for this annotation
        def get_pos(footprint):
            pos = bnc.as_coords2d(footprint.position)
            # Convert pos from nm to mm
            pos = (pos[0] / 1e6, pos[1] / 1e6)
            pos = (pos[0] - centroid.x, pos[1] - centroid.y)
            return pos

        points = bd.Locations([get_pos(footprint) for footprint in footprints])

        operations = annotations[name]
        for i, plate in enumerate(plates):
            plates[i] = apply_operation(plate, points, operations[i])

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
        top_plane = bd.Plane(plate.faces().sort_by(bd.Axis.Z)[-1])
        face_plane = top_plane * face
        plate -= bd.extrude(face_plane, amount=-0.6)  # type: ignore
        plates[i] = plate

    # Emboss project name to all plates

    for i, plate in enumerate(plates):
        top_plane = bd.Plane(plate.faces().sort_by(bd.Axis.Z)[-1])
        sketch = (
            top_plane
            * bd.Location((0, plate_size.h / 2 - 10))
            * bd.Text(
                f"{config.project.name} Test Jig Plate {'ABC'[i]}",
                font_size=10.0,
            )
        )
        plate -= bd.extrude(sketch, amount=-0.6)  # type: ignore
        plates[i] = plate

    # Finally, fillet vertical plate edges
    for i, plate in enumerate(plates):
        pve = plate.edges().filter_by(bd.Axis.Z).sort_by(bd.Axis.Z)[0:4]
        plate = plate.fillet(3.0, pve)

        plates[i] = plate

    return plates


def apply_operation(plate, locations, operation):
    if operation is None:
        return plate
    top_plane = bd.Plane(plate.faces().sort_by(bd.Axis.Z)[-1])
    if isinstance(operation, kfc.SimpleHole):
        plate -= (
            top_plane
            * locations
            * bd.Hole(radius=operation.diameter_mm / 2, depth=100.0)
        )
    elif isinstance(operation, kfc.CounterboreHole):
        plate -= (
            top_plane
            * locations
            * bd.CounterBoreHole(
                radius=operation.diameter_mm / 2,
                counter_bore_radius=operation.counterbore_diameter_mm / 2,
                counter_bore_depth=operation.counterbore_depth_mm,
                depth=100.0,
            )
        )
    return plate
