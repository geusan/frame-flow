import assert from "node:assert/strict";
import { canRestoreExperiment } from "../../../packages/studio/src/features/nodes/experiment-restore.ts";
import { refreshReadyStatuses } from "../../../packages/studio/src/lib/canvas-model.ts";

const node = { data: { key: "character.image_to_3d", contractVersion: 3, status: "READY" } };
const definition = { execution: { executor: "character-turnaround-to-3d", revision: "tripo-turnaround-to-3d.v1" } };
const old = { node_key: node.data.key, execution_mode: "tripo-multiview-image-to-3d.v1+tripo-api-v3.2026-09" };
const current = { ...old, execution_mode: "tripo-turnaround-to-3d.v1+tripo-api-v3.2026-09" };
assert.equal(canRestoreExperiment(node, old, definition), false);
assert.equal(canRestoreExperiment(node, current, definition), true);
assert.equal(canRestoreExperiment(node, { ...current, node_key: "character.generate" }, definition), false);
assert.equal(canRestoreExperiment({ data: { ...node.data, status: "STALE" } }, current, definition), false);
assert.equal(canRestoreExperiment({ data: { ...node.data, status: "STALE", lastExperimentId: "exp_previous" } }, current, definition), true);
assert.equal(canRestoreExperiment(node, old, { execution: { executor: "legacy-compatibility" } }), true);
const cleared = refreshReadyStatuses([{ ...node, id: "replaced", data: { ...node.data, status: "STALE" } }], [])[0];
assert.equal(cleared.data.status, "STALE");
assert.equal(canRestoreExperiment(cleared, current, definition), false);
console.log("Experiment restore compatibility checks passed");
