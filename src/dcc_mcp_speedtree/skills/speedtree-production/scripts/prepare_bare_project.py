from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.production_bare import make_bare_copy


@skill_entry
def main(source_path, output_path, **_kwargs):
    result = make_bare_copy(source_path, output_path)
    return skill_success("Bare SpeedTree project prepared for independent export.", **result)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
