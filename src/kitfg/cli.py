import argparse
import pathlib

import build123d as bd
import kipy

import kitfg.config as kfconfig
import kitfg.kitfg as kf


def parse_args():
    parser = argparse.ArgumentParser(description="KiCad Test Fixture Generator")
    parser.add_argument("config", type=argparse.FileType("r"), help="Config file")
    parser.add_argument(
        "output", type=pathlib.Path, help="Path to the output directory"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = kfconfig.parse_config(args.config.name)

    board = kipy.KiCad().get_board()
    footprints = kf.get_annotation_footprints(board)
    annotation_positions = kf.get_annotation_positions(footprints)
    edge = kf.get_edge(board)

    unannotated_smt_pads = kf.get_unannotated(
        kf.get_test_point_smd_pads(board), footprints
    )

    unannotated_tht_pads = kf.get_unannotated(kf.get_tht_pads(board), footprints)

    if config.project.test_point_auto_annotation_type:
        annotation_positions[config.project.test_point_auto_annotation_type].extend(
            pad.position for pad in unannotated_smt_pads
        )

    if config.project.tht_pad_auto_annotation_type:
        annotation_positions[config.project.tht_pad_auto_annotation_type].extend(
            pad.position for pad in unannotated_tht_pads
        )

    plates = kf.render_plates(config, annotation_positions, edge)

    pressure_pin_length = config.pcb.top_clearance_mm
    long_pressure_pin_length = (
        pressure_pin_length + config.pcb.thickness_mm + config.pcb.bottom_clearance_mm
    )

    pressure_pin = kf.render_pressure_pin(
        pressure_pin_length,
        config.plate_alignment_pins.pressure_pin_screw_hole_diameter_mm,
    )
    long_pressure_pin = kf.render_pressure_pin(
        long_pressure_pin_length,
        config.plate_alignment_pins.pressure_pin_screw_hole_diameter_mm,
    )

    mount_pillar = kf.render_tester_board_mounts(config)

    args.output.mkdir(exist_ok=True)
    for i, plate in enumerate(plates):
        bd.export_step(
            plate, args.output / f"{config.project.name}_plate_{"ABC"[i]}.step"
        )

    bd.export_step(
        pressure_pin,
        args.output
        / f"{config.project.name}_pressure_pin_{pressure_pin_length}mm.step",
    )
    bd.export_step(
        long_pressure_pin,
        args.output
        / f"{config.project.name}_pressure_pin_{long_pressure_pin_length}mm.step",
    )
    bd.export_step(
        mount_pillar,
        args.output
        / f"{config.project.name}_tester_board_mount_{config.tester_board.offset_mm}mm.step",
    )


if __name__ == "__main__":
    main()
