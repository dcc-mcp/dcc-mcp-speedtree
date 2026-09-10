import gzip
import xml.etree.ElementTree as ET

import pytest

from dcc_mcp_speedtree.graph import GraphError, SpeedTreeGraph
from dcc_mcp_speedtree.node_tools import edit_graph, inspect_authoring_catalog


def document(path, generators, links="", extra=""):
    xml = f'<SpeedTree Version="8"><Generators>{generators}</Generators>{links}{extra}</SpeedTree>'
    path.write_bytes(gzip.compress(xml.encode()))
    return path


def node(identity, kind="Branch"):
    return f'''<Generator Type="{kind}"><GUID>{identity}</GUID><Name>{identity}</Name>
    <Level>0</Level><Hidden>false</Hidden><Extra><Unrecognized>keep</Unrecognized></Extra>
    <Properties><SplineProperty><Name>Spine:Length:Absolute</Name><Value>2</Value>
    <Variance>0</Variance><ProfileSpline><ControlPoint><X>0</X><Y>1</Y></ControlPoint>
    <ControlPoint><X>1</X><Y>0</Y></ControlPoint></ProfileSpline></SplineProperty>
    <Property><Name>Enabled</Name><Value>true</Value></Property></Properties></Generator>'''


@pytest.fixture
def files(tmp_path):
    source = document(
        tmp_path / "source.spm",
        node("root", "Tree"),
        extra="<VendorExtension><Value>untouched</Value></VendorExtension>",
    )
    template = document(tmp_path / "branch.stt", node("template"))
    return source, template, tmp_path / "edited.spm"


def test_add_connect_property_curve_and_reopen(files):
    source, template, output = files
    before = source.read_bytes()
    result = edit_graph(
        source,
        output,
        [
            {"op": "add", "template_path": str(template), "node_id": "trunk", "parent_id": "root"},
            {
                "op": "set_property",
                "node_id": "trunk",
                "name": "Spine:Length:Absolute",
                "value": 7.5,
            },
            {
                "op": "set_property",
                "node_id": "trunk",
                "name": "Spine:Length:Absolute",
                "component": "ProfileSpline/ControlPoint[2]/Y",
                "value": 0.15,
            },
            {"op": "rename", "node_id": "trunk", "name": "Willow trunk"},
        ],
    )
    reloaded = SpeedTreeGraph.load(output)
    assert reloaded.get_property("trunk", "Spine:Length:Absolute") == "7.5"
    assert (
        reloaded.get_property("trunk", "Spine:Length:Absolute", "ProfileSpline/ControlPoint[2]/Y")
        == "0.15"
    )
    assert reloaded.root.findtext("VendorExtension/Value") == "untouched"
    assert reloaded._node("trunk").findtext("Extra/Unrecognized") == "keep"
    assert result["graph"]["generators"][1]["level"] == "1"
    assert source.read_bytes() == before
    assert result["source_modified"] is False
    assert result["output"]["requires_modeler_regeneration"] is True


def test_failed_batch_rolls_back_graph(files):
    source, template, _ = files
    graph = SpeedTreeGraph.load(source)
    before = ET.tostring(graph.root)
    with pytest.raises(GraphError, match="Unknown"):
        graph.apply(
            [
                {"op": "add", "template_path": str(template), "node_id": "branch"},
                {"op": "set_property", "node_id": "branch", "name": "invented", "value": 2},
            ]
        )
    assert ET.tostring(graph.root) == before


def test_duplicate_independent_parameters_disconnect_and_cascade(files):
    source, template, _ = files
    graph = SpeedTreeGraph.load(source)
    graph.apply(
        [
            {"op": "add", "template_path": str(template), "node_id": "a", "parent_id": "root"},
            {"op": "duplicate", "node_id": "a", "new_id": "b", "parent_id": "a"},
            {"op": "set_property", "node_id": "b", "name": "Spine:Length:Absolute", "value": 3},
            {"op": "set_hidden", "node_id": "b", "hidden": True},
        ]
    )
    assert graph.get_property("a", "Spine:Length:Absolute") == "2"
    assert graph.get_property("b", "Spine:Length:Absolute") == "3"
    assert graph._node("b").findtext("Hidden") == "true"
    with pytest.raises(GraphError, match="descendants"):
        graph.apply([{"op": "remove", "node_id": "a"}])
    with pytest.raises(GraphError, match="cycle"):
        graph.apply([{"op": "connect", "source_id": "b", "target_id": "a"}])
    graph.apply(
        [
            {"op": "disconnect", "source_id": "a", "target_id": "b"},
            {"op": "connect", "source_id": "a", "target_id": "b"},
            {"op": "remove", "node_id": "a", "cascade": True},
        ]
    )
    assert len(graph.inspect()["generators"]) == 1
    assert not graph.inspect()["links"]


