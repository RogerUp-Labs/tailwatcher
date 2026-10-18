import { FileHelper, z } from '@start9labs/start-sdk'
import { sdk } from '../sdk'

/** Settings written by the Configure action and read by /app/tailwatcher.py. */
const shape = z.object({
  aircraft: z
    .array(z.object({ tail: z.string(), label: z.string().catch('') }))
    .catch([]),
  ntfyTopic: z.string().catch('tailwatcher'),
  ntfyToken: z.string().catch(''),
  pollSeconds: z.number().catch(60),
  dataSource: z.enum(['adsb.lol', 'adsb.fi']).catch('adsb.lol'),
  mapLinks: z.enum(['adsbx', 'adsblol', 'both']).catch('adsbx'),
  notifyLanding: z.boolean().catch(false),
  priority: z.enum(['low', 'default', 'high', 'max']).catch('default'),
})

export type Config = z.infer<typeof shape>

export const configJson = FileHelper.json(
  { base: sdk.volumes.main, subpath: 'config.json' },
  shape,
)
