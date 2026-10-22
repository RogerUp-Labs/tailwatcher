import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const v0_23_0 = VersionInfo.of({
  version: '0.23.0:0',
  releaseNotes: {
    en_US:
      'Family accounts, finished: admins can make a sign-up link on the People page and text it to someone new. They open it, pick their own username and password, get a watcher of their own and are walked through getting alerts on their phone. Each link works once and expires. Forgot your password? "Forgot your password?" on the sign-in page sends a 6-digit code to your alerts in the ntfy app; type it with a new password, no admin needed.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
