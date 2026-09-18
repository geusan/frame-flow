# Cat 2D v1

`base.png` is the prop-free A-pose illustration generated in this task from the
user's existing cat-character reference. It contains painted colors/shading and
no bag or bag straps. Its pixel layout is fixed at 1024×1536.

`reference-motion.json` is derived locally from the user-supplied video Artifact
`art_d78356242bc4494495` (SHA-256 recorded in the file), using MediaPipe Holistic.
It is a sample performance, not source webcam data or a production Workflow node.
Part masks and rig defaults are authored under `src/features/avatar-2d`.
