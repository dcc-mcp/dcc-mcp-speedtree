"""Compose a README animation from verified native stage data and mesh renders.

Requires ffmpeg. The graph is drawn from saved IDs/links; the right-hand image
is explicitly an exported-geometry render, never a fabricated Modeler UI.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def run(*arguments):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", *arguments], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/segoeui.ttf"))
    parser.add_argument("--renders", default="renders")
    args = parser.parse_args()
    root = args.stage_root.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    stages = json.loads((root / args.renders / "readback.json").read_text(encoding="utf-8"))
    font = args.font.resolve(strict=True).as_posix().replace(":", "\\:")
    frames = []
    for index, stage in enumerate(stages):
        filters = []

        def label(value, x, y, size=24, color="d7e5db"):
            if any(c in value for c in "'\\:%"):
                raise ValueError("Unexpected diagram label character")
            filters.append(
                f"drawtext=fontfile='{font}':text='{value}':x={x}:y={y}:fontsize={size}:fontcolor=0x{color}"
            )

        label("NATIVE NODE WORKFLOW", 60, 50, 19, "8ca78e")
        label(stage["species"].capitalize(), 60, 97, 50)
        title = (
            "Taper width curve"
            if stage["stage"] == "03-tapered-clump"
            else "Add " + stage["stage"][3:].replace("-", " ")
        )
        label(title, 60, 164, 27)
        graph = stage["graph"]
        nodes = sorted(graph["generators"], key=lambda n: int(n["level"]))
        positions = {node["id"]: (60, 240 + i * 88) for i, node in enumerate(nodes)}
        for link in graph["links"]:
            sx, sy = positions[link["source_id"]]
            tx, ty = positions[link["target_id"]]
            filters.append(
                f"drawbox=x={sx + 24}:y={sy + 58}:w=2:h={ty - sy - 58}:color=0x526554:t=fill"
            )
        changed = {op.get("node_id") for op in stage["operations"]}
        for node in nodes:
            x, y = positions[node["id"]]
            accent = "a5c46c" if node["id"] in changed else "526554"
            filters.append(f"drawbox=x={x}:y={y}:w=390:h=58:color=0x203027:t=fill")
            filters.append(f"drawbox=x={x}:y={y}:w=4:h=58:color=0x{accent}:t=fill")
            label(node["name"], x + 20, y + 13, 23)
        vertices = stage["geometry_validation"]["vertices"]
        faces = stage["geometry_validation"]["faces"]
        operation_label = (
            "Edit scalar + spline component"
            if stage["stage"] == "03-tapered-clump"
            else "Add + connect + set properties"
        )
        label(operation_label, 60, 687, 19, "a5c46c")
        label(f"{len(nodes)} generators   /   {vertices:,} vertices", 60, 730, 21, "9aae9c")
        label(f"{faces:,} faces from Modeler OBJ", 60, 766, 21, "9aae9c")
        label(f"STEP {index + 1:02d} / {len(stages):02d}", 60, 836, 19, "a5c46c")
        filters.append("drawbox=x=560:y=830:w=1040:h=70:color=0x0c1815:t=fill")
        label("Exported mesh render - display materials - no UI automation", 565, 854, 19, "9aae9c")
        frame = output / f"stage-{index + 1:02d}.png"
        graph_filter = "[0:v]scale=922:830[mesh];[1:v][mesh]overlay=599:0," + ",".join(filters)
        run(
            "-i",
            str(root / stage["render"]),
            "-f",
            "lavfi",
            "-i",
            "color=c=0x0c1815:s=1600x900",
            "-filter_complex",
            graph_filter,
            "-frames:v",
            "1",
            str(frame),
        )
        frames.append(frame)
        stage["render"] = frame.name
        stage["render_sha256"] = hashlib.sha256(frame.read_bytes()).hexdigest()
    listing = output / "frames.txt"
    listing.write_text(
        "".join(f"file '{p.name}'\nduration 2.6\n" for p in frames) + f"file '{frames[-1].name}'\n",
        encoding="utf-8",
    )
    run(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
        "-vf",
        "fps=5,scale=1200:-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=bayer",
        "-loop",
        "0",
        str(output / "native-node-workflow.gif"),
    )
    run(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(listing),
        "-vf",
        "fps=30,format=yuv420p",
        "-c:v",
        "libx264",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        str(output / "native-node-workflow.mp4"),
    )
    shutil.copyfile(frames[3], output / "willow.png")
    shutil.copyfile(frames[-1], output / "grass.png")
    (output / "provenance.json").write_text(
        json.dumps(
            {
                "schema": "speedtree.node-showcase.v1",
                "modeler": "10.1.0",
                "creation": "SPM generator edits through speedtree-nodes; official Modeler CLI export",
                "visualization": "Headless Blender 5.1.1, unchanged OBJ geometry with display materials",
                "ui_automation": False,
                "modeler_screenshots": False,
                "stages": stages,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