@pytest.mark.parametrize(
    "component,value",
    [
        ("../GUID", "hijack"),
        ("Name", "other"),
        ("Name[1]", "other"),
        ("Value", "nan"),
        ("Value", float("inf")),
        ("ProfileSpline/ControlPoint/Y", 2),
    ],
)
def test_invalid_scalar_or_path_rejected(files, component, value):
    source, _, _ = files
    graph = SpeedTreeGraph.load(source)
    with pytest.raises(GraphError):
        graph.apply(
            [
                {
                    "op": "set_property",
                    "node_id": "root",
                    "name": "Spine:Length:Absolute",
                    "component": component,
                    "value": value,
                }
            ]
        )


def test_output_and_source_fences(files):
    source, _, output = files
    graph = SpeedTreeGraph.load(source)
    with pytest.raises(GraphError, match="differ"):
        graph.save(source)
    graph.save(output)
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        graph.save(output)
    assert output.read_bytes() == before
    source.write_bytes(source.read_bytes() + b"changed")
    with pytest.raises(GraphError, match="Source changed"):
        graph.save(output.parent / "other.spm")


@pytest.mark.parametrize(
    "xml",
    [
        b'<SpeedTree Version="99"><Generators/></SpeedTree>',
        b'<!DOCTYPE x [<!ENTITY a "x">]><SpeedTree/>',
        '<!DOCTYPE x [<!ENTITY a "x">]><SpeedTree/>'.encode("utf-16"),
        b"not xml",
    ],
)
def test_reject_unknown_and_unsafe_xml(tmp_path, xml):
    path = tmp_path / "bad.spm"
    path.write_bytes(gzip.compress(xml))
    with pytest.raises(GraphError):
        SpeedTreeGraph.load(path)


def test_decompression_limit(tmp_path, monkeypatch):
    monkeypatch.setattr("dcc_mcp_speedtree.graph.MAX_XML_BYTES", 1024)
    path = tmp_path / "bomb.spm"
    path.write_bytes(gzip.compress(b" " * 1025))
    with pytest.raises(GraphError, match="Expanded"):
        SpeedTreeGraph.load(path)


def test_duplicate_identity_dangling_link_and_root_removal(files):
    source, template, _ = files
    graph = SpeedTreeGraph.load(source)
    with pytest.raises(GraphError):
        graph.apply([{"op": "add", "template_path": str(template), "node_id": "root"}])
    with pytest.raises(GraphError):
        graph.apply([{"op": "connect", "source_id": "root", "target_id": "missing"}])
    with pytest.raises(GraphError, match="root"):
        graph.apply([{"op": "remove", "node_id": "root"}])
    with pytest.raises(GraphError, match="Control"):
        graph.apply([{"op": "add", "template_path": str(template), "node_id": "invalid\x00id"}])


def test_installed_catalog_reports_failures_without_claiming_full_coverage(tmp_path):
    folder = tmp_path / "templates"
    folder.mkdir()
    document(folder / "branch.stt", node("branch"))
    (folder / "unreadable.stt").write_bytes(b"unsupported vendor format")
    catalog = inspect_authoring_catalog(tmp_path)
    assert catalog["inspected_templates"] == 1
    assert catalog["generator_types"][0]["type"] == "Branch"
    assert catalog["generator_types"][0]["property_names"] == ["Enabled", "Spine:Length:Absolute"]
    assert catalog["failures"][0]["template"] == "templates/unreadable.stt"
    assert catalog["all_modeler_capabilities_exposed"] is False
