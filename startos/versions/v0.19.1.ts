import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_19_1 = VersionInfo.of({
  version: '0.19.1:0',
  releaseNotes: {
    en_US:
      'Fixed a misleading "can\'t read topic (HTTP 403)" message for new watchers on this server\'s NTFY: it told you to grant access on tailwatcher*, but watcher topics now start with tw-. The message now names the right permission and points to "Set up NTFY for me" in ⚙ Settings, which now also covers topics made by older versions.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
