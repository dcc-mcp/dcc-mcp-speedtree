from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.reference_rank import rank_reference_candidates


@skill_entry
def main(references, candidate_sets, output_dir, canvas_size=512, **_kwargs):
    result = rank_reference_candidates(references, candidate_sets, output_dir, canvas_size)
    return skill_success(
        "Candidate silhouette ranking prepared; artistic review is pending.", **result
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
