"""Wait for one owned Modeler process with the core cancellation contract."""

import os
import subprocess
import time

from dcc_mcp_core.cancellation import check_cancelled


def run_modeler(argv, *, cwd, stdout, timeout):
    check_cancelled()
    with subprocess.Popen(
        argv,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=stdout,
        stderr=subprocess.STDOUT,
        shell=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    ) as process:
        deadline = time.monotonic() + timeout
        try:
            while True:
                check_cancelled()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(argv, timeout)
                try:
                    return subprocess.CompletedProcess(
                        argv, process.wait(timeout=min(0.25, remaining))
                    )
                except subprocess.TimeoutExpired:
                    continue
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
