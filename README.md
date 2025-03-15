# KiCad Test Fixture Generator

## Introduction

KiTFG is a Python script that generates bed-of-nails test fixture plates for KiCad projects. It uses the KiCad Python API to extract the board outline and test pin positions from a KiCad PCB file and generates solid modeling STEP files for 3D printing or CNC machining.

## Installation

TODO: Provide a more user-friendly installation process.

- Install [Pixi](https://pixi.sh/latest/).
- Clone this repository
- Run `pixi install` in the repository directory
- Start a new shell in the pixi environment: `pixi shell`
- Install the project in-place: `pip install -e .`

## Usage

Have a KiCad project open in the KiCad PCB editor. Make sure you have enabled the Python scripting API in the KiCad settings. Then, run the following command:

```shell
kitfg example_config.toml output
```

This will generate STEP files in the `output` directory. You can inspect the generated files in a 3D viewer like FreeCAD or 3D printing software.
