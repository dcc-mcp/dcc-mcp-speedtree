from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.node_tools import inspect_graph


@skill_entry
def main(source_path, **_kwargs):
    result = inspect_graph(source_path)
    return skill_success(
        "Native file operation completed; geometry requires Modeler regeneration.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
