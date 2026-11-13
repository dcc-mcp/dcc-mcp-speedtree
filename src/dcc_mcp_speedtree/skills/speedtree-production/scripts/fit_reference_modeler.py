from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_speedtree.reference_fit_modeler import fit_reference_modeler


@skill_entry
def main(
    source_path,
    output_dir,
    parameters,
    references,
    preset_path,
    material_categories,
    brief,
    trunk_id,
    **kwargs,
):
    allowed = {
        "base_operations",
        "total_max_triangles",
        "card_triangles",
        "max_branch_order",
        "max_secondary",
        "plane_tolerance",
        "max_evaluations",
        "max_rounds",
        "resolution",
        "candidate_view_map",
    }
    result = fit_reference_modeler(
        source_path,
        output_dir,
        parameters,
        references,
        preset_path,
        material_categories,
        brief,
        trunk_id,
        **{key: value for key, value in kwargs.items() if key in allowed},
    )
    if result["status"] != "candidate_selected":
        return skill_error("No eligible fitted candidate was selected.", result["status"], **result)
    return skill_success(
        "Budget-gated candidate selected; visual review remains required.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
