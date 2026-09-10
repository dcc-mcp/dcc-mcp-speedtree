"""Copy-on-write editing of the observed SpeedTree SPM/STT generator XML.

This is a file format integration, not a live Modeler API. Modeler must reopen
and regenerate each output before its geometry can be accepted.
"""

from __future__ import annotations

import base64
import copy
import gzip
import hashlib
import math
import re
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_XML_BYTES = 64 * 1024 * 1024
MAX_OPERATIONS = 256
_COMPONENT = re.compile(
    r"[A-Za-z_][A-Za-z_0-9]*(?:\[[1-9][0-9]*\])?(?:/[A-Za-z_][A-Za-z_0-9]*(?:\[[1-9][0-9]*\])?)*"
)


def _guid():
    return base64.b64encode(uuid.uuid4().bytes_le).decode("ascii")


def _text(element, tag, value):
    child = element.find(tag)
    if child is None:
        child = ET.SubElement(element, tag)
    child.text = str(value)


class GraphError(ValueError):
    """An invalid or unsupported graph edit; no output was written."""


class _NativeTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise GraphError("XML declarations with external or custom entities are unsupported")


class SpeedTreeGraph:
    def __init__(self, root, *, source=None, source_hash=None):
        self.root = root
        self.source = source
        self.source_hash = source_hash
        self.validate()

    @classmethod
    def load(cls, path):
        path = Path(path).expanduser().resolve(strict=True)
        if path.suffix.lower() not in {".spm", ".stt"} or not path.is_file():
            raise GraphError("Expected an SPM project or STT template")
        if path.stat().st_size > MAX_XML_BYTES:
            raise GraphError("Compressed document exceeds the size limit")
        raw = path.read_bytes()
        try:
            if raw.startswith(b"\x1f\x8b"):
                import io

                with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                    xml = stream.read(MAX_XML_BYTES + 1)
            else:
                xml = raw
            if len(xml) > MAX_XML_BYTES:
                raise GraphError("Expanded document exceeds the size limit")
            parser = ET.XMLParser(target=_NativeTreeBuilder(insert_comments=True))
            root = ET.fromstring(xml, parser=parser)
        except (OSError, EOFError, ET.ParseError) as exc:
            raise GraphError("Invalid SpeedTree compressed XML") from exc
        if root.tag != "SpeedTree" or root.get("Version") not in {"5", "8"}:
            raise GraphError(
                "Unsupported SpeedTree XML root/version; expected observed version 5 or 8"
            )
        return cls(root, source=path, source_hash=hashlib.sha256(raw).hexdigest())

    def _generators(self):
        parent = self.root.find("Generators")
        if parent is None:
            raise GraphError("Missing Generators section")
        return list(parent.findall("Generator"))

    def _links(self):
        return self.root.findall("Links/Link")

    def _node(self, node_id):
        matches = [g for g in self._generators() if g.findtext("GUID") == node_id]
        if len(matches) != 1:
            raise GraphError(f"Unknown or ambiguous generator ID: {node_id}")
        return matches[0]

    def validate(self):
        generators = self._generators()
        ids = [g.findtext("GUID") for g in generators]
        if not ids or any(not v for v in ids) or len(set(ids)) != len(ids):
            raise GraphError("Generator IDs must be nonempty and unique")
        trees = [g for g in generators if g.get("Type") == "Tree"]
        if len(trees) > 1 or (self.source and self.source.suffix.lower() == ".spm" and not trees):
            raise GraphError("An SPM must contain exactly one Tree generator")
        edges = set()
        link_ids = set(ids)
        children = {v: [] for v in ids}
        for link in self._links():
            source, target = link.findtext("SourceGUID"), link.findtext("TargetGUID")
            identity = link.findtext("GUID")
            if source not in children or target not in children:
                raise GraphError("Dangling generator link")
            if not identity or identity in link_ids or (source, target) in edges:
                raise GraphError("Duplicate or missing link identity")
            if self._node(target).get("Type") == "Tree":
                raise GraphError("Tree cannot have a parent")
            link_ids.add(identity)
            edges.add((source, target))
            children[source].append(target)
        indegree = dict.fromkeys(ids, 0)
        for _, target in edges:
            indegree[target] += 1
        queue = [n for n in ids if indegree[n] == 0]
        visited = 0
        while queue:
            node = queue.pop()
            visited += 1
            for child in children[node]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if visited != len(ids):
            raise GraphError("Generator graph contains a cycle")

    def inspect(self):
        return {
            "schema": "speedtree.generator-graph.v1",
            "integration": "experimental_file_graph",
            "format_version": self.root.get("Version"),
            "modeler_version": self.root.get("VersionString", "").strip(),
            "source_sha256": self.source_hash,
            "live_document_modified": False,
            "requires_modeler_regeneration": True,
            "generators": [
                {
                    "id": g.findtext("GUID"),
                    "name": g.findtext("Name"),
                    "type": g.get("Type"),
                    "level": g.findtext("Level"),
                    "hidden": g.findtext("Hidden") == "true",
                    "property_count": len(g.findall("Properties/*")),
                }
                for g in self._generators()
            ],
            "links": [
                {
                    "id": link.findtext("GUID"),
                    "source_id": link.findtext("SourceGUID"),
                    "target_id": link.findtext("TargetGUID"),
                }
                for link in self._links()
            ],
        }

    def properties(self, node_id):
        result = []

        def components(parent, prefix=""):
            values = {}
            counts = {}
            totals = {}
            for child in parent:
                totals[child.tag] = totals.get(child.tag, 0) + 1
            for child in parent:
                if not isinstance(child.tag, str) or child.tag == "Name":
                    continue
                counts[child.tag] = counts.get(child.tag, 0) + 1
                index = f"[{counts[child.tag]}]" if totals[child.tag] > 1 else ""
                path = prefix + child.tag + index
                if len(child):
                    values.update(components(child, path + "/"))
                else:
                    values[path] = child.text or ""
            return values

        for prop in self._node(node_id).findall("Properties/*"):
            result.append(
                {"name": prop.findtext("Name"), "kind": prop.tag, "components": components(prop)}
            )
        return result

    def _component(self, node_id, name, component):
        if not isinstance(component, str) or not _COMPONENT.fullmatch(component):
            raise GraphError("Invalid property component path")
        if component.split("/")[0].split("[")[0] == "Name":
            raise GraphError("Property identity is read-only")
        props = [
            p for p in self._node(node_id).findall("Properties/*") if p.findtext("Name") == name
        ]
        if len(props) != 1:
            raise GraphError(f"Unknown or ambiguous property: {name}")
        matches = props[0].findall(component)
        if len(matches) != 1 or len(matches[0]) or matches[0].attrib:
            raise GraphError("Component must resolve to one existing scalar leaf")
        return matches[0]

    def get_property(self, node_id, name, component="Value"):
        return self._component(node_id, name, component).text or ""

    def apply(self, operations):
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_OPERATIONS:
            raise GraphError("Provide 1..256 graph operations")
        candidate = copy.deepcopy(self)
        receipts = []
        for op in operations:
            if not isinstance(op, dict):
                raise GraphError("Each operation must be an object")
            receipts.append(candidate._apply_one(op))
            candidate.validate()
        candidate._update_levels()
        self.root = candidate.root
        return receipts

    def _connect(self, source, target):
        self._node(source)
        self._node(target)
        parent = self.root.find("Links")
        if parent is None:
            parent = ET.SubElement(self.root, "Links")
        link = ET.SubElement(parent, "Link")
        for tag, value in (
            ("SourceGUID", source),
            ("TargetGUID", target),
            ("Name", f"{self._node(source).get('Type')}->{self._node(target).get('Type')}"),
            ("GUID", _guid()),
            ("Hidden", "false"),
        ):
            _text(link, tag, value)
        ET.SubElement(link, "Extra")
        ET.SubElement(link, "Properties")

    def _apply_one(self, op):
        action = op.get("op")
        allowed = {
            "add": {"template_path", "template_node_id", "node_id", "name", "parent_id"},
            "duplicate": {"node_id", "new_id", "name", "parent_id"},
            "remove": {"node_id", "cascade"},
            "connect": {"source_id", "target_id"},
            "disconnect": {"source_id", "target_id"},
            "rename": {"node_id", "name"},
            "set_hidden": {"node_id", "hidden"},
            "set_property": {"node_id", "name", "component", "value"},
        }
        if action not in allowed or set(op) - allowed[action] - {"op"}:
            raise GraphError("Unsupported operation or unexpected fields")
        try:
            if action in {"add", "duplicate"}:
                if action == "add":
                    template = self.load(op["template_path"])
                    nodes = template._generators()
                    if "template_node_id" in op:
                        node = template._node(op["template_node_id"])
                    elif len(nodes) == 1:
                        node = nodes[0]
                    else:
                        raise GraphError("Select template_node_id for a multi-generator template")
                    new_id = op.get("node_id", _guid())
                else:
                    node = self._node(op["node_id"])
                    new_id = op.get("new_id", _guid())
                if node.get("Type") == "Tree":
                    raise GraphError("Cannot add or duplicate the Tree root")
                if not isinstance(new_id, str) or not 1 <= len(new_id) <= 128:
                    raise GraphError("New generator ID must be a bounded string")
                if any(ord(c) < 32 for c in new_id):
                    raise GraphError("Control characters are not allowed in generator IDs")
                clone = copy.deepcopy(node)
                _text(clone, "GUID", new_id)
                if "name" in op:
                    self._rename(clone, op["name"])
                self.root.find("Generators").append(clone)
                if op.get("parent_id"):
                    self._connect(op["parent_id"], new_id)
                return {"op": action, "node_id": new_id}
            if action in {"connect", "disconnect"}:
                source, target = op["source_id"], op["target_id"]
                if action == "connect":
                    self._connect(source, target)
                else:
                    matches = [
                        link
                        for link in self._links()
                        if link.findtext("SourceGUID") == source
                        and link.findtext("TargetGUID") == target
                    ]
                    if len(matches) != 1:
                        raise GraphError("Unknown or ambiguous connection")
                    self.root.find("Links").remove(matches[0])
                return {"op": action, "source_id": source, "target_id": target}
            node = self._node(op["node_id"])
            if action == "remove":
                if node.get("Type") == "Tree":
                    raise GraphError("Cannot remove the Tree root")
                if type(op.get("cascade", False)) is not bool:
                    raise GraphError("cascade must be boolean")
                remove = {op["node_id"]}
                while True:
                    children = {
                        link.findtext("TargetGUID")
                        for link in self._links()
                        if link.findtext("SourceGUID") in remove
                    }
                    if children - remove and not op.get("cascade", False):
                        raise GraphError("Generator has descendants; request cascade explicitly")
                    if not children - remove:
                        break
                    remove.update(children)
                for gen in self._generators():
                    if gen.findtext("GUID") in remove:
                        self.root.find("Generators").remove(gen)
                for link in self._links():
                    if {link.findtext("SourceGUID"), link.findtext("TargetGUID")} & remove:
                        self.root.find("Links").remove(link)
                cache = self.root.find("Nodes")
                if cache is not None:
                    for generated in list(cache):
                        if generated.findtext("GeneratorGUID") in remove:
                            cache.remove(generated)
                return {"op": action, "removed_ids": sorted(remove)}
            if action == "rename":
                self._rename(node, op["name"])
            elif action == "set_hidden":
                if type(op["hidden"]) is not bool:
                    raise GraphError("hidden must be boolean")
                _text(node, "Hidden", str(op["hidden"]).lower())
            elif action == "set_property":
                component = self._component(op["node_id"], op["name"], op.get("component", "Value"))
                value = op["value"]
                if not isinstance(value, (str, int, float, bool)):
                    raise GraphError("Property value must be scalar")
                text = str(value).lower() if isinstance(value, bool) else str(value)
                if len(text) > 4096 or any(ord(c) < 32 for c in text):
                    raise GraphError("Invalid property value")
                old = component.text or ""
                if old in {"true", "false"} and text not in {"true", "false"}:
                    raise GraphError("Boolean component requires true or false")
                try:
                    float(old)
                except ValueError:
                    pass
                else:
                    try:
                        finite = math.isfinite(float(text))
                    except ValueError:
                        finite = False
                    if not finite:
                        raise GraphError("Numeric component requires a finite number")
                component.text = text
            return {"op": action, "node_id": op["node_id"]}
        except KeyError as exc:
            raise GraphError(f"Missing operation field: {exc.args[0]}") from exc

    @staticmethod
    def _rename(node, name):
        if not isinstance(name, str) or not name.strip() or len(name) > 200:
            raise GraphError("Name must contain 1..200 characters")
        if any(ord(c) < 32 for c in name):
            raise GraphError("Control characters are not allowed in generator names")
        _text(node, "Name", name)

    def _update_levels(self):
        levels = {g.findtext("GUID"): 0 for g in self._generators()}
        for _ in levels:
            changed = False
            for link in self._links():
                source, target = link.findtext("SourceGUID"), link.findtext("TargetGUID")
                if levels[target] < levels[source] + 1:
                    levels[target] = levels[source] + 1
                    changed = True
            if not changed:
                break
        parents = {link.findtext("SourceGUID") for link in self._links()}
        for generator in self._generators():
            identity = generator.findtext("GUID")
            _text(generator, "Level", levels[identity])
            extra = generator.find("Extra")
            if extra is not None:
                _text(extra, "m_bHasDescendants", str(identity in parents).lower())

    def save(self, output_path):
        output = Path(output_path).expanduser().resolve()
        if output.suffix.lower() not in {".spm", ".stt"}:
            raise GraphError("Output must be an SPM or STT file")
        if output == self.source:
            raise GraphError("Output must differ from source")
        if self.source and output.suffix.lower() != self.source.suffix.lower():
            raise GraphError("Keep the source document type; an STT is not an SPM")
        self.validate()
        if self.source and hashlib.sha256(self.source.read_bytes()).hexdigest() != self.source_hash:
            raise GraphError("Source changed since inspection")
        payload = gzip.compress(
            ET.tostring(self.root, encoding="utf-8", xml_declaration=True), mtime=0
        )
        with output.open("xb") as stream:
            stream.write(payload)
        return {
            "path": str(output),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "live_document_modified": False,
            "requires_modeler_regeneration": True,
        }
