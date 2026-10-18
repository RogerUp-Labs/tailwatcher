import { configJson } from '../fileModels/config.json'
import { sdk } from '../sdk'
import { ntfyFallbackUrl, ntfyUrl, publicNtfy } from '../utils'

export const testNotification = sdk.Action.withoutInput(
  'test-notification',

  async () => ({
    name: 'Send Test Notification',
    description:
      "Publish a sample takeoff alert to every watcher's NTFY topic to check that each phone receives it.",
    warning: null,
    allowedStatuses: 'any',
    group: null,
    visibility: 'enabled',
  }),

  async ({ effects }) => {
    const c = await configJson.read().once()
    if (!c?.watchers.length) throw new Error('Add a watcher in Configure first.')
    // Same rules as resolve_ntfy() in app/tailwatcher.py: the token never goes to ntfy.sh.
    const base =
      c.ntfyServer === 'custom'
        ? c.ntfyCustomUrl
        : c.ntfyServer === 'local'
          ? ((await ntfyUrl(effects).once()) ?? ntfyFallbackUrl)
          : publicNtfy
    const token = c.ntfyServer === 'public' ? '' : c.ntfyToken
    if (!base) throw new Error('Set the custom server address in Configure first.')
    const hex = 'a835af'

    const results = await Promise.all(
      c.watchers.map(async (w) => {
        try {
          const res = await fetch(base.replace(/\/$/, '') + '/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              ...(token ? { Authorization: `Bearer ${token}` } : {}),
            },
            body: JSON.stringify({
              topic: w.topic,
              title: `TailWatcher test for ${w.name}: N628TS departed`,
              message:
                'at KFDK – Frederick Municipal Airport\n1,800 ft · 105 kt · hdg 270°\nThis is a test alert.',
              tags: ['airplane', 'test_tube'],
              click: `https://globe.adsbexchange.com/?icao=${hex}`,
              actions: [
                {
                  action: 'view',
                  label: 'ADS-B Exchange',
                  url: `https://globe.adsbexchange.com/?icao=${hex}`,
                },
              ],
            }),
          })
          if (res.ok) return { w, ok: true, detail: 'sent' }
          const detail =
            res.status === 401 || res.status === 403
              ? `refused (HTTP ${res.status}): the token has no access to this topic. In NTFY, give the token's user Read-Write on "tailwatcher*" with Grant User Topic Access.`
              : `HTTP ${res.status}: ${(await res.text()).slice(0, 120)}`
          return { w, ok: false, detail }
        } catch (e) {
          return { w, ok: false, detail: `could not reach NTFY: ${e}` }
        }
      }),
    )

    const failed = results.filter((r) => !r.ok).length
    return {
      version: '1',
      title: failed ? `${failed} of ${results.length} Failed` : 'Test Sent',
      message: failed
        ? 'Some topics did not accept the test. Details below.'
        : `Published to ${results.length} topic(s) on ${base}. Check each watcher's NTFY app.`,
      result: {
        type: 'group',
        value: results.map((r) => ({
          type: 'single',
          name: `${r.w.name} → ${r.w.topic}`,
          description: null,
          value: r.ok ? '✓ sent' : `✗ ${r.detail}`,
          masked: false,
          copyable: false,
          qr: false,
        })),
      },
    }
  },
)
