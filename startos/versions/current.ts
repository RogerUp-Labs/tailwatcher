import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'
import { configJson, rawConfigJson } from '../fileModels/config.json'

export const current = VersionInfo.of({
  version: '0.12.0:0',
  releaseNotes: {
    en_US:
      'Much easier setup: alerts can now go through the public ntfy.sh service, so new installs need no NTFY package, users or tokens. Add a watcher on the Web UI (TailWatcher picks an unguessable topic) and tap "Connect phone" to send that person a one-tap subscribe link for the ntfy app. Choose between ntfy.sh, this server\'s NTFY or a custom server in Configure. Existing installs keep using this server\'s NTFY exactly as before.',
  },
  migrations: {
    // Every install before 0.12 used this server's NTFY; keep it that way.
    up: async ({ effects }) => {
      const raw = await rawConfigJson.read().once()
      if (raw && !('ntfyServer' in raw)) {
        await configJson.merge(effects, { ntfyServer: 'local' })
      }
    },
    down: IMPOSSIBLE,
  },
})
