from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_speedtree.export import verify_export


@skill_entry
def main(manifest_path: str, **kwargs):
    result = verify_export(manifest_path)
    if not result["verified"]:
        return skill_error(
            "SpeedTree export verification failed", "bundle_integrity_failed", **result
        )
    return skill_success(
        "SpeedTree export files verified; target import validation still required",
        **result,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
