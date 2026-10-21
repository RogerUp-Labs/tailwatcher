import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.21.0:0',
  releaseNotes: {
    en_US:
      'Trips come first: a watcher can now send plane-spotting alerts (the tail and flight numbers they watch) to a separate Planes topic, so their main topic carries only trips, shared trips and replies. Turn it on with "Separate topic for plane alerts" when editing a watcher in the Web UI, then subscribe with the second link in Connect phone. Text commands work in either topic. Nothing changes until you turn it on.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
