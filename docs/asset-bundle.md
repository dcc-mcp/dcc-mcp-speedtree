# Asset bundle contract v1

`export-manifest.json` uses `schema: speedtree.export-batch.v1`. File paths in
`items[].mesh`, `items[].files[].path`, and material maps are relative to the
manifest directory. Move the whole bundle; resolve paths under that directory
and reject traversal. The tool response includes a local absolute manifest path.

The producer records exporter/source/preset SHA256 and byte counts, requested
format and preset mode, requested transform settings, requested tree count,
per-item status/exit code, and an inventory of emitted files. These hashes
identify inputs and detect changes; they do not certify licensing or trust.
Each successful item has a recognizable mesh header and nonempty output.
STMAT material records preserve map semantics and two-sided flags without
copying vendor `Source` paths into the manifest. Binary references still need
the target importer. Raw vendor sidecars are kept unchanged locally.

`status: exported` and `verify_export.verified: true` mean file-level checks
passed. `target_validation.status: not_run` is deliberately independent.
`dependencies.status` is `sidecar_verified` when explicit STMAT File references
exist, otherwise `requires_target_importer`. It never asserts full binary
texture dependency coverage. Preset unit/axis settings are requests; a target
must read its effective world bounds, units, and transforms back.

## Consumer contract

A destination adapter should consume the resolved mesh and adjacent files,
import into a new destination by default, and produce a separate receipt keyed
by manifest hash and mesh hash. Include target application/version, importer
and plugin state, imported object identifiers, geometry/LOD counts, material
slots, missing references, effective transform, warnings, and per-feature
`verified`, `converted`, `unsupported`, or `not_checked` results. Do not rewrite
the producer manifest to turn file validation into target validation.

Use the target adapter's typed capability discovery rather than embedding
application commands in this package. Example routes: Unreal asset import for
ST9/ST, Blender interchange import for FBX/OBJ/Alembic/USD, and the discovered
Maya or 3ds Max importer for a compatible format. Missing plugins yield a
reviewable configuration plan; apply only within the target's user consent
contract. Importing a mesh never restores the editable SpeedTree generator.
