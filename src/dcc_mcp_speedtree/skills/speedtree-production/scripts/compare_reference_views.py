from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.reference_match import compare_reference_views


@skill_entry
def main(references, candidates, output_dir, canvas_size=512, **_kwargs):
    result = compare_reference_views(references, candidates, output_dir, canvas_size)
    return skill_success("Silhouette comparison prepared; artistic review is pending.", **result)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
