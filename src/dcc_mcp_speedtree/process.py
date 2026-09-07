"""Wait for one owned Modeler process with the core cancellation contract."""

import subprocess
import time

from dcc_mcp_core.cancellation import check_cancelled


def run_modeler(argv, *, cwd, stdout, timeout):
    check_cancelled()
    with subprocess.Popen(
        argv, cwd=cwd, stdout=stdout, stderr=subprocess.STDOUT, shell=False
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
