import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_21_1 = VersionInfo.of({
  version: '0.21.1:0',
  releaseNotes: {
    en_US:
      'Clearer "help" reply: the commands you can text TailWatcher are now grouped under headings, with trips first (your trips, changing a trip, sharing a trip) and watching a plane or flight after. The Text commands table in Help follows the same order.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
