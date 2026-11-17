from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.production_validation import validate_obj_budget


@skill_entry
def main(obj_path, material_categories, total_max_triangles, category_limits, **_kwargs):
    result = validate_obj_budget(
        obj_path, material_categories, total_max_triangles, category_limits
    )
    return skill_success(
        "OBJ geometry budget readback complete; visual acceptance is pending.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
