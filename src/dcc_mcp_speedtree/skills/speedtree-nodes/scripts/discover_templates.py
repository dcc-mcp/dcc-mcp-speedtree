from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.node_tools import discover_templates


@skill_entry
def main(speedtree_root, **_kwargs):
    result = discover_templates(speedtree_root)
    return skill_success(
        "Native file operation completed; geometry requires Modeler regeneration.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
