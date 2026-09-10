"""Headless Blender visualization of unmodified Modeler-exported OBJ geometry.

This produces clearly labeled mesh renders, not Modeler UI screenshots.
Usage: blender --background --factory-startup --python this.py -- <stage-root> [render-folder]
"""

import hashlib
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def read_obj(path):
    vertices, faces = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("v "):
            vertices.append(tuple(map(float, line.split()[1:4])))
        elif line.startswith("f "):
            faces.append(tuple(int(part.split("/")[0]) - 1 for part in line.split()[1:]))
    if not vertices or not faces:
        raise ValueError("Modeler exported no geometry")
    return vertices, faces


def material(name, color):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1)
    result.use_nodes = True
    shader = result.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Roughness"].default_value = 0.72
    return result


def light(location, energy, size):
    data = bpy.data.lights.new("Studio light", "AREA")
    data.energy, data.shape, data.size = energy, "DISK", size
    obj = bpy.data.objects.new("Studio light", data)
    bpy.context.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (-obj.location).to_track_quat("-Z", "Y").to_euler()


def main():
    root = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    stages = json.loads((root / "showcase.json").read_text())["stages"]
    exports = json.loads((root / "exports/export-manifest.json").read_text())
    if exports["status"] != "exported" or len(exports["items"]) != len(stages):
        raise ValueError("Complete native exports before visualization")
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    output = root / (arguments[1] if len(arguments) > 1 else "renders")
    output.mkdir(exist_ok=False)
    geometry = [read_obj(root / "exports" / item["mesh"]) for item in exports["items"]]
    for stage, item in zip(stages, exports["items"]):
        source = root / stage["source"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["source"]["sha256"]:
            raise ValueError("Export does not match the saved stage source")
    for index, (stage, (vertices, faces)) in enumerate(zip(stages, geometry)):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        scene = bpy.context.scene
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 24
        scene.cycles.use_denoising = True
        scene.render.resolution_x, scene.render.resolution_y = 1000, 900
        scene.render.resolution_percentage = 100
        scene.world = bpy.data.worlds.new("Neutral studio")
        scene.world.use_nodes = True
        scene.world.node_tree.nodes["Background"].inputs[0].default_value = (0.14, 0.17, 0.15, 1)
        scene.world.node_tree.nodes["Background"].inputs[1].default_value = 0.45
        mesh = bpy.data.meshes.new("Unmodified Modeler OBJ")
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        obj = bpy.data.objects.new(stage["stage"], mesh)
        bpy.context.collection.objects.link(obj)
        bark = material("Display bark", (0.20, 0.12, 0.065))
        leaves = material("Display foliage", (0.22, 0.39, 0.055))
        mesh.materials.append(bark)
        mesh.materials.append(leaves)
        parent = list(range(len(vertices)))

        def find(value):
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        for face in faces:
            for vertex in face[1:]:
                parent[find(vertex)] = find(face[0])
        sizes = {}
        for vertex in range(len(vertices)):
            component = find(vertex)
            sizes[component] = sizes.get(component, 0) + 1
        for polygon in mesh.polygons:
            polygon.material_index = int(
                stage["species"] == "grass" or sizes[find(polygon.vertices[0])] <= 8
            )
            polygon.use_smooth = polygon.material_index == 0
        bounds = [[min(v[a] for v in vertices), max(v[a] for v in vertices)] for a in range(3)]
        height = 8.5 if stage["species"] == "willow" else 2.0
        center = Vector((0, 0, 4.1 if stage["species"] == "willow" else 0.25))
        camera_data = bpy.data.cameras.new("Orthographic")
        camera = bpy.data.objects.new("Orthographic", camera_data)
        bpy.context.collection.objects.link(camera)
        camera.location = center + Vector((0.8, -1.3, 0.4)) * height
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        camera_data.type, camera_data.ortho_scale = "ORTHO", height * 1.24
        scene.camera = camera
        light((height * 0.2, -height * 0.7, height * 1.2), 30 * height**2, height)
        light((-height, height * 0.3, height * 0.8), 15 * height**2, height * 0.8)
        bpy.ops.mesh.primitive_plane_add(
            size=height * 200, location=(0, 0, bounds[2][0] - height * 0.006)
        )
        bpy.context.object.data.materials.append(material("Display floor", (0.038, 0.054, 0.046)))
        scene.view_settings.view_transform = "AgX"
        destination = output / f"{index + 1:02d}-{stage['species']}-{stage['stage']}.png"
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(destination)
        bpy.ops.render.render(write_still=True)
        stage["geometry_validation"] = {
            "vertices": len(vertices),
            "faces": len(faces),
            "bounds": bounds,
            "obj_sha256": hashlib.sha256(
                (root / "exports" / exports["items"][index]["mesh"]).read_bytes()
            ).hexdigest(),
        }
        stage["render"] = destination.relative_to(root).as_posix()
        stage["presentation"] = (
            "Headless Blender mesh render with display materials; not a Modeler screenshot"
        )
        print(
            json.dumps({"stage": stage["stage"], "vertices": len(vertices), "faces": len(faces)}),
            flush=True,
        )
    (output / "readback.json").write_text(json.dumps(stages, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
