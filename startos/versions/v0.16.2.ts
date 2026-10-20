import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_16_2 = VersionInfo.of({
  version: '0.16.2:0',
  releaseNotes: {
    en_US:
      'Where is it now: each aircraft on the dashboard shows its approximate location next to Live map, like "near Denver, CO" or "40 nm NE of Denver, CO", and "at" the airport when it is on the ground. A plane that has gone quiet shows where it was last seen.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
