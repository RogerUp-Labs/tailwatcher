# TailWatcher

TailWatcher sends a push notification, through NTFY on this server, when an aircraft someone follows takes off. Each **watcher** is one person with their own NTFY topic and their own list of tail numbers and flight numbers.

## Setup

1. **Give TailWatcher its own NTFY user and token.**
   1. **NTFY → Actions → Create User**, username `tailwatcher`. Copy the password it shows.
   2. **NTFY → Actions → Grant User Topic Access**: user `tailwatcher`, topic **Enter New** `tailwatcher*`, permission **Read-Write**. The `*` covers every watcher's topic (`tailwatcher`, `tailwatcher_dad`, …), and Read-Write lets TailWatcher both send alerts and read text commands.
   3. Open the **NTFY web UI** (a private browser window is easiest), log in as `tailwatcher`, go to **Account → Access tokens → Create access token**, set it to never expire, and copy the token (`tk_…`).

   (NTFY's **Provision Publisher** action creates a send-only account that can't be given read access, so it works for alerts but not for text commands.)
2. **Configure TailWatcher.** Open **TailWatcher → Actions → Configure**, paste the **token**, and add a watcher:
   - **Name**, e.g. `Sam`
   - **NTFY Topic**, e.g. `tailwatcher_sam`
   - **Aircraft:** each tail number (e.g. `N12345`) or flight number (e.g. `UA1234`, with **Type** set to Flight number), with an optional nickname and an optional **Stop Watching After** (days)
3. **Subscribe on the phone.** In the NTFY Android app, add your server, log in, and subscribe to the watcher's topic.
4. Run **TailWatcher → Actions → Send Test Notification**. It sends to every watcher's topic and shows which ones worked.

## Web UI

