# Active local web runtime

The web UI at `http://127.0.0.1:3000` currently runs **on the host**, because Docker's virtual disk is full and the existing web container cannot start. `video-canvas-web-1` is stopped. API/database/worker services were not changed or cleaned. Only specific caches from our earlier web builds were pruned; no unrelated images/volumes/user data were deleted.

Current command (run from repository root):

```sh
node node_modules/next/dist/bin/next start output/local-web-all-channels-runtime -p 3000 -H 127.0.0.1
```

The host process serves the complete build snapshot in `output/local-web-all-channels-runtime`; `deployment.json` records its build ID. Do not modify this snapshot while it is being served. Future changes should create a new complete snapshot, stop this host server and start the replacement. Do not launch Docker web on port 3000 while the host server owns it.

`compose.override.yaml` still describes the Docker fallback mounts in `output/local-web-mouth-runtime`. Those contents were also updated, only while the container was stopped, with a backup in `output/local-web-mouth-runtime-before-mouth-actions`. Returning to Docker requires resolving its disk capacity first, stopping the host web server, then starting web. Image rebuilds alone do not supersede these mounts. Earlier snapshots and backups are retained for rollback.

The current host snapshot includes all 51 MediaPipe motion channels. Docker fallback mounts still contain the earlier mouth-actions build; refresh them from the intended snapshot before returning to Docker.

Another session owns an IPv6-only server on [::1]:3000. Do not stop it as part of avatar work. Use http://127.0.0.1:3000 for this snapshot; localhost may resolve to that other app.
