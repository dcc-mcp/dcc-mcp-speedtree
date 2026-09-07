from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.export import export_status


@skill_entry
def main(manifest_path: str, **kwargs):
    return skill_success("Export progress read", **export_status(manifest_path))


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
