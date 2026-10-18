import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_8_0 = VersionInfo.of({
  version: '0.8.0:0',
  releaseNotes: {
    en_US:
      'Web UI: a dashboard of your trips (route, departure, the plane flying in and how far along it is), every watcher\'s aircraft with what\'s airborne now, recent alerts and text commands, and system status. Open it from the Web UI interface and log in with any username and the password from "Show Web UI Password". Read-only for now; changes still go through text commands or Configure.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
