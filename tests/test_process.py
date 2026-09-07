import subprocess

import pytest
from dcc_mcp_core.cancellation import (
    CancelToken,
    DccMcpCancelledError,
    reset_cancel_token,
    set_cancel_token,
)

from dcc_mcp_speedtree.process import run_modeler


def test_core_cancellation_terminates_only_owned_child(monkeypatch):
    token = CancelToken()

    class Child:
        killed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def wait(self, timeout=None):
            if timeout is None:
                return -9
            token.cancel()
            raise subprocess.TimeoutExpired("modeler", timeout)

        def poll(self):
            return None

        def kill(self):
            self.killed = True

    child = Child()

    def spawn(argv, **kwargs):
        assert kwargs["shell"] is False
        return child

    monkeypatch.setattr(subprocess, "Popen", spawn)
    marker = set_cancel_token(token)
    try:
        with pytest.raises(DccMcpCancelledError):
            run_modeler(["modeler"], cwd=".", stdout=None, timeout=10)
    finally:
        reset_cancel_token(marker)
    assert child.killed


def test_cancel_before_launch_does_not_start_child(monkeypatch):
    token = CancelToken()
    token.cancel()
    monkeypatch.setattr(
        subprocess, "Popen", lambda *a, **k: pytest.fail("cancelled request launched a child")
    )
    marker = set_cancel_token(token)
    try:
        with pytest.raises(DccMcpCancelledError):
            run_modeler(["modeler"], cwd=".", stdout=None, timeout=10)
    finally:
        reset_cancel_token(marker)
