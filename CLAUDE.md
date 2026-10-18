# TailWatcher

Headless StartOS 0.4 service: watches tail numbers and airline flight numbers on free ADS-B feeds and pushes NTFY alerts on takeoff (optionally landing), with links to ADS-B Exchange. Config is a list of **watchers** (name, NTFY topic, aircraft list, landing toggle, priority); each tail/callsign is polled once and fanned out to every watcher following it. Aircraft entries are `{tail, label, kind: 'tail'|'flight', expires: unix|null}` (`tail` holds the flight number for flights).

## Layout

- `app/tailwatcher.py` — the watcher (Python stdlib only). Reads `/data/config.json`, keeps per-aircraft state in `/data/state.json`, serves `/health` on :8080, publishes JSON to `$NTFY_URL`.
- `app/flights.py` — IATA→ICAO airline map, `parse_flight()` (the tail-vs-flight rule), callsign matching on the trimmed `flight` field.
- `app/commands.py` — text commands: one ntfy JSON stream per watcher topic (`TopicListener`), `parse()` (incl. expiry phrases), `apply_command()` and `remove_expired()`, which edit `config.json` under `CONFIG_LOCK`. The entry shape must match `startos/fileModels/config.json.ts`. Messages tagged with `OWN_TAGS` (airplane, airplane_arriving, robot, test_tube) are TailWatcher's own and ignored, so keep every published message tagged.
- `app/lookup.py` — the `info N12345` command: FAA N-number page (parsed from HTML via `data-label` cells), hexdb.io, live feed (adsb.fi) and planespotters.net photo, fetched in parallel; each source optional. Replies show owner city/state only, never street. planespotters requires a contact URL in the User-Agent (USER_AGENT has one) and photo credit in the message. The FAA site rejects non-browser user agents, hence FAA_UA.
- `app/test_*.py` — unit tests (`make test`); `app/testdata/faa_N17169.html` is a real FAA page for the parser test.
- `Dockerfile` — python:3.12-alpine; bakes a trimmed OurAirports CSV for "nearest airport".
- `startos/` — StartOS package (SDK 1.5.2, same as the homebrew-suite packages). `actions/configure.ts` is the settings form, written to `config.json` via `fileModels/config.json.ts`; `main.ts` resolves NTFY's bridge address; the watcher hot-reloads `config.json` by mtime (Configure and text commands both write it), so config changes don't restart the service.

## Build

- `make x86` → `tailwatcher_x86_64.s9pk` (docker build of `start9/tailwatcher/main:0.5.0`, then `start-cli s9pk pack`). No buildx on this machine, so aarch64 isn't built.
- Packing needs a git commit (it records the hash) and the `assets/` dir.
- `make install` sideloads to the host in `~/.startos/config.yaml`.

## Gotchas

- `info` runs in the topic listener thread, outside CONFIG_LOCK; `apply_command` returns (None, False) for it. `on_info` lives inside `run()` in tailwatcher.py, so a missing module import only fails live; `test_lookup` checks the import.
- Text commands need `pkg_tailwatcher` Read-Write on `tailwatcher*` (Provision Publisher only grants write); a 403 on the stream shows in health and retries every 60s.
- NTFY on StartOS is deny-all. TailWatcher needs a publisher token from NTFY → Provision Publisher (topic `tailwatcher*` covers every watcher); SDK 1.5.2 can't call that action cross-package, so the user pastes it into Configure.
- Publish failures: transient ones (network, 429, 5xx) go to a per-delivery retry queue in `state.json` `_retry` (30 min), so other watchers never get duplicates; 4xx refusals aren't retried and show in health.
- Config format changed in 0.2.0 (top-level `aircraft`/`ntfyTopic` → `watchers`). `versions/current.ts` migrates on update, and `load_config` in Python also accepts the old format.
- The Configure form nests a list (aircraft) inside a list item (watcher). The SDK types allow it; check it renders well in the StartOS UI before relying on deeper nesting.
- Dependency title/icon only show if `manifest.dependencies.ntfy.s9pk` points at a real NTFY s9pk; a `metadata` block is ignored by start-cli.
- airplanes.live now requires approval (403); data sources are adsb.lol and adsb.fi. Both rate-limit (~1 req/s); the watcher backs off on 429.
- Detection: ground→air = "departed"; first seen airborne after 20+ min unseen = "is airborne" (small fields lack ground coverage).
- Flights are polled by callsign (`/v2/callsign/{CS}` on both adsb.lol and adsb.fi) and state is keyed by callsign, so "UA1234" and "UAL1234" are one entry. Tail-vs-flight rule lives in `flights.parse_flight` (dash or N+digit → tail; 3 letters+digits or a known IATA code+1–4 digits → flight; else tail). New Python modules must be added to the Dockerfile `COPY` line.
- Expiry: the watcher calls `remove_expired()` at the top of each cycle and posts "⌛ Stopped watching X (expired)"; `load_config` also skips expired entries. "until fri" = 3am the next day in `timeZone` (Configure, default America/New_York); the container is UTC, so never use the container date. The Configure form shows `expiresDays`; saving it unchanged keeps the stored `expires`.
