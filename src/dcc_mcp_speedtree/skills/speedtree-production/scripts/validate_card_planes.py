from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.production_planarity import validate_card_planes


@skill_entry
def main(full_obj, material_categories, tolerance=0.001, **_kwargs):
    result = validate_card_planes(full_obj, material_categories, tolerance)
    return skill_success(
        "Card geometry checked; texture and visual review remain pending.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
