import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_10_0 = VersionInfo.of({
  version: '0.10.0:0',
  releaseNotes: {
    en_US:
      'Share a trip with family: tick "Share with" on the trip form, or text "share 1 Mom & Dad". They get a note when you share, a heads-up if the departure time changes or the flight disappears (with an AeroDataBox key), and departure and landing alerts on the day, without your inbound-plane updates. No extra NTFY topic needed. The dashboard shows who each trip is shared with and what each watcher is following.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
