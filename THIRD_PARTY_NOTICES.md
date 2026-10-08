The existing repository LICENSE is retained unchanged. It is not a license for
the supplied datasets, reference inputs, textures, or every vendored resource.

`backend/src/voxlush/voxel/resources/` reuses the actual user-supplied
`wooden_pipeline_20261006` builder primitives, material `COLORS` catalog,
two-view saved-voxel renderer, `architecture-evidence-3.1` geometry gate, and
`wooden_quality_v2` timber gate. Original filenames and SHA256 fingerprints are
recorded in `resources/provenance.json`. Their authorship and upstream license
were not stated in the supplied files; this project does not relabel them as
original work or infer that they are MIT licensed. Distribution rights for these
resources require clarification from their owner before public redistribution.

The builder adaptation adds general natural categories and multiple object
parents; the legacy quality gate only changes its import to the package-local
renderer. The renderer and timber checks retain their original behavior.
No private generated datasets or reference archive contents are included.

Python, NumPy, SciPy, Pillow and the Docker Python base image are separate
dependencies; their licenses remain with the upstream packages. The renderer
uses deterministic flat block colors, not bundled Minecraft game textures.
