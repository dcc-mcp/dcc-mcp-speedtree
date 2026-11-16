from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_speedtree import live


@skill_entry
def main(process_id=None, settle_seconds=3.0, **kwargs):
    try:
        result = live.revert(
            process_id,
            settle_seconds,
            session=kwargs.get(live.TRUSTED_SESSION_PARAM),
        )
    except live.LiveError as exc:
        payload = dict(exc.payload)
        error = payload.pop("error", "live_failed")
        payload.pop("message", None)  # str(exc) already supplies the message
        return skill_error(str(exc), error, **payload)
    known = "Delivered the revert command to the bound Modeler window."
    return skill_success(live.effect_message(result, action="revert", known=known), **result)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
