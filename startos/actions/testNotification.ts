import { configJson } from '../fileModels/config.json'
import { sdk } from '../sdk'
import { ntfyFallbackUrl, ntfyUrl } from '../utils'

export const testNotification = sdk.Action.withoutInput(
  'test-notification',

  async () => ({
    name: 'Send Test Notification',
    description:
      'Publish a sample takeoff alert to your NTFY topic to check that your phone receives it.',
    warning: null,
    allowedStatuses: 'any',
    group: null,
    visibility: 'enabled',
  }),

  async ({ effects }) => {
    const c = await configJson.read().once()
    if (!c) throw new Error('Run Configure first.')
    const base = (await ntfyUrl(effects).once()) ?? ntfyFallbackUrl
    const hex = 'a835af'
    const res = await fetch(base.replace(/\/$/, '') + '/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(c.ntfyToken ? { Authorization: `Bearer ${c.ntfyToken}` } : {}),
      },
      body: JSON.stringify({
        topic: c.ntfyTopic,
        title: 'TailWatcher test: N628TS departed',
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
    if (!res.ok) {
      const detail = (await res.text()).slice(0, 200)
      throw new Error(
        res.status === 403 || res.status === 401
          ? `NTFY refused the token for topic "${c.ntfyTopic}" (HTTP ${res.status}). Provision a publisher for this topic in NTFY and paste its token in Configure.`
          : `NTFY returned HTTP ${res.status}: ${detail}`,
      )
    }
    return {
      version: '1',
      title: 'Test Sent',
      message: `Published to "${c.ntfyTopic}" on ${base}. Check the NTFY app on your phone.`,
      result: null,
    }
  },
)
