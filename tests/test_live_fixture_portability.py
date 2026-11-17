"""P2 regression: the live runtime fixture is portable across CI platforms.

The candidate's Linux CI failed because ``live_ui_harness.runtime()`` hard-coded
``C:/dcc-cua/dcc-cua.exe``, which is Windows-absolute but NOT POSIX-absolute.
Core validates with ``Path(binary).is_absolute()`` using the HOST pathlib, so on
Linux that spelling raised ``ValueError: UI Control binary must be an absolute
path`` before any test ran.

The fix derives the fixture from the host's own temp directory, so it is
absolute in the host's flavor on Windows and POSIX alike. A Windows-only pass is
not Linux acceptance, so this module ALSO proves the strategy is flavor-agnostic
by building an absolute fixture for each flavor as pure data, without launching
anything or relaxing Core's production validation.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

import live_ui_harness as harness
import pytest
from dcc_mcp_core.host.ui_control_options import UiControlRuntimeOptions


def _absolute_fixture(root: str, flavor: str) -> str:
    """The host-absolute strategy, evaluated for one path flavor as pure data."""
    if flavor == "posix":
        return str(PurePosixPath(root) / "dcc-cua" / "dcc-cua.exe")
    return str(PureWindowsPath(root) / "dcc-cua" / "dcc-cua.exe")


def test_strategy_is_absolute_in_both_path_flavors():
    """A temp-root-derived fixture is absolute on POSIX and Windows runners."""
    posix = _absolute_fixture("/tmp", "posix")
    windows = _absolute_fixture("C:/Temp", "windows")
    assert PurePosixPath(posix).is_absolute() is True
    assert PureWindowsPath(windows).is_absolute() is True
    # The historical hard-coded value fails exactly the POSIX flavor: this is the
    # documented root cause of the failing Linux CI run 43945625959.
    assert PurePosixPath("C:/dcc-cua/dcc-cua.exe").is_absolute() is False


def test_runtime_binary_is_host_absolute_and_never_executed():
    """Core validates the host's own path flavor; no artifact needs to exist."""
    options: UiControlRuntimeOptions = harness.runtime()
    assert Path(options.binary).is_absolute(), "the host's pathlib must accept it"
    # The integrity pin is unchanged and the spelling-only validation is honored:
    # a non-existent but absolute path is accepted, so no binary is launched.
    assert Path(options.binary).exists() is False
    assert options.binary == harness.host_binary_path()
    assert options.sha256 == "0" * 64
    assert options.transport == "owned_mcp_pixels"
    assert options.observation_mode == "pixels_only"


def test_runtime_binary_is_a_real_dcc_cua_path_shape():
    """The fixture still names the integrity-pinned dcc-cua executable."""
    assert harness.host_binary_path().replace("\\", "/").endswith("/dcc-cua/dcc-cua.exe")


def test_production_path_validation_is_not_relaxed():
    """Core still rejects a relative binary path; only the fixture value changed."""
    with pytest.raises(ValueError, match="absolute path"):
        harness.runtime(binary="relative/dcc-cua.exe")
    with pytest.raises(ValueError, match="sha256"):
        harness.runtime(sha256="not-hex")


def test_binary_path_is_derived_from_the_host_temp_dir():
    """The value is built from tempfile.gettempdir(), not a fixed drive letter."""
    import tempfile

    assert harness.host_binary_path() == str(
        Path(tempfile.gettempdir()) / "dcc-cua" / "dcc-cua.exe"
    )
    assert Path(harness.host_binary_path()).is_absolute()
