import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.6.0:0',
  releaseNotes: {
    en_US:
      '"Where\'s my plane?" trip tracking. Text "inbound UA1234 N38473 dep 4:30pm" (your flight, the plane flying in for it from your airline app, and your departure time) and TailWatcher tells you when that plane takes off toward you, warns if its arrival gets close to your departure, and says when it lands. With an optional free AeroDataBox key (RapidAPI) in Configure, "inbound UA1234" finds the plane, its inbound flight and your departure time on its own, and re-checks before departure in case the plane changes. "trips" lists your trips and "cancel UA1234" stops one.',
  },
  migrations: {
    // aerodataboxKey defaults to empty via the schema; trips live in a new trips.json.
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
