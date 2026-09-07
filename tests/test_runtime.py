import pytest

from dcc_mcp_speedtree.runtime import SpeedTreeRuntimeError, bind_runtime


class Inspector:
    def validate_window(self, pid, hwnd):
        assert pid == 42 and hwnd == 99

    def process_path(self, pid):
        from pathlib import Path

        return Path("C:/SpeedTree/SpeedTree.exe")


def test_bind_runtime():
    b = bind_runtime(42, 99, inspector=Inspector(), version="9.0")
    assert b.pid == 42 and b.version == "9.0"


def test_window_owner_failure_cannot_be_overridden_with_title():
    class WrongWindow(Inspector):
        def validate_window(self, pid, hwnd):
            raise SpeedTreeRuntimeError("HWND belongs to a different process")

    with pytest.raises(SpeedTreeRuntimeError, match="different process"):
        bind_runtime(42, 99, title="SpeedTree", inspector=WrongWindow())
