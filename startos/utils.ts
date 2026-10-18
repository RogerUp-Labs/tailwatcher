import { T } from '@start9labs/start-sdk'
import { sdk } from './sdk'

/** Port of the watcher's internal /health endpoint (not exported as an interface). */
export const healthPort = 8080

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
