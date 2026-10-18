import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_4_0 = VersionInfo.of({
  version: '0.4.0:0',
  releaseNotes: {
    en_US:
      'Flight numbers: watch an airline flight as well as a tail number. Text "UA1234" (or "DL 89", "UAL1234") to your topic and the alert names the aircraft flying it, e.g. "UA1234 (N38473) departed". Entries can expire on their own: "UA1234 for 2 days", "add N12345 Vegas trip for 3d" or "UA1234 until fri"; you get a "Stopped watching" message when they do, and "list" shows the time left. Configure gains a Type (tail or flight) and an optional "Stop Watching After" (days) per entry. Existing settings carry over unchanged.',
  },
  migrations: {
    // kind and expires default to 'tail' and null via the schema.
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
