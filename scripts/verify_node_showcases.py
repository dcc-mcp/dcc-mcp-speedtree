"""Export node stages and verify graph operations against real Modeler geometry.

Requires a licensed Modeler and a running adapter. All exports use new folders;
an existing stage export may be reused only after its hashes are verified.
"""

import argparse
import hashlib
import json
import time
from pathlib import Path

from build_node_showcases import call, cli


def export(instance, sources, output, preset):
    manifest = output / "export-manifest.json"
    if not manifest.exists():
        result = call(
            instance,
            "speedtree_export__export_batch",
            {
                "source_paths": [str(source) for source in sources],
                "output_dir": str(output),
                "preset_path": str(preset),
                "format": "obj",
                "timeout_seconds": 600,
            },
        )
        job_id = result.get("job_id") or result.get("core_job_id")
        if not job_id:
            raise RuntimeError(f"Missing Core job receipt: {result}")
        deadline = time.monotonic() + 660
        while time.monotonic() < deadline:
            status = call(instance, "jobs_get_status", {"job_id": job_id, "include_result": False})
            if status["status"] == "completed":
                break
            if status["status"] in {"failed", "cancelled", "canceled"}:
                raise RuntimeError(status)
            time.sleep(3)
        else:
            raise TimeoutError(f"Core export still pending: {job_id}")
    call(instance, "speedtree_export__verify_export", {"manifest_path": str(manifest)})
    result = json.loads(manifest.read_text(encoding="utf-8"))
    if result["status"] != "exported" or len(result["items"]) != len(sources):
        raise ValueError("Incomplete native export")
    counts = []
    for source, item in zip(sources, result["items"]):
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["source"]["sha256"]:
            raise ValueError("Stage source differs from exported source")
        mesh = output / item["mesh"]
        lines = mesh.read_text(encoding="utf-8").splitlines()
        counts.append(
            {
                "source": source.name,
                "vertices": sum(line.startswith("v ") for line in lines),
                "faces": sum(line.startswith("f ") for line in lines),
                "obj_sha256": hashlib.sha256(mesh.read_bytes()).hexdigest(),
                "positions_sha256": hashlib.sha256(
                    "\n".join(line for line in lines if line.startswith("v ")).encode()
                ).hexdigest(),
            }
        )
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage_root", type=Path)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--preset", required=True, type=Path)
    args = parser.parse_args()
    root = args.stage_root.resolve(strict=True)
    for skill in ("speedtree-nodes", "speedtree-export"):
        if not cli("load-skill", skill, "--instance-id", args.instance_id).get("loaded"):
            raise RuntimeError(f"Could not load {skill}")
    stages = json.loads((root / "showcase.json").read_text(encoding="utf-8"))["stages"]
    sources = [root / stage["source"] for stage in stages]
    counts = export(args.instance_id, sources, root / "exports", args.preset)
    final = next(
        root / s["source"] for s in stages if s["species"] == "willow" and s["stage"] == "04-leaves"
    )
    graph = call(args.instance_id, "speedtree_nodes__inspect_graph", {"source_path": str(final)})
    leaves = next(g["id"] for g in graph["generators"] if g["name"] == "Willow leaves")
    parent = next(link["source_id"] for link in graph["links"] if link["target_id"] == leaves)
    output = root / "operation-checks"
    output.mkdir(exist_ok=False)
    recipes = [
        ("removed", final, [{"op": "remove", "node_id": leaves}]),
        ("disconnected", final, [{"op": "disconnect", "source_id": parent, "target_id": leaves}]),
        (
            "reconnected",
            output / "disconnected.spm",
            [
                {"op": "connect", "source_id": parent, "target_id": leaves},
                {"op": "rename", "node_id": leaves, "name": "Reconnected leaves"},
            ],
        ),
        (
            "duplicated",
            final,
            [
                {
                    "op": "duplicate",
                    "node_id": leaves,
                    "parent_id": parent,
                    "name": "Additional leaves",
                }
            ],
        ),
    ]
    variants = []
    for name, source, operations in recipes:
        destination = output / f"{name}.spm"
        call(
            args.instance_id,
            "speedtree_nodes__edit_graph",
            {
                "source_path": str(source),
                "output_path": str(destination),
                "operations": operations,
            },
        )
        variants.append(destination)
    actual = export(args.instance_id, variants, output / "exports", args.preset)
    bare = next(c["faces"] for c in counts if c["source"] == "03-drooping-branches.spm")
    full = next(c["faces"] for c in counts if c["source"] == "04-leaves.spm")
    expected = [bare, bare, full, full + (full - bare)]
    if full <= bare or [item["faces"] for item in actual] != expected:
        raise AssertionError({"expected_faces": expected, "actual": actual})
    baseline = {item["source"]: item for item in counts}
    bare_positions = baseline["03-drooping-branches.spm"]["positions_sha256"]
    full_positions = baseline["04-leaves.spm"]["positions_sha256"]
    if [item["positions_sha256"] for item in actual[:3]] != [
        bare_positions,
        bare_positions,
        full_positions,
    ]:
        raise AssertionError("Removing and reconnecting leaves changed the baseline geometry")
    if (
        baseline["02-blades.spm"]["positions_sha256"]
        == baseline["03-tapered-clump.spm"]["positions_sha256"]
    ):
        raise AssertionError("Grass curve edits did not change vertex positions")
    receipt = {
        "schema": "speedtree.node-acceptance.v1",
        "status": "passed",
        "native_export": "Modeler CLI",
        "ui_automation": False,
        "stages": counts,
        "operation_checks": actual,
    }
    (output / "acceptance.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
