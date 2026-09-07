from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.capabilities import capability_status


@skill_entry
def main(**kwargs):
    return skill_success(
        "SpeedTree implementation coverage; no live host probe.", **capability_status()
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
