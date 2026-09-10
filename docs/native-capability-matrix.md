# Native capability coverage

Target: SpeedTree Modeler 10.1 on Windows. This inventory separates native
file access, official commands, and live Modeler commands. It does **not**
claim that every feature of the application has a callable authoring API.
No UI automation is used to fill native gaps.

## Entry points and evidence

| Product capability | Native entry | Exposed implementation | Evidence / remaining boundary |
| --- | --- | --- | --- |
| Generator inventory | SPM/STT `Generators` | `inspect_graph`, `inspect_authoring_catalog` | 51 installed templates parsed; 16 generator types |
| Generator create/copy/delete/name/visibility | Generator XML and GUIDs | `edit_graph` | Validated file operations; Modeler export required |
| Generator connections | `Links` with source/target GUIDs | Connect/disconnect, cycle and reference checks | Reloaded output graph; staged exports |
| Branches, fronds, leaves | Generator properties | All stored property/component names accessible | Willow and grass native export cases |
| Base, reference, mesh branch, conversion, stitches | Installed generator templates | Template instantiation and stored properties | Structure exposed; separate geometry recipes not yet validated |
| Caps, fins, knots, zones, decals, mesh detail, targets | Installed generator templates | Template instantiation and stored properties | Structure exposed; separate geometry recipes not yet validated |
| Batched leaves | Installed generator template | Template instantiation and stored properties | Structure exposed; separate geometry recipe not yet validated |
| Distribution and random seeds | `Generation:*`, `Random Seeds:*` properties | Existing scalar/component editing | Vendor enums/ranges are not published in the XML |
| Profile and parent curves | Stored spline control points | Existing scalar control-point editing | No arbitrary curve point insertion/deletion yet |
| Wind, seasons, growth, LOD, UVs, normals, vertex colors | Stored generator property groups | Existing generator fields accessible | Field readback does not prove dynamic evaluation or final quality |
| Fan, global lighting, document controls | Separate SPM objects | Preserved, not exposed for mutation | Needs a typed object contract and host evaluation tests |
| Materials, textures, meshes, displacements, asset sets | `Assets` and external files | Existing exports/sidecar inspection | No complete asset-authoring or material-assignment transaction |
| Forces, hand drawing, individual generated-node edits | Separate authoring state / node overrides | Existing state preserved where unaffected | No callable live authoring integration verified |
| Collision generation | Modeler operation / saved collision objects | No native command exposed | Requires a verified command bridge or documented SDK |
| Ambient occlusion computation | Modeler operation | No native command exposed | Same boundary; export is not an AO command |
| Save and reopen authoring files | SPM/STT files | Exclusive new-file writes and parse readback | Does not update an already open document |
| VFX and games export | Official `-export`, `-export_game`, `-export_options` | Export, status, cancellation, verification | Six supported output extensions; product/license dependent |
| Batch control | Owned Modeler child + Core jobs | Progress, timeout, active-job cancellation | No vendor-internal progress or session reconstruction |
| Interactive viewport, selection, undo/redo, timeline playback | Live Modeler UI state | No native bridge verified | CUA canceled; not replaced by input automation |
| Modeler screenshot/viewport rendering | No reviewed CLI command | Not exposed | Showcase visualization must label exported-geometry renders honestly |
| Engine integration | Exported ST/ST9 and destination importer | Verified handoff/preflight | Destination owns import and acceptance |
| Licensing, preferences, application updates | Vendor-owned lifecycle | Not exposed as authoring mutations | Not evidence of a missing generator API |

`inspect_authoring_catalog` generates the installed generator inventory rather
than hard-coding a list of node types. New or unreadable formats are reported
as failures. Property enumeration reports stored fields, including components
of curves; it does not infer undocumented property meanings or legal ranges.

## C++ / C# bridge boundary

The installed Modeler includes Qt libraries and external-DCC import scripts.
The reviewed installation contains no Modeler authoring headers, plugin SDK,
or documented command interface for live node mutations. Qt libraries are not
proof of an authoring API. The [Runtime SDK](https://docs.unity3d.com/speedtree-runtime-sdk)
is a separate runtime integration; an engine importer also cannot establish a
Modeler authoring interface.

A complete live bridge needs verified host commands and signatures, a version
handshake, main-thread dispatch, document/revision identity, typed arguments,
undo transactions, and authoritative post-operation state. Until that boundary
is available and tested, full native application coverage remains incomplete.
Adding a stub hook, guessed addresses, or synthetic success responses would
not close these gaps.

References: [Modeler manual](https://docs.unity3d.com/speedtree-modeler/manual/index.html),
[official command-line export](https://docs.unity3d.com/speedtree-modeler/manual/export-from-the-command-line.html),
[generator template commands](https://docs.unity3d.com/speedtree-modeler/manual/generation-editor-toolbar-reference.html).
