import json

from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_speedtree.export import verify_export


@skill_entry
def main(manifest_path: str, **kwargs):
    result = verify_export(manifest_path)
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
