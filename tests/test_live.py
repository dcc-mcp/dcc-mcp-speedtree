import gzip

import pytest

from dcc_mcp_speedtree import live
from dcc_mcp_speedtree.graph import SpeedTreeGraph


def write_tree(path, length="2"):
    xml = (
        '<SpeedTree Version="8"><Generators><Generator Type="Tree"><GUID>root</GUID>'
        "<Name>root</Name><Level>0</Level><Hidden>false</Hidden><Properties><SplineProperty>"
        f"<Name>Spine:Length:Absolute</Name><Value>{length}</Value></SplineProperty>"
        "</Properties></Generator></Generators></SpeedTree>"
    )
    path.write_bytes(gzip.compress(xml.encode()))
    return path


def length(path):
    props = SpeedTreeGraph.load(path).properties("root")
    return next(p for p in props if p["name"] == "Spine:Length:Absolute")["components"]["Value"]


class FakeModeler:
    def __init__(self, active="tree.spm", modal=None):
        self.active, self.modal, self.calls = active, modal, []

    def __call__(self, command, timeout=300, **params):
        self.calls.append((command, params.get("Menu"), params.get("Item")))
        if command == "status":
            inst = {"process_id": 7, "active_document": self.active, "modal_dialog": self.modal}
            return {"ok": True, "instances": [inst]}
        if command == "screenshot":
            return {"ok": True, "process_id": 7, "path": "shot.png"}
        return {"ok": True, "process_id": 7, "active_document": self.active}


SET_LENGTH = [
    {"op": "set_property", "node_id": "root", "name": "Spine:Length:Absolute", "value": 9}
]


def test_apply_saves_snapshots_edits_in_place_and_reloads(tmp_path, monkeypatch):
    tree = write_tree(tmp_path / "tree.spm")
    fake = FakeModeler()
    monkeypatch.setattr(live, "_run", fake)

    result = live.apply(tree, SET_LENGTH, settle_seconds=0)

    assert length(tree) == "9"
    assert length(result["history_snapshot"]) == "2"
    assert result["undo_depth"] == 1 and result["screenshot"] == "shot.png"
    commands = [c[0] for c in fake.calls]
    assert commands.index("menu") < commands.index("revert")
    assert ("menu", "File", "Save") in fake.calls
    assert not list(tmp_path.glob(".live_*"))


def test_undo_restores_previous_state_and_consumes_history(tmp_path, monkeypatch):
    tree = write_tree(tmp_path / "tree.spm")
    monkeypatch.setattr(live, "_run", FakeModeler())
    live.apply(tree, SET_LENGTH, settle_seconds=0)

    result = live.undo(tree, settle_seconds=0)

    assert length(tree) == "2"
    assert result["undo_depth"] == 0
    with pytest.raises(live.LiveError) as exc:
        live.undo(tree, settle_seconds=0)
    assert exc.value.payload["error"] == "no_history"


def test_failed_edit_leaves_file_and_history_untouched(tmp_path, monkeypatch):
    tree = write_tree(tmp_path / "tree.spm")
    before = tree.read_bytes()
    fake = FakeModeler()
    monkeypatch.setattr(live, "_run", fake)

    with pytest.raises(Exception):
        live.apply(tree, [{"op": "set_property", "node_id": "missing", "name": "x", "value": 1}])

    assert tree.read_bytes() == before
    assert not any(p.is_file() for p in tmp_path.rglob("*.spm") if p != tree)
    assert "revert" not in [c[0] for c in fake.calls]


@pytest.mark.parametrize(
    "fake, error",
    [
        (FakeModeler(active="other.spm"), "not_active"),
        (FakeModeler(modal="Warning"), "modal_dialog_open"),
    ],
)
def test_apply_refuses_when_modeler_is_not_ready(tmp_path, monkeypatch, fake, error):
    tree = write_tree(tmp_path / "tree.spm")
    monkeypatch.setattr(live, "_run", fake)

    with pytest.raises(live.LiveError) as exc:
        live.apply(tree, SET_LENGTH, settle_seconds=0)

    assert exc.value.payload["error"] == error
    assert [c[0] for c in fake.calls] == ["status"]
