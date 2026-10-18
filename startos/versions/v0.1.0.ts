import { IMPOSSIBLE, VersionInfo } from '@start9labs/start-sdk'

export const v0_1_0 = VersionInfo.of({
  version: '0.1.0:0',
  releaseNotes: {
    en_US:
      'First release: watch tail numbers on adsb.lol or adsb.fi and get NTFY alerts on takeoff (and optionally landing), with links to ADS-B Exchange.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
