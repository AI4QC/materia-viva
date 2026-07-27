"""Short-lived OVITO/Tachyon worker used by :mod:`ovito_renderer`."""

from __future__ import annotations

import argparse
import gc
import math
import os
import tempfile
import warnings
from pathlib import Path

import numpy as np


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render one CIF with OVITO/Tachyon")
    parser.add_argument("input")
    parser.add_argument("--output", required=True)
    parser.add_argument("--view", choices=("isometric", "front", "top"), default="isometric")
    parser.add_argument(
        "--representation", choices=("ball_stick", "spacefill"), default="ball_stick"
    )
    parser.add_argument("--supercell", default="2,2,2")
    parser.add_argument("--quality", choices=("preview", "high"), default="preview")
    parser.add_argument("--show-cell", action="store_true")
    return parser


def render(args: argparse.Namespace) -> None:
    warnings.filterwarnings("ignore", message=".*OVITO.*PyPI")
    # PyPI's PySide6 wheel keeps Qt plugins inside its package. Register that
    # path before importing OVITO so headless workers can find qoffscreen.
    try:
        from PySide6.QtCore import QLibraryInfo

        os.environ.setdefault(
            "QT_PLUGIN_PATH", QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
        )
    except ImportError:
        pass
    from ase.data import atomic_numbers, covalent_radii
    from ase.data.colors import jmol_colors
    from ase.io import read, write
    from ovito import scene
    from ovito.io import import_file
    from ovito.modifiers import CreateBondsModifier
    from ovito.vis import TachyonRenderer, Viewport

    repeats = tuple(int(value) for value in args.supercell.split(","))
    if len(repeats) != 3 or any(value < 1 or value > 4 for value in repeats):
        raise ValueError("invalid supercell")
    atoms = read(args.input, format="cif")
    if len(atoms) < 15 and repeats != (1, 1, 1):
        atoms = atoms.repeat(repeats)

    with tempfile.NamedTemporaryFile(suffix=".extxyz") as exchange:
        write(exchange.name, atoms, format="extxyz")
        pipeline = import_file(exchange.name)
        if args.representation == "ball_stick":
            pipeline.modifiers.append(CreateBondsModifier(cutoff=2.8))
        pipeline.add_to_scene()
        try:
            data = pipeline.compute()
            cell_vis = data.cell_.vis
            cell_vis.enabled = bool(args.show_cell)
            cell_vis.rendering_color = (0.38, 0.90, 0.69)
            cell_vis.line_width = 0.025
            particles = data.particles_
            particle_vis = particles.vis
            particle_vis.radius = 0.55 if args.representation == "ball_stick" else 1.0
            particle_types = particles.particle_types_
            for particle_type in particle_types.types_:
                number = atomic_numbers.get(particle_type.name)
                if number:
                    particle_type.color = tuple(float(v) for v in jmol_colors[number])
                    multiplier = 0.55 if args.representation == "ball_stick" else 1.0
                    particle_type.radius = max(0.25, float(covalent_radii[number]) * multiplier)
            if particles.bonds is not None:
                particles.bonds_.vis.width = 0.16

            positions = np.asarray(atoms.positions)
            center = positions.mean(axis=0)
            bounds = np.ptp(positions, axis=0)
            maximum = max(float(bounds.max()), float(np.max(atoms.cell.lengths())), 2.0)
            elevation, azimuth = {
                "isometric": (30.0, 45.0),
                "front": (0.0, 0.0),
                "top": (89.0, 0.0),
            }[args.view]
            elevation = math.radians(elevation)
            azimuth = math.radians(azimuth)
            distance = maximum * 3.2
            camera = np.array([
                center[0] + distance * math.cos(elevation) * math.cos(azimuth),
                center[1] + distance * math.cos(elevation) * math.sin(azimuth),
                center[2] + distance * math.sin(elevation),
            ])

            viewport = Viewport(type=Viewport.Type.Perspective)
            viewport.camera_pos = tuple(camera)
            viewport.camera_dir = tuple(center - camera)
            viewport.fov = math.radians(35)
            renderer = TachyonRenderer()
            renderer.antialiasing = True
            renderer.direct_light = True
            renderer.shadows = True
            renderer.ambient_occlusion = True
            renderer.ambient_occlusion_samples = 16 if args.quality == "high" else 8
            renderer.direct_light_intensity = 0.9
            size = (1600, 1200) if args.quality == "high" else (1000, 760)
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            viewport.render_image(
                filename=args.output,
                size=size,
                renderer=renderer,
                background=(0.027, 0.039, 0.047),
                crop=False,
                alpha=False,
            )
        finally:
            pipeline.remove_from_scene()
            scene.pipelines.clear()
            gc.collect()


def main() -> int:
    render(_parser().parse_args())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
