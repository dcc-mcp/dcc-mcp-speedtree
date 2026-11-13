from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.production_pair import validate_obj_pair


@skill_entry
def main(full_path, bare_path, total_max_triangles, card_triangles, **_kwargs):
    result = validate_obj_pair(full_path, bare_path, total_max_triangles, card_triangles)
    return skill_success(
        "Full and bare geometry compared; source attribution requires review.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
