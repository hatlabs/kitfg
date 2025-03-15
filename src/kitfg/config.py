from typing import List, NamedTuple, Union

import toml
from pydantic import BaseModel, field_validator


class SimpleHole(BaseModel):
    diameter_mm: float


class CounterboreHole(SimpleHole):
    counterbore_diameter_mm: float
    counterbore_depth_mm: float


HoleType = Union[SimpleHole, CounterboreHole, None]


class Annotation(NamedTuple):
    A: HoleType
    B: HoleType
    C: HoleType


class Project(BaseModel):
    name: str


class PlateSize(BaseModel):
    width_mm: float
    height_mm: float

    @property
    def w(self):
        return self.width_mm

    @property
    def h(self):
        return self.height_mm


class Plate(BaseModel):
    size: PlateSize
    thicknesses_mm: List[float]


class PCB(BaseModel):
    thickness_mm: float
    top_clearance_mm: float
    bottom_clearance_mm: float


class Location(BaseModel):
    x_mm: float
    y_mm: float

    @property
    def x(self):
        return self.x_mm

    @property
    def y(self):
        return self.y_mm


class PlateAlignmentPins(BaseModel):
    alignment_pin_corner_offset: Location
    pressure_pin_corner_offset: Location
    plate_alignment_pin_type: str
    pressure_pin_type: str


class TesterBoard(BaseModel):
    offset_mm: float
    mount_pillar_type: str
    mount_pillar_locations: List[Location]


class Config(BaseModel):
    project: Project
    plate: Plate
    pcb: PCB
    plate_alignment_pins: PlateAlignmentPins
    tester_board: TesterBoard
    annotations: dict[str, Annotation]

    @field_validator("annotations", mode="before")
    def parse_annotations(cls, value):
        def _parse_annotation(annotation: list[dict]) -> Annotation:
            assert len(annotation) == 3
            holes = []
            for hole in annotation:
                type_ = hole["type"]
                del hole["type"]
                if type_ == "SimpleHole":
                    holes.append(SimpleHole(**hole))
                elif type_ == "CounterboreHole":
                    holes.append(CounterboreHole(**hole))
                else:
                    holes.append(None)
            return Annotation(A=holes[0], B=holes[1], C=holes[2])

        return {key: _parse_annotation(val) for key, val in value.items()}


def parse_config(file_path: str) -> Config:
    data = toml.load(file_path)
    return Config.model_validate(data)
