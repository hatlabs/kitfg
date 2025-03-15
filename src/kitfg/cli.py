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
    footprints = kf.get_footprints(board)
    edge = kf.get_edge(board)

    plates = kf.render_plates(config, footprints, edge)
    args.output.mkdir(exist_ok=True)
    for i, plate in enumerate(plates):
        bd.export_step(
            plate, args.output / f"{config.project.name}_plate_{"ABC"[i]}.step"
        )


if __name__ == "__main__":
    main()
