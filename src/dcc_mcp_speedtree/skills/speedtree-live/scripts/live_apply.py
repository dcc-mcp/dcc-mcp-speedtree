from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_speedtree import live


@skill_entry
def main(path, operations, process_id=None, settle_seconds=3.0, **_kwargs):
    try:
        result = live.apply(path, operations, process_id, settle_seconds)
    except live.LiveError as exc:
        return skill_error(str(exc), exc.payload.get("error", "live_failed"), **exc.payload)
    return skill_success(
        "Change applied and reloaded in the Modeler; read the screenshot PNG and ask the user.",
        **result,
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
