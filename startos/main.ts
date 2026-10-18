import { configJson } from './fileModels/config.json'
import { sdk } from './sdk'
import { healthPort, ntfyFallbackUrl, ntfyUrl } from './utils'

export const main = sdk.setupMain(async ({ effects }) => {
  // .const() restarts the service when the config or NTFY's address changes.
  const config = await configJson.read().const(effects)
  const ntfy = (await ntfyUrl(effects).const()) ?? ntfyFallbackUrl
  console.info(
    `Starting TailWatcher: ${config?.aircraft.length ?? 0} aircraft, NTFY at ${ntfy}`,
  )

  const subcontainer = await sdk.SubContainer.of(
    effects,
    { imageId: 'main' },
    sdk.Mounts.of().mountVolume({
      volumeId: 'main',
      subpath: null,
      mountpoint: '/data',
      readonly: false,
    }),
    'tailwatcher-sub',
  )

  return sdk.Daemons.of(effects).addDaemon('primary', {
    subcontainer,
    exec: {
      command: ['python', '/app/tailwatcher.py'],
      env: { NTFY_URL: ntfy },
    },
    ready: {
      display: 'Watcher',
      fn: async () => {
        try {
          const res = await fetch(`http://localhost:${healthPort}/health`)
          const h = (await res.json()) as { ok: boolean; message: string }
          return h.ok
            ? { result: 'success', message: h.message }
            : { result: 'failure', message: h.message }
        } catch {
          return { result: 'starting', message: 'Starting watcher' }
        }
      },
    },
    requires: [],
  })
})
