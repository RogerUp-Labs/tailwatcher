import { IMPOSSIBLE, VersionInfo } from '@start9labs/start-sdk'
import { configJson, rawConfigJson } from '../fileModels/config.json'

export const v0_2_0 = VersionInfo.of({
  version: '0.2.0:0',
  releaseNotes: {
    en_US:
      'Watchers: each person gets their own NTFY topic and aircraft list, with their own landing alerts and priority. A tail followed by several watchers is still checked once. Your existing settings become the first watcher, "Me". Alerts that fail to send are retried for 30 minutes without re-sending to anyone who already got them.',
  },
  migrations: {
    // 0.1.x kept one aircraft list and one topic at the top level.
    up: async ({ effects }) => {
      const raw = await rawConfigJson.read().once()
      if (!raw || 'watchers' in raw || !Array.isArray(raw.aircraft)) return
      await configJson.write(effects, {
        watchers: [
          {
            name: 'Me',
            topic: typeof raw.ntfyTopic === 'string' ? raw.ntfyTopic : 'tailwatcher',
            aircraft: raw.aircraft as { tail: string; label: string }[],
            notifyLanding: raw.notifyLanding === true,
            priority: (['low', 'default', 'high', 'max'].includes(raw.priority as string)
              ? raw.priority
              : 'default') as 'low' | 'default' | 'high' | 'max',
          },
        ],
        ntfyToken: typeof raw.ntfyToken === 'string' ? raw.ntfyToken : '',
        pollSeconds: typeof raw.pollSeconds === 'number' ? raw.pollSeconds : 60,
        dataSource: raw.dataSource === 'adsb.fi' ? 'adsb.fi' : 'adsb.lol',
        mapLinks: (['adsbx', 'adsblol', 'both'].includes(raw.mapLinks as string)
          ? raw.mapLinks
          : 'adsbx') as 'adsbx' | 'adsblol' | 'both',
        textCommands: true,
      })
    },
    down: IMPOSSIBLE,
  },
})
