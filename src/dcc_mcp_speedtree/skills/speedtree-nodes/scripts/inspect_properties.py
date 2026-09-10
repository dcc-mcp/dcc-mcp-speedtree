from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.node_tools import inspect_properties


@skill_entry
def main(source_path, node_id, **_kwargs):
    result = inspect_properties(source_path, node_id)
    return skill_success(
        "Native file operation completed; geometry requires Modeler regeneration.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
