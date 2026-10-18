import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_14_0 = VersionInfo.of({
  version: '0.14.0:0',
  releaseNotes: {
    en_US:
      'A searchable guide in the Web UI: ? Help opens it, with topics for getting started, connecting phones, text commands, trips, sharing and settings, a troubleshooting section, and a short "For people getting alerts" page you can copy and send to family. Help links next to Connect phone, trips and Settings open the right topic. The StartOS instructions use the same guide. Editing a watcher can now give them a new topic.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
