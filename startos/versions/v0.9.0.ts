import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_9_0 = VersionInfo.of({
  version: '0.9.0:0',
  releaseNotes: {
    en_US:
      'Edit from the Web UI: add, edit and remove watchers, their aircraft and flights (with nickname and stop-after days), and trips (flight, date, departure time, airport and the plane flying in). Trips added on the page get the same AeroDataBox lookup and alerts as the "inbound" text command, and every edit appears in the activity feed. Edits are only accepted from the TailWatcher page itself.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
