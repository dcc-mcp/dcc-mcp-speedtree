from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.production_preview import generate_diagnostic_views


@skill_entry
def main(obj_path, output_dir, material_categories, resolution=768, **_kwargs):
    result = generate_diagnostic_views(obj_path, output_dir, material_categories, resolution)
    return skill_success(
        "Blender diagnostic previews prepared; artistic review is pending.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
