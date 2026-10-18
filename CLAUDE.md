# TailWatcher

Headless StartOS 0.4 service: watches tail numbers on free ADS-B feeds and pushes NTFY alerts on takeoff (optionally landing), with links to ADS-B Exchange. Config is a list of **watchers** (name, NTFY topic, aircraft list, landing toggle, priority); each tail is polled once and fanned out to every watcher following it.

## Layout

- `app/tailwatcher.py` — the watcher (Python stdlib only). Reads `/data/config.json`, keeps per-aircraft state in `/data/state.json`, serves `/health` on :8080, publishes JSON to `$NTFY_URL`.
- `app/test_tailwatcher.py` — unit tests for the state machine and message builder (`make test`).
- `Dockerfile` — python:3.12-alpine; bakes a trimmed OurAirports CSV for "nearest airport".
- `startos/` — StartOS package (SDK 1.5.2, same as the homebrew-suite packages). `actions/configure.ts` is the settings form, written to `config.json` via `fileModels/config.json.ts`; `main.ts` resolves NTFY's bridge address and restarts on config change.

## Build

- `make x86` → `tailwatcher_x86_64.s9pk` (docker build of `start9/tailwatcher/main:0.2.0`, then `start-cli s9pk pack`). No buildx on this machine, so aarch64 isn't built.
- Packing needs a git commit (it records the hash) and the `assets/` dir.
- `make install` sideloads to the host in `~/.startos/config.yaml`.

## Gotchas

- NTFY on StartOS is deny-all. TailWatcher needs a publisher token from NTFY → Provision Publisher (topic `tailwatcher*` covers every watcher); SDK 1.5.2 can't call that action cross-package, so the user pastes it into Configure.
- Publish failures: transient ones (network, 429, 5xx) go to a per-delivery retry queue in `state.json` `_retry` (30 min), so other watchers never get duplicates; 4xx refusals aren't retried and show in health.
- Config format changed in 0.2.0 (top-level `aircraft`/`ntfyTopic` → `watchers`). `versions/current.ts` migrates on update, and `load_config` in Python also accepts the old format.
- The Configure form nests a list (aircraft) inside a list item (watcher). The SDK types allow it; check it renders well in the StartOS UI before relying on deeper nesting.
- Dependency title/icon only show if `manifest.dependencies.ntfy.s9pk` points at a real NTFY s9pk; a `metadata` block is ignored by start-cli.
- airplanes.live now requires approval (403); data sources are adsb.lol and adsb.fi. Both rate-limit (~1 req/s); the watcher backs off on 429.
- Detection: ground→air = "departed"; first seen airborne after 20+ min unseen = "is airborne" (small fields lack ground coverage).
