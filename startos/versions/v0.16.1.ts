import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_16_1 = VersionInfo.of({
  version: '0.16.1:0',
  releaseNotes: {
    en_US:
      'Parked planes: once a plane has landed and stopped transmitting, the dashboard says Parked with when it was last seen instead of On the ground forever, and the Live map link only shows while the plane is actually on the radar.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
