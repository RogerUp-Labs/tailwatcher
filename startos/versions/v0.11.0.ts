import { VersionInfo, IMPOSSIBLE } from '@start9labs/start-sdk'
import { configJson, rawConfigJson } from '../fileModels/config.json'

export const v0_11_0 = VersionInfo.of({
  version: '0.11.0:0',
  releaseNotes: {
    en_US:
      'Far fewer requests to the free ADS-B feeds: all watched aircraft, trip planes and shared flights are now checked together in one request per cycle (up to 25 per request) instead of one request each. If a feed answers "too many requests", TailWatcher uses the other one for that check. adsb.lol turned out to allow only 500 requests a day, which ran out partway through the day, so installs using it switch to adsb.fi (you can change it back in Configure).',
  },
  migrations: {
    up: async ({ effects }) => {
      const raw = await rawConfigJson.read().once()
      if (raw?.dataSource === 'adsb.lol') {
        await configJson.merge(effects, { dataSource: 'adsb.fi' })
      }
    },
    down: IMPOSSIBLE,
  },
})
