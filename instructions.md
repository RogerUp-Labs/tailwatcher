# TailWatcher

TailWatcher sends a push notification, through NTFY on this server, when an aircraft someone follows takes off. Each **watcher** is one person with their own NTFY topic and their own list of aircraft.

## Setup

1. **Create a publisher in NTFY.** Open **NTFY → Actions → Provision Publisher**. Enter Publisher ID `tailwatcher` and Topic `tailwatcher*`. Copy the **token** (`tk_…`) it shows. The `*` lets this one token publish to every watcher's topic (`tailwatcher`, `tailwatcher_dad`, …).
2. **Configure TailWatcher.** Open **TailWatcher → Actions → Configure**, paste the **token**, and add a watcher:
   - **Name**, e.g. `Sam`
   - **NTFY Topic**, e.g. `tailwatcher_sam`
   - **Aircraft:** each tail number (e.g. `N12345`), with an optional nickname
3. **Subscribe on the phone.** In the NTFY Android app, add your server, log in, and subscribe to the watcher's topic.
4. **Turn on text commands (optional, recommended).** In NTFY, run **Grant User Topic Access** for user `pkg_tailwatcher`, topic `tailwatcher*`, permission **Read-Write**, so TailWatcher can read what you send.
5. Run **TailWatcher → Actions → Send Test Notification**. It sends to every watcher's topic and shows which ones worked.

## Text commands

Type in your topic in the NTFY app (the message bar at the bottom) and TailWatcher replies there:

| Send | Does |
|---|---|
| `N12345` | Watch N12345 |
| `add N12345 Vegas trip` | Watch it with a nickname (or rename one you already watch) |
| `remove N12345` | Stop watching |
| `list` | Show your aircraft and which are airborne |
| `help` | Show the commands |

A plane you add is checked right away; if it's already flying, you get the "airborne" alert within seconds. Changes show up in **Configure** too. Each person can only change their own list, since they can only post to their own topic. Turn this off with **Text Commands** in Configure.

## Adding another person

1. **In NTFY:** run **Create User** (e.g. `dad`) and save the password. Then run **Grant User Topic Access** with user `dad`, topic `tailwatcher_dad`, permission **Read-Write** (or **Read Only** if they shouldn't use text commands). They can only use their own topic.
2. **In TailWatcher → Configure:** add a watcher named `Dad` with topic `tailwatcher_dad`. Add their aircraft there, or leave the list empty and let them text tail numbers in. Several watchers can follow the same aircraft, and each can give it their own nickname. It's still checked only once.
3. **On their phone:** the NTFY app, logged in as `dad`, subscribed to `tailwatcher_dad`.

No new token is needed as long as the topic starts with `tailwatcher`.

## When you get an alert

- **Departed:** the aircraft was seen on the ground, then in the air.
- **Is airborne:** it appeared already flying after being off the radar for 20+ minutes. Many small airports have no ADS-B coverage at ground level, so this is often the first sign of a departure.
- **Landed / likely landed** (optional, per watcher): it touched down, or dropped off the radar below 3,000 ft.

Tapping the alert opens the aircraft live on ADS-B Exchange (or adsb.lol, set in Configure).

## Good to know

- Data comes from free, community-run ADS-B feeds (adsb.lol or adsb.fi). Coverage depends on volunteer receivers, so remote areas can have gaps.
- These feeds are unfiltered: aircraft that FlightAware and Flightradar24 hide under the FAA's LADD program still appear. Aircraft in the FAA's privacy (PIA) program broadcast a rotating address and can't be tracked by tail number anywhere.
- The service's health check shows which watched aircraft are airborne right now, and reports any watcher topic that NTFY refused.
- If NTFY is briefly unreachable, alerts are retried for 30 minutes and sent only to watchers who haven't received them yet.
- If the feed rate-limits TailWatcher, it backs off automatically (up to 10 minutes). Raise **Check Every** if you watch many aircraft.
