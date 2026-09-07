from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.capabilities import discover_official_content


@skill_entry
def main(speedtree_root: str, **_kwargs):
    content = discover_official_content(speedtree_root)
    return skill_success("Official SpeedTree content discovered.", verified=True, content=content)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
