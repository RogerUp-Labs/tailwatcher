import { T, utils } from '@start9labs/start-sdk'
import { sdk } from './sdk'

/** The watcher's web server: the Web UI (password-protected) and /health. */
export const webPort = 8080
export const healthPort = webPort

/** Used when NTFY has not published a bridge address (older StartOS builds). */
export const ntfyFallbackUrl = 'http://ntfy.startos:80'

export const publicNtfy = 'https://ntfy.sh'

/** An unguessable topic like "tw-dad-k3j9…" (see newTopic in app/edits.py). */
export const newTopic = (name: string) =>
  `tw-${name.toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 12) || 'watcher'}-` +
  utils.getDefaultString({ charset: 'a-h,j-k,m-n,p-z,2-9', len: 20 })

/**
 * TailWatcher's own public HTTPS address (e.g. via StartTunnel), for invite
 * links that work away from home. Null if it only has LAN addresses.
 */
export const ownPublicUrl = (effects: T.Effects) =>
  sdk.serviceInterface.getOwn(effects, 'ui', (i) =>
    i?.addressInfo
      ?.filter({ visibility: 'public', predicate: (h) => h.ssl })
      .format()[0] ?? null,
  )

/**
 * The address phones use to reach this server's NTFY, for "Connect phone"
 * links: a public HTTPS domain if NTFY has one, else its LAN HTTPS address.
 */
export const ntfyPhoneUrl = (effects: T.Effects) =>
  sdk.serviceInterface.get(effects, { packageId: 'ntfy', id: 'ui' }, (i) => {
    const info = i?.addressInfo
    if (!info) return null
    const pub = info.filter({ visibility: 'public', predicate: (h) => h.ssl }).format()
    const lan = info.filter({ kind: 'mdns', predicate: (h) => h.ssl }).format()
    return pub[0] ?? lan[0] ?? null
  })

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
