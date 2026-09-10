"""Build successive native generator stages through discovered MCP tools.

Run with --content-root <installed SpeedTree bin> --output <new directory>
--instance-id <registered SpeedTree instance>. No UI automation is used.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import uuid
from pathlib import Path


def cli(*args):
    result = subprocess.run(
        ["dcc-mcp-cli", *args], check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return json.loads(result.stdout)


def call(instance, tool, arguments):
    result = cli("call", tool, "--instance-id", instance, "--json", json.dumps(arguments))
    if not result.get("success") or result.get("result", {}).get("isError"):
        raise RuntimeError(result)
    payload = result["result"].get("structuredContent")
    if payload is None:
        payload = json.loads(result["result"]["content"][0]["text"])
    if payload.get("success") is False:
        raise RuntimeError(payload)
    return payload.get("context", payload)


def properties(node, values):
    return [
        {"op": "set_property", "node_id": node, "name": name, "value": value}
        for name, value in values.items()
    ]


def recipes(root, tree_id):
    templates = root / "templates" / "combined"

    def add(node, name, filename, parent):
        return {
            "op": "add",
            "node_id": node,
            "name": name,
            "template_path": str(templates / filename),
            "parent_id": parent,
        }

    willow = [
        (
            "01-trunk",
            [add("willow-trunk", "Willow trunk", "__________Trunk.stt", tree_id)]
            + properties(
                "willow-trunk",
                {
                    "Spine:Length:Absolute": 7.5,
                    "Skin:Radius:Absolute": 0.28,
                    "Random Seeds:Spine": 1701,
                },
            ),
        ),
        (
            "02-primary-branches",
            [add("willow-primary", "Primary branches", "___Branches/__Big.stt", "willow-trunk")]
            + properties(
                "willow-primary",
                {
                    "Generation:First": 0.42,
                    "Generation:Last": 0.94,
                    "Generation:Interval:Frequency": 2.2,
                    "Spine:Length:Absolute": 3.3,
                    "Spine:Length:+ % of parent": 0,
                    "Spine:Orientation:Start angle": 0.38,
                    "Spine:Shape:Gravity": 0.2,
                    "Skin:Radius:Absolute": 0.08,
                    "Skin:Radius:+ % of parent": 0,
                },
            ),
        ),
        (
            "03-drooping-branches",
            [
                add(
                    "willow-drooping",
                    "Drooping branches",
                    "___Branches/__Twigs.stt",
                    "willow-primary",
                )
            ]
            + properties(
                "willow-drooping",
                {
                    "Generation:First": 0.2,
                    "Generation:Last": 1,
                    "Generation:Interval:Frequency": 4,
                    "Spine:Length:Absolute": 3.0,
                    "Spine:Length:+ % of parent": 0,
                    "Spine:Orientation:Start angle": 0.36,
                    "Spine:Shape:Gravity": 1.1,
                    "Skin:Radius:Absolute": 0.011,
                    "Skin:Radius:+ % of parent": 0,
                },
            ),
        ),
        (
            "04-leaves",
            [
                add(
                    "willow-leaves",
                    "Willow leaves",
                    "___Leaves/__Alternating.stt",
                    "willow-drooping",
                )
            ]
            + properties(
                "willow-leaves",
                {
                    "Generation:Mode": 3,
                    "Generation:Absolute:Number": 72,
                    "Generation:Absolute Steps:Steps": 22,
                    "Generation:Absolute Steps:Per Step:Number": 2,
                    "Generation:First": 0.05,
                    "Generation:Last": 1,
                    "Leaves:Size": 0.24,
                    "Deformation:Scale:X": 0.28,
                    "Deformation:Scale:Y": 1.2,
                    "Deformation:Fold": 0.18,
                },
            ),
        ),
    ]
    grass = [
        (
            "01-stalks",
            [
                {"op": "set_property", "node_id": tree_id, "name": "Shape:Radius", "value": 2},
                {
                    "op": "add",
                    "node_id": "grass-stalks",
                    "name": "Grass stalks",
                    "template_path": str(root / "tree_templates/VFX/_Grass.spm"),
                    "template_node_id": "o4nw4Qp7fkCW1XYpravGxQ==",
                    "parent_id": tree_id,
                },
            ]
            + properties(
                "grass-stalks",
                {
                    "Generation:Mode": 5,
                    "Generation:Absolute Steps:Steps": 5,
                    "Generation:Absolute Steps:Per Step:Number": 16,
                    "Generation:First": 0.015,
                    "Generation:Last": 0.24,
                    "Spine:Length:Absolute": 0.65,
                    "Spine:Orientation:Start angle": 0.36,
                    "Spine:Shape:Gravity": 0.12,
                    "Skin:Radius:Absolute": 0.0015,
                    "Random Seeds:Spine": 2901,
                },
            ),
        ),
        (
            "02-blades",
            [
                {
                    "op": "add",
                    "node_id": "grass-blades",
                    "name": "Grass blades",
                    "template_path": str(root / "tree_templates/VFX/_Grass.spm"),
                    "template_node_id": "9Xy0bgn1fEy10P0UFSX2sw==",
                    "parent_id": "grass-stalks",
                }
            ]
            + properties(
                "grass-blades",
                {
                    "Shape:Scale:Width": 0.028,
                    "Shape:Fold": 0.5,
                    "Shape:Roll": 0.14,
                    "Material:Two sided": True,
                },
            ),
        ),
        (
            "03-tapered-clump",
            properties("grass-stalks", {"Spine:Length:Absolute": 0.55})
            + [
                {
                    "op": "set_property",
                    "node_id": "grass-blades",
                    "name": "Shape:Scale:Width",
                    "component": "ProfileSpline/ControlPoint[2]/Y",
                    "value": 0,
                }
            ],
        ),
    ]
    mapping = {
        name: base64.b64encode(
            uuid.uuid5(uuid.NAMESPACE_URL, "speedtree-showcase/" + name).bytes_le
        ).decode("ascii")
        for name in [
            "willow-trunk",
            "willow-primary",
            "willow-drooping",
            "willow-leaves",
            "grass-stalks",
            "grass-blades",
        ]
    }
    for stages in (willow, grass):
        for _, operations in stages:
            for operation in operations:
                for key in ("node_id", "parent_id", "source_id", "target_id", "new_id"):
                    if key in operation and operation[key] in mapping:
                        operation[key] = mapping[operation[key]]
    return {"willow": willow, "grass": grass}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--instance-id", required=True)
    args = parser.parse_args()
    root = args.content_root.resolve(strict=True)
    output = args.output.resolve()
    blank = root / "tree_templates" / "VFX" / " __Blank.spm"
    loaded = cli("load-skill", "speedtree-nodes", "--instance-id", args.instance_id)
    if not loaded.get("loaded"):
        raise RuntimeError(loaded)
    graph = call(args.instance_id, "speedtree_nodes__inspect_graph", {"source_path": str(blank)})
    tree_id = next(g["id"] for g in graph["generators"] if g["type"] == "Tree")
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "schema": "speedtree.node-showcase.v1",
        "creation_route": "native_file_graph",
        "ui_automation": False,
        "stages": [],
    }
    for species, stages in recipes(root, tree_id).items():
        folder = output / species
        folder.mkdir()
        source = blank
        for stage, operations in stages:
            destination = folder / f"{stage}.spm"
            arguments = {
                "source_path": str(source),
                "output_path": str(destination),
                "operations": operations,
            }
            result = call(args.instance_id, "speedtree_nodes__edit_graph", arguments)
            (folder / f"{stage}-receipt.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            manifest["stages"].append(
                {
                    "species": species,
                    "stage": stage,
                    "source": destination.relative_to(output).as_posix(),
                    "sha256": result["output"]["sha256"],
                    "graph": result["graph"],
                    "operations": [
                        {k: Path(v).name if k == "template_path" else v for k, v in op.items()}
                        for op in operations
                    ],
                    "geometry_validation": "pending_modeler_export",
                }
            )
            (output / "showcase.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            print(f"{species}/{stage}: {len(result['graph']['generators'])} generators", flush=True)
            source = destination


if __name__ == "__main__":
    main()
