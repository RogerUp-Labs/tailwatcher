import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.24.0:0',
  releaseNotes: {
    en_US:
      'Trip reminders and lighter use of the free AeroDataBox plan. Each watcher can now get a reminder 1, 2 or 3 days or a week before each trip, with the flight, time and plane (Edit the watcher → Trip reminder; off unless you turn it on). Far-off trips are now checked weekly until 3 days out instead of daily for the last two weeks, cutting a typical flight from about 26 lookups to 16. ⚙ Settings and the System panel show how much of this month\'s AeroDataBox allowance is left, and a lookup that fails now waits before trying again instead of retrying every minute.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
