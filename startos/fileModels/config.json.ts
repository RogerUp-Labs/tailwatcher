import { FileHelper, z } from '@start9labs/start-sdk'
import { sdk } from '../sdk'

const priority = z.enum(['low', 'default', 'high', 'max'])

/** One person (or channel) with their own NTFY topic and aircraft list. */
const watcher = z.object({
  name: z.string(),
  topic: z.string(),
  aircraft: z
    .array(z.object({ tail: z.string(), label: z.string().catch('') }))
    .catch([]),
  notifyLanding: z.boolean().catch(false),
  priority: priority.catch('default'),
})

/**
 * Settings written by the Configure action and read by /app/tailwatcher.py.
 * Text commands also edit `watchers[].aircraft` from inside the container,
 * so keep this shape in sync with app/commands.py.
 */
const shape = z.object({
  watchers: z.array(watcher).catch([]),
  ntfyToken: z.string().catch(''),
  pollSeconds: z.number().catch(60),
  dataSource: z.enum(['adsb.lol', 'adsb.fi']).catch('adsb.lol'),
  mapLinks: z.enum(['adsbx', 'adsblol', 'both']).catch('adsbx'),
  textCommands: z.boolean().catch(true),
})

export type Config = z.infer<typeof shape>
export type Watcher = z.infer<typeof watcher>

const path = { base: sdk.volumes.main, subpath: 'config.json' }

export const configJson = FileHelper.json(path, shape)

/** The same file read without a schema, for migrating older formats. */
export const rawConfigJson = FileHelper.json(
  path,
  z.record(z.string(), z.unknown()),
)
