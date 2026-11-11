from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_speedtree import live


@skill_entry
def main(process_id=None, output_path=None, scale=0.6, **_kwargs):
    try:
        result = live.screenshot(process_id, output_path, scale)
    except live.LiveError as exc:
        return skill_error(str(exc), exc.payload.get("error", "live_failed"), **exc.payload)
    return skill_success("Modeler window captured; read the PNG to view it.", **result)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
