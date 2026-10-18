import { configJson } from '../fileModels/config.json'
import { sdk } from '../sdk'

const { InputSpec, Value, List } = sdk

const aircraftSpec = InputSpec.of({
  tail: Value.text({
    name: 'Tail Number',
    description:
      'The aircraft registration, e.g. N12345 or G-ABCD. Dashes and spaces are ignored.',
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
    description: 'Optional name shown in the alert, e.g. "Dad\'s Cessna".',
    required: false,
    default: null,
    placeholder: "Dad's Cessna",
    maxLength: 40,
  }),
})

const inputSpec = InputSpec.of({
  aircraft: Value.list(
    List.obj(
      {
        name: 'Aircraft',
        description:
          'Tail numbers to watch worldwide. You get an alert when one takes off, or first shows up airborne after being off the radar for 20+ minutes.',
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
  ntfyTopic: Value.text({
    name: 'NTFY Topic',
    description:
      'The topic to publish to. Subscribe to the same topic in the NTFY app on your phone.',
    required: true,
    default: 'tailwatcher',
    patterns: [
      {
        regex: '^[a-zA-Z0-9_-]{1,64}$',
        description: 'Letters, numbers, underscores and hyphens only',
      },
    ],
  }),
  ntfyToken: Value.text({
    name: 'NTFY Access Token',
    description:
      'In NTFY, run Actions → Provision Publisher with Publisher ID "tailwatcher" and the topic above, then paste the token (tk_…) here. Leave blank only if the topic allows anonymous publishing.',
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
      'Free, unfiltered ADS-B feed to poll. Both show aircraft that FlightAware and Flightradar24 hide (FAA LADD).',
    default: 'adsb.lol',
    values: {
      'adsb.lol': 'adsb.lol',
      'adsb.fi': 'adsb.fi',
    },
  }),
  pollSeconds: Value.number({
    name: 'Check Every',
    description:
      'How often to check each aircraft. Lower is faster to alert but makes more requests to the free API.',
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
      'Choose the tail numbers to watch and where alerts go. TailWatcher restarts to apply changes.',
    warning: null,
    allowedStatuses: 'any',
    group: null,
    visibility: 'enabled',
  }),

  inputSpec,

  async () => {
    const c = await configJson.read().once()
    if (!c) return null
    return {
      ...c,
      ntfyToken: c.ntfyToken || null,
      aircraft: c.aircraft.map((a) => ({ tail: a.tail, label: a.label || null })),
    }
  },

  async ({ effects, input }) => {
    await configJson.write(effects, {
      aircraft: input.aircraft.map((a) => ({
        tail: a.tail.toUpperCase().replace(/[^A-Z0-9]/g, ''),
        label: a.label?.trim() ?? '',
      })),
      ntfyTopic: input.ntfyTopic,
      ntfyToken: input.ntfyToken ?? '',
      pollSeconds: input.pollSeconds,
      dataSource: input.dataSource,
      mapLinks: input.mapLinks,
      notifyLanding: input.notifyLanding,
      priority: input.priority,
    })
    return null
  },
)
