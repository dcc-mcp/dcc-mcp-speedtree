from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.production import generate_project


@skill_entry
def main(source_path, output_dir, operations, brief, **_kwargs):
    result = generate_project(source_path, output_dir, operations, brief)
    return skill_success(
        "Candidate prepared; Modeler and visual verification are pending.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
