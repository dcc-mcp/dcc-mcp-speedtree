from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.capabilities import inspect_preset


@skill_entry
def main(preset_path: str, **_kwargs):
    preset = inspect_preset(preset_path)
    return skill_success("SpeedTree export preset inspected.", verified=True, preset=preset)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
