from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.unreal import inspect_unreal_project


@skill_entry
def main(project_file: str, **_kwargs):
    project = inspect_unreal_project(project_file)
    return skill_success("Unreal SpeedTree preflight completed.", verified=True, project=project)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
