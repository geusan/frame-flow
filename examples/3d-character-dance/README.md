# 3D Character Dance example

This example demonstrates the first practical Frameflow MVP:

```text
known-good rigged GLB -> validation -> rig pass-through -----------+
                                                                  +-> retarget -> preview/final Blender renders
short dance MP4 -> video validation -> MediaPipe -> cleanup ------+
```

## 1. Start the isolated Blender runtime

Blender is not required on the host. Build the dedicated worker and start the Compose stack:

```bash
docker compose build blender-worker
docker compose up -d
docker compose exec blender-worker blender --version
```

The API and Temporal worker send retarget/render jobs to `blender-worker:8090` on the internal
Compose network. The Blender service is not published to a host port.

## 2. Verify Blender independently (optional)

The repository does not commit a large character binary. Build a tiny procedural humanoid, round
trip it through Blender GLB import/export, bake `known-motion.json`, and render a real H.264 MP4:

```bash
python scripts/validate_3d_character_motion.py --output output/3d-character-motion-spike
```

The command creates `fixture-character.glb`, `roundtrip-character.glb`, `animation.blend`,
`animated-character.glb`, `preview.mp4`, and `validation-summary.json` under the ignored `output/`
directory.

## 3. Run the Canvas workflow with a real dance clip

1. Start Frameflow with `docker compose up -d` (or `make up`).
2. Upload `output/3d-character-motion-spike/roundtrip-character.glb` in an Upload node and copy its
   Artifact ID.
3. Upload a short, rights-cleared MP4 where one full body is visible and copy its Artifact ID.
4. Replace both `REPLACE_WITH_...` values in `canvas-request.json` (Config and runtime entries).
5. Create the Canvas:

   ```bash
   curl -X POST http://localhost:8000/canvases \
     -H 'content-type: application/json' \
     --data-binary @examples/3d-character-dance/canvas-request.json
   ```

6. Open the returned Canvas ID, press **Run workflow**, and inspect each node's Artifact, progress,
   logs, and common Raw data tab.

For a fast first run, make the Preview node the only declared Primary output or use **Run this
step** after Retarget. The Final node renders 1080x1920 and is intentionally much slower.

`known-motion.json` is a lightweight deterministic retargeting fixture, not a substitute for the
real MediaPipe branch. It exists so Blender/rig regressions can be reproduced without a dance-video
download or a large committed model.

## 4. Use the Tripo character branch

Configure the write-only Tripo API key in **Settings → Tripo**, then build this character branch in
the Canvas:

```text
Character
  → Character Multiview Reference
  → Image to 3D · Tripo (P1, 20,000 faces)
  → 3D Asset Validation
  → Auto Rig · Tripo (biped, Mixamo)
  → Motion Retarget
```

The multiview node defaults map Frameflow's generated roles as follows:

```text
front_full → front
profile → left
back_three_quarter → back
three_quarter_full → right
```

Generation and Auto Rig are distinct cached Nodes. Changing a motion or render preset therefore
does not spend Tripo credits again for an unchanged character.
