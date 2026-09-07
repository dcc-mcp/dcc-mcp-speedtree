from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.capabilities import inspect_asset


@skill_entry
def main(asset_path: str, preview_bytes: int = 512, **_kwargs):
    asset = inspect_asset(asset_path, preview_bytes=preview_bytes)
    return skill_success("SpeedTree asset inspected.", verified=True, asset=asset)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