Open **TailWatcher → Web UI** (on your LAN, over Tor, or a public address if you've set one up) for a dashboard of:

- **Trips:** each upcoming trip with its route, departure, the plane flying in, where it is in its journey, and when TailWatcher checks next
- **Watchers:** each person's aircraft, which are airborne right now, and links to the live map
- **Activity:** recent alerts, replies and the text commands people sent, including any NTFY didn't accept
- **System:** whether NTFY, text commands and trip lookups are working

It shows everyone's watchers and trips in one place, like an admin panel, and opens without a login. The switch in the top corner picks a look: **Modern**, or **Board**, an airport departures board where trips and aircraft sit on split-flap tiles that flip when something changes. Each browser remembers its choice. If you'd like a password (for example, if TailWatcher gets a public address), turn on **Require Web UI Password** in **Configure**; then use any username and the password from **Actions → Show Web UI Password** (**Reset Web UI Password** makes a new one). The dashboard is read-only for now; make changes with text commands or **Configure**.

## Text commands

Type in your topic in the NTFY app (the message bar at the bottom) and TailWatcher replies there:

| Send | Does |
|---|---|
| `N12345` | Watch tail number N12345 |
| `UA1234` (or `DL 89`, `UAL1234`) | Watch a flight number, whichever aircraft flies it |
| `add N12345 Vegas trip` | Watch it with a nickname (or rename one you already watch) |
| `UA1234 for 2 days` | Watch it, then stop automatically. Also `3d`, `12h`, `for 6 hours` |
| `add UA1234 Mom until fri` | Watch it through Friday night (until 3am Saturday). Also `until tomorrow` |
| `remove N12345` | Stop watching |
| `list` | Show your list, what's airborne, and time left on expiring entries |
| `info N12345` (or `who N12345`) | Look up any aircraft: what it is, who owns it, where it is now, and a photo |
| `info UA1234` | The same for whichever plane is flying that flight right now |
| `inbound UA1234 N38473 dep 4:30pm` | Follow the plane flying in for your flight (see **Where's my plane?** below) |
| `trips` | Your trips, numbered, soonest first |
| `change 1 AA5678` · `change 1 dep 5:10pm` · `change 1 N38473` · `change 1 11/15` · `change 1 from DFW` | Update trip 1: new flight number, departure time, plane, date or airport |
| `cancel 1` | Stop tracking trip 1 (or `cancel AA1234`) |
| `help` | Show the commands |

A plane you add is checked right away; if it's already flying, you get the "airborne" alert within seconds. Sending an entry you already watch with a new expiry (`UA1234 for 3d`) updates it. When an entry expires, TailWatcher removes it and posts "⌛ Stopped watching UA1234 (expired)". "until" uses the **Time Zone** set in Configure. Changes show up in **Configure** too. Each person can only change their own list, since they can only post to their own topic. Turn this off with **Text Commands** in Configure.

## Flight numbers

Airlines pick the aircraft for a flight on the day, so after booking a trip, watch the flight number instead of a tail. TailWatcher looks it up by the callsign the airline broadcasts (UA1234 → UAL1234) and the alert names the aircraft flying it: **UA1234 (N38473) departed**.

- Type flight numbers the way they appear on your ticket: `UA1234`, `DL 89`, `B6 123`. Major US and international airlines are recognized; for others, type the ICAO callsign directly (`UAL1234`).
- Some airlines (Ryanair, easyJet) broadcast callsigns that differ from the flight number, like `RYR5TM`. Use that callsign if the flight number doesn't alert.
- A flight number is watched every day it flies, so give trips an expiry: `UA1234 for 2 days`.
- How TailWatcher tells them apart: a registration with a dash (`G-ABCD`, `B-6123`) or a US N-number (`N12345`) is always a tail. A known airline code followed by 1–4 digits (`UA1234`), or any three letters followed by digits (`UAL1234`), is a flight. Anything else is a tail (`JA8089`).

## Looking up a plane

`info` works for any aircraft, watched or not. A reply looks like:

> 🔎 N172SP
> Cessna R172K (1977)
> Owner: Luke Airlines LLC · Southgate, Michigan
> Registration: valid, expires 08/31/2028
> Engine: Continental IO-360 (piston)
> Live: ✈️ 4,500 ft · 110 kt · 10 nm NW of KFDK
> Send N172SP to watch it.

with a photo when planespotters.net has one, and buttons for ADS-B Exchange, the FAA record and the photo page.

- **Owner details** come from the FAA registry, so they're US aircraft (N-numbers) only. The reply shows city and state; the **FAA record** button has the full public record. Non-US aircraft show the operator from hexdb.io instead.
- **Flags** show when an aircraft is military, on adsb.lol's "interesting" list, or hidden from FlightAware and Flightradar24 (FAA LADD).
- Owners can be companies or trusts set up to keep their name private, and the FAA's privacy (PIA) program hides some aircraft altogether.

## Where's my plane?

Before a flight, the plane you'll fly on is usually still finishing its previous flight somewhere else. If that flight runs late, so will yours. TailWatcher can follow that plane and tell you:

- ✈️ when it **takes off toward your airport**, with an arrival estimate and how much time that leaves before your departure
- ⏳ / ⚠️ if its arrival gets **within 45 minutes**, then **20 minutes**, of your departure, and 🧳 if it's **running 15+ minutes later** than last announced
- 🛬 when it **lands** at your airport (or that it's already there)
- 🧳 if it's flying an **earlier flight** first, so you know where it is

**Without an AeroDataBox key**, tell TailWatcher which plane it is. Your airline app usually shows it under "Where's my plane?", as a tail number or the flight it's arriving on:

`inbound UA1234 N38473 dep 4:30pm` · `inbound UA1234 UA567 dep 4:30pm tomorrow from IAD`

Your flight comes first, then the plane, your departure time, and optionally `tomorrow` or a date (`10/20`) and your airport (`from IAD`). Without `from`, TailWatcher works out your airport from where the plane is flying.

**With an AeroDataBox key** (free; see Configure), `inbound UA1234` is enough. Add `tomorrow` or a date for later trips, e.g. `inbound AA1234 11/14`, and `from IAD` if the flight number makes more than one stop. TailWatcher looks up your departure time, then the plane assigned to your flight and the flight it arrives on once the airline assigns one, and tells you if the plane or your departure time changes.

How often it checks, to stay well inside the free plan's 400 requests a month:
- **More than 2 weeks out:** once a week (1 request): is the flight still listed, and when does it leave?
- **2 weeks to 1 day out:** once a day (1 request).
- **The last day:** about 24 h, 6 h, 2 h and 45 min before departure (2 requests each), to find the assigned plane and its inbound flight.

A trip added a month ahead uses about 20 requests in all.

**If the airline renumbers or cancels your flight**, AeroDataBox stops listing it. TailWatcher notices on its next check and tells you. It also searches your airport's departures around the original time for the same airline to the same destination. If it finds a likely match, the message says e.g. "Looks like it's now AA5678, departing 4:10pm to KDFW. Reply \"change 2 AA5678\" to switch." It never switches on its own, so it can't end up following the wrong flight.

Arrival estimates come from the plane's live position and speed, so treat them as a heads-up rather than the airline's official time. Times are shown in the time zone set in Configure. Trips clear themselves a few hours after departure.

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
