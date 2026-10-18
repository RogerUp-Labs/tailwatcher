import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_13_0 = VersionInfo.of({
  version: '0.13.0:0',
  releaseNotes: {
    en_US:
      'Settings in the Web UI: choose ntfy.sh, this server\'s NTFY or another server, and set the AeroDataBox key, feed, check interval, time zone, map buttons, text commands and page password, all from the dashboard. "Set up NTFY for me" configures this server\'s NTFY in one step with its admin password (used once, never saved): TailWatcher creates its own user and token and lets phones connect either without a login or with one NTFY login per person, which TailWatcher creates.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
