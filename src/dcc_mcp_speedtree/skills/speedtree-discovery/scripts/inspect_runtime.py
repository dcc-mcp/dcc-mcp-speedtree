from __future__ import annotations

from dcc_mcp_core.skill import skill_entry, skill_success

from dcc_mcp_speedtree.capabilities import capability_status
from dcc_mcp_speedtree.runtime import bind_runtime


@skill_entry
def main(
    pid: int,
    window_handle: int,
    executable: str | None = None,
    version: str | None = None,
    **_kwargs,
):
    binding = bind_runtime(pid, window_handle, executable, version)
    return skill_success(
        "SpeedTree runtime inspected.",
        verified=True,
        postcondition={"method": "exact_process_and_window_binding", "verified": True},
        provider="dcc-mcp-speedtree",
        runtime=binding.as_dict(),
        capabilities=capability_status(),
    )


if __name__ == "__main__":
    from dcc_mcp_core.skill import run_main

    run_main(main)
