import { Aircraft, configJson, timeZones } from '../fileModels/config.json'
import { newTopic } from '../utils'
import { sdk } from '../sdk'

const { InputSpec, Value, List } = sdk

const DAY = 86400

/** Days left on an entry, as shown in the form (one decimal). */
const daysLeft = (expires: number | null, now: number) =>
  expires === null
    ? null
    : Math.max(0.1, Math.round(((expires - now) / DAY) * 10) / 10)

const aircraftSpec = InputSpec.of({
  tail: Value.text({
    name: 'Tail or Flight Number',
    description:
      'An aircraft registration (N12345, G-ABCD) or an airline flight number (UA1234, DL89, or the ICAO callsign UAL1234). Set Type to match. Dashes and spaces are ignored.',
    required: true,
    default: null,
    placeholder: 'N12345',
    patterns: [
      {
        regex: '^[A-Za-z0-9 -]{2,12}$',
        description: 'Letters, numbers and dashes only',
      },
    ],
  }),
  label: Value.text({
    name: 'Nickname',
    description:
      'Optional name shown in this watcher\'s alerts, e.g. "Dad\'s Cessna".',
    required: false,
    default: null,
    placeholder: "Dad's Cessna",
    maxLength: 40,
  }),
  kind: Value.select({
    name: 'Type',
    description:
      'Flight numbers are matched by the callsign the airline broadcasts, so you are alerted whichever aircraft flies it, and the alert names that aircraft.',
    default: 'tail',
    values: {
      tail: 'Tail number',
      flight: 'Flight number',
    },
  }),
  expiresDays: Value.number({
    name: 'Stop Watching After',
    description:
      'Optional. Remove this entry automatically after this many days, e.g. for a trip. Leave empty to watch it until you remove it. Text commands set this too ("UA1234 for 2 days").',
    required: false,
    default: null,
    min: 0.1,
    max: 365,
    integer: false,
    units: 'days',
  }),
})

const watcherSpec = InputSpec.of({
  name: Value.text({
    name: 'Name',
    description: 'Who this watcher is for, e.g. "Sam" or "Dad".',
    required: true,
    default: null,
    placeholder: 'Dad',
    maxLength: 40,
  }),
  topic: Value.text({
    name: 'NTFY Topic',
    description:
      'Leave blank and TailWatcher makes an unguessable one. Use "Connect phone" on the Web UI to send this person a one-tap subscribe link.',
    required: false,
    default: null,
    placeholder: 'tailwatcher_dad',
    patterns: [
      {
        regex: '^[a-zA-Z0-9_-]{1,64}$',
        description: 'Letters, numbers, underscores and hyphens only',
      },
    ],
  }),
  aircraft: Value.list(
    List.obj(
      {
        name: 'Aircraft',
        description:
          'Tail numbers and flight numbers this watcher gets alerts for. Several watchers can follow the same aircraft.',
        default: [],
        maxLength: 50,
      },
      {
        spec: aircraftSpec,
        displayAs: '{{tail}} {{label}}',
        uniqueBy: 'tail',
      },
    ),
  ),
  notifyLanding: Value.toggle({
    name: 'Also Alert on Landing',
    description:
      'Send a second alert when the aircraft lands, or drops off the radar at low altitude.',
    default: false,
  }),
  priority: Value.select({
    name: 'Notification Priority',
    description:
      'NTFY priority. "High" and "Max" can sound or vibrate even when the phone is set to quiet for normal notifications.',
    default: 'default',
    values: {
      low: 'Low',
      default: 'Default',
      high: 'High',
      max: 'Max',
    },
  }),
})

