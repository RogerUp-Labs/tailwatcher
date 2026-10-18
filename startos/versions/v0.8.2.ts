import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_8_2 = VersionInfo.of({
  version: '0.8.2:0',
  releaseNotes: {
    en_US:
      'A Board theme for the Web UI: an airport departures board where your trips and watched aircraft sit on split-flap tiles that flip when a status changes. Switch between Modern and Board in the top corner; each browser remembers its choice.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
