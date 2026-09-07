from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.capabilities import plan_export


@skill_entry
def main(
    source_path: str,
    preset_path: str,
    output_dir: str,
    format: str | None = None,
    **_kwargs,
):
    plan = plan_export(source_path, preset_path, output_dir, format=format)
    return skill_success("SpeedTree export plan prepared.", verified=True, plan=plan)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