const inputSpec = InputSpec.of({
  watchers: Value.list(
    List.obj(
      {
        name: 'Watchers',
        description:
          'Each watcher has their own NTFY topic and aircraft list. You get an alert when one of your aircraft takes off, or first shows up airborne after being off the radar for 20+ minutes.',
        default: [],
        maxLength: 20,
      },
      {
        spec: watcherSpec,
        displayAs: '{{name}} → {{topic}}',
        uniqueBy: 'topic',
      },
    ),
  ),
  ntfyServer: Value.select({
    name: 'Notification Server',
    description:
      "- ntfy.sh: the public ntfy service. Nothing else to install or set up; each watcher gets an unguessable topic, which is what keeps their alerts private.\n- This server's NTFY: alerts stay on your hardware. Install NTFY, then in NTFY run \"Set Anonymous Topic Access\" for topic \"tw-*\" with Read-Write (or set up a token below).\n- Custom: another ntfy server, at the address below.",
    default: 'public',
    values: {
      public: 'ntfy.sh (easiest)',
      local: "This server's NTFY (private)",
      custom: 'Custom ntfy server',
    },
  }),
  ntfyCustomUrl: Value.text({
    name: 'Custom Server Address',
    description: 'Only for "Custom ntfy server", e.g. https://ntfy.example.com.',
    required: false,
    default: null,
    placeholder: 'https://ntfy.example.com',
    inputmode: 'url',
    patterns: [{ regex: '^https?://\\S+$', description: 'Starts with https:// or http://' }],
  }),
  ntfyToken: Value.text({
    name: 'NTFY Access Token',
    description:
      "Optional, and only used with this server's NTFY or a custom server (never sent to ntfy.sh). Needed if that server requires a login for TailWatcher's topics: a token for a regular user with Read-Write on them (made in the NTFY web UI under Account → Access tokens).",
    required: false,
    default: null,
    masked: true,
    placeholder: 'tk_…',
    patterns: [
      {
        regex: '^tk_[A-Za-z0-9]+$',
        description: 'NTFY tokens start with tk_',
      },
    ],
  }),
  textCommands: Value.toggle({
    name: 'Text Commands',
    description:
      'Let each watcher change their own list by typing in their NTFY topic: send a tail or flight number to add it ("UA1234 for 2 days" to have it expire), "remove N12345" to drop it, "list" to see it. Requires the NTFY Access Token above to belong to a user with Read-Write on tailwatcher*, and each watcher\'s user Read-Write on their topic.',
    default: true,
  }),
  timeZone: Value.select({
    name: 'Time Zone',
    description:
      'Used by text commands like "UA1234 until fri": the entry is watched through Friday night (until 3am Saturday) in this time zone.',
    default: 'America/New_York',
    values: timeZones,
  }),
  aerodataboxKey: Value.text({
    name: 'AeroDataBox API Key (optional)',
    description:
      'For "where\'s my plane?" trip tracking. Without a key, you tell TailWatcher which plane is flying in for your flight ("inbound UA1234 N38473 dep 4:30pm"). With one, "inbound UA1234" is enough: it looks up the assigned plane, the flight it arrives on and your departure time, and re-checks before departure in case the plane changes. Get a free key by subscribing to AeroDataBox\'s Basic plan on RapidAPI (rapidapi.com/aedbx-aedbx/api/aerodatabox). Each trip uses about 2 requests per check.',
    required: false,
    default: null,
    masked: true,
    placeholder: 'RapidAPI key',
  }),
  webPassword: Value.toggle({
    name: 'Require Web UI Password',
    description:
      'Off: the dashboard opens without a login for anyone who can reach it (on StartOS 0.4 that is your local network and VPN unless you add a public address). On: the browser asks for a password (any username); see "Show Web UI Password".',
    default: false,
  }),
  mapLinks: Value.select({
    name: 'Map Buttons',
    description:
      'Which live maps the alert links to. Tapping the alert opens the first one.',
    default: 'adsbx',
    values: {
      adsbx: 'ADS-B Exchange',
      adsblol: 'adsb.lol',
      both: 'Both',
    },
  }),
  dataSource: Value.select({
    name: 'ADS-B Data Source',
    description:
      'Free, unfiltered ADS-B feed to poll; if it refuses, TailWatcher uses the other one for that check. Both show aircraft that FlightAware and Flightradar24 hide (FAA LADD). adsb.lol allows only 500 requests a day, so adsb.fi is the better everyday choice.',
    default: 'adsb.fi',
    values: {
      'adsb.fi': 'adsb.fi',
      'adsb.lol': 'adsb.lol',
    },
  }),
  pollSeconds: Value.number({
    name: 'Check Every',
    description:
      'How often to check. All watched aircraft are checked together (one request covers up to 25), so 60 seconds is about 60 requests an hour however many you watch. Lower alerts sooner.',
    required: true,
    default: 60,
    min: 15,
    max: 600,
    integer: true,
    units: 'seconds',
  }),
})

export const configure = sdk.Action.withInput(
  'configure',

  async () => ({
    name: 'Configure',
    description:
      'Set up watchers (who gets alerts, on which NTFY topic, for which tail and flight numbers). Changes apply within a few seconds.',
    warning: null,
    allowedStatuses: 'any',
    group: null,
    visibility: 'enabled',
  }),

  inputSpec,

  async () => {
    const c = await configJson.read().once()
    if (!c) return null
    const now = Date.now() / 1000
    return {
      ...c,
      ntfyToken: c.ntfyToken || null,
      ntfyCustomUrl: c.ntfyCustomUrl || null,
      aerodataboxKey: c.aerodataboxKey || null,
      watchers: c.watchers.map((w) => ({
        ...w,
        aircraft: w.aircraft.map((a) => ({
          tail: a.tail,
          label: a.label || null,
          kind: a.kind,
          expiresDays: daysLeft(a.expires, now),
        })),
      })),
    }
  },

  async ({ effects, input }) => {
    const prev = await configJson.read().once()
    const now = Date.now() / 1000
    const norm = (t: string) => t.toUpperCase().replace(/[^A-Z0-9]/g, '')

    // The form shows days left; keep the stored expiry when that number is
    // unchanged, so saving the form doesn't push every trip back.
    const expiry = (
      topic: string,
      a: { tail: string; expiresDays: number | null },
    ) => {
      if (a.expiresDays === null) return null
      const old: Aircraft | undefined = prev?.watchers
        .find((w) => w.topic === topic)
        ?.aircraft.find((p) => norm(p.tail) === norm(a.tail))
      if (
        old &&
        old.expires !== null &&
        daysLeft(old.expires, now) === a.expiresDays
      )
        return old.expires
      return Math.round(now + a.expiresDays * DAY)
    }

    await configJson.write(effects, {
      watchers: input.watchers.map((w) => {
        const topic = w.topic?.trim() || newTopic(w.name)
        return {
          name: w.name.trim(),
          topic,
          aircraft: w.aircraft.map((a) => ({
            tail: norm(a.tail),
            label: a.label?.trim() ?? '',
            kind: a.kind,
            expires: expiry(topic, a),
          })),
          notifyLanding: w.notifyLanding,
          priority: w.priority,
        }
      }),
      ntfyToken: input.ntfyToken ?? '',
      pollSeconds: input.pollSeconds,
      dataSource: input.dataSource,
      mapLinks: input.mapLinks,
      textCommands: input.textCommands,
      timeZone: input.timeZone,
      aerodataboxKey: input.aerodataboxKey?.trim() ?? '',
      ntfyServer: input.ntfyServer,
      ntfyCustomUrl: input.ntfyCustomUrl?.trim() ?? '',
      webPassword: input.webPassword,
    })
    return null
  },
)
