import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'

export const current = VersionInfo.of({
  version: '0.24.1:0',
  releaseNotes: {
    en_US:
      'Fixes text commands and alerts stopping with "HTTP 401" when TailWatcher uses this server\'s NTFY. "Set up NTFY for me" asked NTFY for a token without saying how long it should last, and NTFY\'s default is 3 days, so everything stopped working 3 days after setup. It now asks for a token that never expires, and a token from an earlier setup that still works is made permanent when TailWatcher starts. If yours has already expired, run "Set up NTFY for me" in ⚙ Settings once more. A 401 now says the token was refused instead of pointing at topic access.',
  },
  migrations: {
    up: async () => {},
    down: IMPOSSIBLE,
  },
})
