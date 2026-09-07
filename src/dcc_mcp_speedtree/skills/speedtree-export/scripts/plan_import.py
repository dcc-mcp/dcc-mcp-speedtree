from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.handoff import plan_import


@skill_entry
def main(manifest_path: str, target: str, **kwargs):
    return skill_success(
        "Import handoff prepared; discover the target importer",
        **plan_import(manifest_path, target),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
