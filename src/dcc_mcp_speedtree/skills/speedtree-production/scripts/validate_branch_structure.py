from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.production_structure import validate_branch_structure


@skill_entry
def main(source_path, trunk_id, max_branch_order=2, max_secondary=None, **_kwargs):
    result = validate_branch_structure(source_path, trunk_id, max_branch_order, max_secondary)
    return skill_success(
        "Stored generator hierarchy inspected; regenerated appearance remains unverified.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
