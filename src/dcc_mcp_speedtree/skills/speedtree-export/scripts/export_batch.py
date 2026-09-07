import json

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_speedtree.export import export_batch


@skill_entry
def main(
    source_paths: list[str],
    preset_path: str,
    output_dir: str,
    format: str = "st9",
    timeout_seconds: int = 300,
    **kwargs,
):
    result = export_batch(source_paths, preset_path, output_dir, format, timeout_seconds)
    ok = result.get("status") == "exported" if "status" in result else result["verified"]
    if not ok:
        return skill_error("SpeedTree export verification failed", json.dumps(result))
    return skill_success(
        "SpeedTree export files verified; target import validation still required",
        **result,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
