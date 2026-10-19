import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.16.0:0',
  releaseNotes: {
    en_US:
      'Round trips: enter your flight out and your flight home in one go, by text (inbound UA1234 11/14 return UA5678 11/21) or with the new Return flight row on + Add trip. Both flights are tracked as one trip: they\'re listed together, sharing covers both with a single note to family, and cancelling covers both unless you say only. return 1 UA5678 11/21 adds the flight home to a trip you already have. The return leaves from where the outbound lands unless you say otherwise. With AeroDataBox, a round trip booked a month ahead uses about 40 of the free plan\'s 400 monthly requests.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
