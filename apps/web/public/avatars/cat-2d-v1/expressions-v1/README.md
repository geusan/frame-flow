# Original-illustration expression images

Created with the built-in `image_gen` tool using `../base.png` as the sole edit
target. The exact prompt set is in `prompts.json`; source/output hashes and the
generation filenames are in `provenance.json`.

The generated images are 1024×1536 aligned full-body expression variants. They are
retained intact as generated. The application uses only their facial region,
with the original head silhouette and body artwork retained by the renderer.
They are not 3D renders and have no dependency on the GLB avatar.

- `smile.png`: subtle closed-mouth smile.
- `laugh.png`: joyful laugh with closed eyes and open mouth.
- `surprise.png`: wide eyes and a small open mouth.
- `sad.png`: worried eyebrows and downturned mouth.
- `angry.png`: narrowed eyes and lowered eyebrows.
- `wink.png`: character-left wink (viewer right).
- `mouth-open.png`: isolated jaw opening for the webcam face rig; prompt in `mouth-open.prompt.json`.

Do not replace `../base.png`: the body masks and saved rig anchors depend on it.
Future artwork versions require a new asset identity and alignment review.
