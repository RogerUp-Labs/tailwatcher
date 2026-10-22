import { FileHelper, z } from '@start9labs/start-sdk'
import { sdk } from '../sdk'

const priority = z.enum(['low', 'default', 'high', 'max'])

/** Time zones offered in Configure (IANA name → label). */
export const timeZones = {
  'America/New_York': 'US Eastern',
  'America/Chicago': 'US Central',
  'America/Denver': 'US Mountain',
  'America/Phoenix': 'Arizona',
  'America/Los_Angeles': 'US Pacific',
  'America/Anchorage': 'Alaska',
  'Pacific/Honolulu': 'Hawaii',
  'America/Halifax': 'Atlantic (Canada)',
  'Europe/London': 'UK / Ireland',
  'Europe/Paris': 'Central Europe',
  'Europe/Helsinki': 'Eastern Europe',
  'Asia/Tokyo': 'Japan',
  'Australia/Sydney': 'Australia Eastern',
  UTC: 'UTC',
} as const
type TimeZone = keyof typeof timeZones

/**
 * A tail number or an airline flight number ("UA1234", watched by its ICAO
 * callsign). `expires` is a Unix time in seconds; the watcher removes the
 * entry once it passes. 0.3.0 entries load as tails that never expire.
 */
const aircraft = z.object({
  tail: z.string(),
  label: z.string().catch(''),
  kind: z.enum(['tail', 'flight']).catch('tail'),
  expires: z.number().nullable().catch(null),
})

/** One person (or channel) with their own NTFY topic and aircraft list. */
const watcher = z.object({
  name: z.string(),
  topic: z.string(),
  /** Optional separate topic for tail/flight-number alerts; blank = they go to `topic` with the trips. */
  planesTopic: z.string().catch(''),
  aircraft: z.array(aircraft).catch([]),
  notifyLanding: z.boolean().catch(false),
  priority: priority.catch('default'),
  /** Their own time zone (0.22.0); blank = the server's `timeZone`. Set in the Web UI. */
  timeZone: z.string().catch(''),
  /** Days before each flight to send a trip reminder (0.24.0); 0 = off. Set in the Web UI. */
  tripReminder: z.number().catch(0),
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
  dataSource: z.enum(['adsb.lol', 'adsb.fi']).catch('adsb.fi'),
  mapLinks: z.enum(['adsbx', 'adsblol', 'both']).catch('adsbx'),
  textCommands: z.boolean().catch(true),
  /** Default IANA zone for text commands like "until fri"; each watcher can have their own. */
  timeZone: z
    .enum(Object.keys(timeZones) as [TimeZone, ...TimeZone[]])
    .catch('America/New_York'),
  /**
   * Where alerts are published. public = ntfy.sh (default; no NTFY package or
   * logins, unguessable topics are the lock), local = this server's NTFY
   * (installs from before 0.12 are migrated to this), custom = ntfyCustomUrl.
   */
  ntfyServer: z.enum(['public', 'local', 'custom']).catch('public'),
  ntfyCustomUrl: z.string().catch(''),
  /** With this server's NTFY: open = phones subscribe to tw-* without a login; login = one NTFY account each. */
  ntfyPhoneMode: z.enum(['open', 'login']).catch('open'),
  /** Optional RapidAPI key for AeroDataBox; lets "inbound UA1234" find the plane itself. */
  aerodataboxKey: z.string().catch(''),
  /** 0.21 and older: ask for the Web UI password (webui.json). Still written, as webAuth !== 'off'. */
  webPassword: z.boolean().catch(false),
  /**
   * How people sign in to the Web UI (0.22.0): off, password (one shared
   * password from webui.json), or accounts (family accounts, app/accounts.py).
   * Missing on older installs, which follow webPassword.
   */
  webAuth: z.enum(['off', 'password', 'accounts']).optional().catch(undefined),
})

export type Config = z.infer<typeof shape>
export type Watcher = z.infer<typeof watcher>
export type Aircraft = z.infer<typeof aircraft>

const path = { base: sdk.volumes.main, subpath: 'config.json' }

export const configJson = FileHelper.json(path, shape)

/** The same file read without a schema, for migrating older formats. */
export const rawConfigJson = FileHelper.json(
  path,
  z.record(z.string(), z.unknown()),
)
