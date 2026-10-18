import { T } from '@start9labs/start-sdk'
import { sdk } from './sdk'

/** The watcher's web server: the Web UI (password-protected) and /health. */
export const webPort = 8080
export const healthPort = webPort

/** Used when NTFY has not published a bridge address (older StartOS builds). */
export const ntfyFallbackUrl = 'http://ntfy.startos:80'

/**
 * NTFY's address on the server's internal bridge network. Read with `.const()`
 * from main so TailWatcher restarts if NTFY's address changes.
 */
export const ntfyUrl = (effects: T.Effects) =>
  sdk.serviceInterface.get(
    effects,
    { packageId: 'ntfy', id: 'ui' },
    (i) =>
      i?.addressInfo
        ?.filter({ kind: 'bridge', predicate: (h) => !h.ssl })
        .format()[0] ?? null,
  )
