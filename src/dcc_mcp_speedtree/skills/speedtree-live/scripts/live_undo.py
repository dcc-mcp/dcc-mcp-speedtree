from dcc_mcp_core.skill import skill_entry, skill_error, skill_success

from dcc_mcp_speedtree import live


@skill_entry
def main(path, process_id=None, settle_seconds=3.0, **kwargs):
    try:
        result = live.undo(
            path,
            process_id,
            settle_seconds,
            session=kwargs.get(live.TRUSTED_SESSION_PARAM),
        )
    except live.LiveError as exc:
        payload = dict(exc.payload)
        error = payload.pop("error", "live_failed")
        payload.pop("message", None)  # str(exc) already supplies the message
        return skill_error(str(exc), error, **payload)
    # Reached only on a route whose scoped-target observation supplies a verified
    # FULL canonical active-document path. On the implemented pixels-only route
    # ``live.undo`` raises ``active_document_binding_unverified`` first, so the
    # ``except`` branch above always wins; this is the guarded engine, not a
    # claim that undo restores a file here.
    known = (
        f"Restored {result.get('restored')} from the history snapshot over {result.get('path')} "
        "on disk and delivered the reload command."
    )
    return skill_success(live.effect_message(result, action="reload", known=known), **result)


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
