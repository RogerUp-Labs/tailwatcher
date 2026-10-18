import { configJson } from './fileModels/config.json'
import { sdk } from './sdk'
import { healthPort, ntfyPhoneUrl, ntfyUrl } from './utils'

export const main = sdk.setupMain(async ({ effects }) => {
  // The watcher hot-reloads config.json itself (text commands edit it too), so
  // only this server's NTFY addresses restart the service. NTFY is optional:
  // with ntfy.sh (the default) or a custom server these are simply unused.
  const config = await configJson.read().once()
  const ntfy = (await ntfyUrl(effects).const()) ?? ''
  const phone = (await ntfyPhoneUrl(effects).const()) ?? ''
  const watchers = config?.watchers ?? []
  const entries = new Set(
    watchers.flatMap((w) => w.aircraft.map((a) => a.tail)),
  )
  console.info(
    `Starting TailWatcher: ${entries.size} tail/flight number(s) for ${watchers.length} watcher(s), alerts via ${config?.ntfyServer ?? 'public'}`,
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
      env: { NTFY_URL: ntfy, NTFY_PHONE_URL: phone },
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
