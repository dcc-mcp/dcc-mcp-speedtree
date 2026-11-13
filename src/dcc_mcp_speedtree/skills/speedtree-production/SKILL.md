---
name: speedtree-production
description: Create a separate editable SpeedTree project from a permitted reference and explicit generator edits, with an auditable production brief; visual and geometry acceptance require independent review.
license: MIT
metadata:
  dcc-mcp:
    dcc: speedtree
    layer: domain
    version: "0.1.0"
    tools: tools.yaml
    search-hint: "SpeedTree reference production tree project generator branches leaf cards triangle budget"
---

# Reference-based tree authoring

Use a reference project and assets that the operator is allowed to copy. First
inspect the reference graph, generator IDs, stored properties and dependencies
with `inspect_graph` and `inspect_properties`. Build explicit `edit_graph`
operations using only observed IDs and property paths. `production_generate`
applies those operations to a separate project in a new output directory, and
records the supplied brief and operations for review. It does not modify the
source project. Failures and unsupported fields must be reported rather than
silently treated as successful edits.

The `brief` object can describe `dependencies` (paths relative to the source
project directory), `references` (an object describing visual references),
`roles` (role names mapped to arrays of generator IDs), `budgets` (total and
card triangle targets), and `seed`. These are user-supplied context, not
automatic proof of geometry or appearance. In particular, a recorded seed is
not applied to the Modeler: set a known seed property explicitly in the
operation list if the project supports it. Reference images are not analyzed
or fitted automatically. Make no unsupported assumptions about a property's
visual effect or per-instance branch/card edits.

The candidate copies caller-declared dependencies and the observed `Assets`
`TexFilename` paths. Other asset reference formats are not comprehensively
discovered, so a successful copy is not proof that all assets resolve. All
copied paths must stay inside the reference project directory. Record a role
only after inspecting its generator identity and type; role checks verify graph
structure, not how geometry looks when regenerated.

For the example in issue #14, map the trunk, primary branches, limited
secondary branches and up to two leaf/fine-branch card variants explicitly.
The requested 2,000 total triangles and 800 combined card triangles are
example user budgets, not universal limits. Specify the desired units,
dimensions and budgets in the brief. Inspect any reported missing dependencies,
unsupported fields and saved manifest before continuing.

Stored graph readback does not prove regenerated geometry. Export the new
project using the official Modeler CLI and independently inspect the exported
mesh, units, category mapping and texture paths. Inspect bare-tree and full-tree
front/back/left/right views as well as card close-ups. Identify each view's
camera and whether it is a native Modeler view or a diagnostic render. Have an
artist compare the results with the supplied references. Numeric budget
compliance alone does not establish visual or production acceptance.

Use `validate_obj_budget` for independent readback of an exported Wavefront OBJ.
Supply a mapping from each `usemtl` name to a category and set the requested
limits, for example `{"cards": {"min": 800, "max": 800}}` with a total
maximum of 2000. Unmapped faces cause an `unverified` result unless a known
limit has already failed. A `passed` result applies only to the supplied OBJ
and mapping; it does not prove the OBJ came from the candidate, that material
names correspond to generator roles, or that an artist approved the tree.

The workflow does not provide a native live Modeler editing API, material
authoring, automatic reference matching or per-branch/per-card overrides. Use
the existing documented export and UI workflows for operations outside its
verified scope.
