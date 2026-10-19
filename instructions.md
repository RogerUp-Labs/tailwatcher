# TailWatcher

TailWatcher sends push notifications to the people in your household when a plane they care about takes off or lands: a family member's flight, a friend's Cessna, or the plane flying in for your next trip. It works with any airline or aircraft, using free public ADS-B data, and delivers alerts through the free **ntfy** app.

## Getting started

1. Open TailWatcher's **Web UI** and tap **+ Add watcher** for each person who should get alerts. A name is all it needs.
2. Tap **Connect phone** on that watcher and send them the link (see **Connecting a phone**).
3. Add what they want to follow with **+ Aircraft**: a tail number like `N12345` or a flight number like `UA1234`. They can also text these in themselves (see **Text commands**).
4. Optional: add a free **AeroDataBox** key in **⚙ Settings** so trips find the plane flying in for your flight on their own.

Nothing else is needed: alerts go through the public ntfy.sh service by default, so there's no NTFY package, account or token to set up. To keep alerts on your own server instead, see **Settings and where alerts go**.

## Connecting a phone

Each watcher has their own notification topic, a long random name that TailWatcher picks. Open **Connect phone** on that watcher. Distance doesn't matter: someone in another state gets alerts the same way.

**Send an invite link** (best when they're not with you): type your name, pick how long the link should work (7 days by default), tap **Create invite link**, then **Send invite** to text it, or send it by iMessage, Signal or email. It's a normal web link, so it's tappable in any messaging app. It opens a page that walks them through installing ntfy and subscribing in two taps. Active invites are listed in the dialog, where **Cancel** stops one. Invite links need TailWatcher to have a public address in StartOS (for example through StartTunnel); without one, they only work on your home network.

**With their phone in hand**, use the steps under the invite box:

1. Install the free **ntfy** app (Google Play, F-Droid or the App Store; the links are in the dialog).
2. Tap the subscribe link on their phone. **Send link** shares it; **Copy link** copies it. The ntfy app opens with their alerts ready to subscribe.

If the link doesn't open the app, open the web link shown under it, or in the ntfy app tap **+**, turn on **Use another server**, and enter the server and topic shown in the dialog.

Keep these links private: anyone with a person's link or invite could read their alerts.

## Watching planes and flights

- **Tail numbers** (`N12345`, `G-ABCD`) follow one specific aircraft: a private plane, a friend's plane, a specific airliner.
- **Flight numbers** (`UA1234`, `DL 89`) follow whichever aircraft the airline uses for that flight, which is usually what you want after booking a trip. The alert names the aircraft: **UA1234 (N38473) departed**. A flight number flies every day, so give it an end: `UA1234 for 2 days`.
- Some airlines broadcast a callsign that differs from the flight number (Ryanair `RYR5TM`). If a flight number never alerts, use the callsign.

What the alerts mean:

- **Departed:** the plane was seen on the ground, then in the air.
- **Is airborne:** it appeared already flying after being off the radar for 20+ minutes. Many small airports have no ADS-B coverage on the ground, so this is often the first sign of a departure.
- **Landed / likely landed** (turn on **Landing alerts** for a watcher): it touched down, or dropped off the radar below 3,000 ft.

Tapping an alert opens the plane on a live map.

## Text commands

People can manage their own list by typing in their topic in the ntfy app (the message bar at the bottom). TailWatcher replies in the same conversation.

| Send | Does |
|---|---|
| `N12345` | Watch tail number N12345 |
| `UA1234` (or `DL 89`) | Watch a flight number |
| `add N12345 Vegas trip` | Watch it with a nickname (or rename one you already watch) |
| `UA1234 for 2 days` | Watch it, then stop automatically. Also `3d`, `12h`, `until fri`, `until tomorrow` |
| `remove N12345` | Stop watching |
| `list` | Your list, what's airborne, and time left on expiring entries |
| `info N12345` | Look up any aircraft: what it is, who owns it, where it is now |
| `inbound UA1234 N38473 dep 4:30pm` | Follow the plane flying in for your flight |
| `inbound UA1234 11/14 return UA5678 11/21` | A round trip: your flight out and your flight home together |
| `return 1 UA5678 11/21` | Add the flight home to trip 1 |
| `trips` | Your trips, numbered |
| `change 1 AA5678` | Update trip 1: a new flight number, `dep 5:10pm`, a plane, a date `11/15` or `from DFW` |
| `share 1 Mom & Dad` | Send another watcher your flight's departure and landing (`unshare` to stop). Covers both flights of a round trip |
| `cancel 1` | Stop tracking trip 1 (and its return; `cancel 1 only` for just that flight) |
| `help` | Show the commands |

A plane you add is checked right away; if it's already flying, the "airborne" alert arrives within seconds. Entries with an end date remove themselves ("⌛ Stopped watching UA1234"). Each person can only change their own list. Text commands can be turned off in **⚙ Settings**.

## Trips: where's my plane?

Before a flight, the plane you'll fly on is usually still finishing an earlier flight somewhere else. If that runs late, so does yours. A trip follows that plane and tells you:

- ✈️ when it's on its way to your airport, with an arrival estimate and how long that leaves before your departure
- ⏳ / ⚠️ if it will land within 45, then 20, minutes of your departure, and 🧳 if it's running 15+ minutes later than announced
- 🛬 when it lands at your airport, or that it's already there
- 🧳 if it's flying an earlier flight first

**Add a trip** with **+ Add trip** on the dashboard, or by text:

- **Without an AeroDataBox key**, say which plane it is. Your airline app usually shows it under "Where's my plane?": `inbound UA1234 N38473 dep 4:30pm` (or the inbound flight number instead of the tail). Add `tomorrow`, a date `10/20` and `from IAD` if needed.
- **With an AeroDataBox key**, `inbound UA1234 11/14` is enough. TailWatcher looks up your departure time, finds the assigned plane once the airline picks one, and tells you if the plane or your time changes. It checks weekly when the trip is far off, daily in the last two weeks, and four times on the last day: about 20 of the free plan's 400 monthly requests for a trip booked a month ahead.

**Round trips.** Going and coming back? Enter both flights at once: fill in **Return flight** on **+ Add trip**, or text `inbound UA1234 11/14 return UA5678 11/21`. Without an AeroDataBox key, give each flight its plane and time: `inbound UA1234 N38473 11/14 dep 4:30pm return UA5678 N12345 11/21 dep 6pm`. Already added your flight out? Text `return 1 UA5678 11/21` to add the flight home to trip 1.

- The flight home leaves from where your flight out lands. Add `from LAS` after the return flight if it doesn't.
- Times you type are local to the airport the flight leaves from: `dep 6pm from LAS` means 6pm in Las Vegas. If TailWatcher doesn't know that airport yet (no AeroDataBox key and no `from`), it reads the time in its own time zone (**⚙ Settings**), so add `from LAS` to a return that leaves from another time zone. Messages and the dashboard always show times in TailWatcher's time zone.
- Both flights are listed together and numbered one after the other. `change` edits one flight; `share` and `cancel` cover both, unless you add `only` (`cancel 2 only`).
- With an AeroDataBox key, each flight is checked on its own schedule, so a round trip booked a month ahead uses about 40 of the 400 free monthly requests.

**If the airline renumbers or cancels your flight**, TailWatcher notices on its next check, tells you, and suggests the likely new flight number. Reply with the `change` it suggests to switch; it never switches by itself.

Arrival estimates come from the plane's live position and speed, so treat them as an early warning rather than the airline's official time. Trips clear themselves a few hours after departure.

## Sharing a trip with family

Your trip alerts are about the plane coming to get *you*; family usually wants to know when your flight leaves and lands. Tick their names under **Share with** on the trip form, or text `share 1 Mom & Dad`.

They get a note that you shared a flight, a heads-up if the time changes or the flight disappears (with an AeroDataBox key), and departure and landing alerts on the day. They don't get your inbound-plane updates. TailWatcher follows your flight only around departure, so a flight shared weeks ahead won't alert on the other days it flies. Changing or cancelling the trip updates them too. Sharing a round trip covers both flights, with one note listing both.

## Looking up a plane

`info N12345` works for any aircraft, watched or not, and replies with what it is, its owner and registration (US N-numbers, from the FAA registry: city and state only; the **FAA record** button has the rest), its engine, where it is right now, and a photo when one exists. `info UA1234` looks up whichever plane is flying that flight right now. Flags show military aircraft and planes hidden from FlightAware and Flightradar24.

## Using the dashboard

The Web UI shows everyone's watchers and trips in one place:

- **Trips:** route, departure, the plane flying in, how far along it is, and when TailWatcher checks next
- **Watchers:** each person's planes and flights, what's airborne now, and live-map links
- **Activity:** recent alerts, replies, text commands and edits
- **System:** whether notifications, text commands and trip lookups are working

Add and change things right on the page: **+ Add trip**, **+ Add watcher**, **+ Aircraft**, and **Edit** on any trip, watcher or aircraft. The switch in the top corner picks a look, **Modern** or **Board** (an airport departures board with split-flap tiles), and each browser remembers it. **? Help** opens this guide.

## Settings and where alerts go

**⚙ Settings** on the dashboard (or **Configure** in StartOS) holds:

- **Notification server**
    - **ntfy.sh** (default): the free public ntfy service. Nothing to install. Each person's topic is a long random name, which is what keeps their alerts private. iPhones get alerts instantly.
    - **This server's NTFY**: alerts stay on your hardware. Install NTFY, choose this option, enter NTFY's admin password and tap **Set up NTFY for me**. TailWatcher sets up its own NTFY user and token, and phones connect either **without a login** (recommended; just the Connect phone link) or with **one NTFY login per person** (TailWatcher creates them; **Connect phone** has a **Create NTFY login** button for people added later). The admin password is used for that one step and never saved.
    - **Another ntfy server**, at an address you enter.
- **AeroDataBox key** (optional): for trips that find their plane automatically. Subscribe to the free Basic plan at rapidapi.com/aedbx-aedbx/api/aerodatabox and paste the key.
- **ADS-B feed** and **Check every**: adsb.fi is the default. All planes are checked together, one request per cycle.
- **Time zone**, **map buttons**, **text commands**, and **Require a password for this page** (get it from **Actions → Show Web UI Password**).

## For people getting alerts

*A short version to send to the people who get alerts. The Copy button in Help copies it.*

TailWatcher sends you alerts in the ntfy app when planes you follow take off or land.

- **Departed / is airborne:** the plane just took off (or just appeared in the air). Tap the alert to see it on a live map.
- **Landed:** it's on the ground.
- **📣 shared a flight with you:** someone added you to their trip; you'll get its departure and landing.

You can type in your ntfy topic to manage your list: send a tail or flight number (`N12345`, `UA1234 for 2 days`) to follow it, `remove N12345` to stop, `list` to see your list, or `help` for everything.

To stop all alerts, unsubscribe from the topic in the ntfy app. On Android, set the ntfy app's battery use to **Unrestricted** so alerts arrive on time.

## Troubleshooting

### I'm not getting any alerts

- Run **Actions → Send Test Notification** in StartOS. If it reports a problem, the message says what to fix.
- Check the phone is subscribed to the right topic: open **Connect phone** for that person and compare the topic with the one in their ntfy app.
- On Android, set the ntfy app's battery use to **Unrestricted** (Settings → Apps → ntfy → Battery).
- Look at **System** on the dashboard: "needs attention" there explains what's wrong.

### Alerts arrive late on an iPhone

Self-hosted NTFY can't use Apple's instant push service, so iPhones may only receive alerts when the app is opened. Use **ntfy.sh** in **⚙ Settings** for instant iPhone alerts.

### A plane took off but there was no alert

- ADS-B coverage comes from volunteers. Small airports often have none on the ground, so the alert comes as "is airborne" once the plane is picked up, which can be a few minutes after takeoff.
- Check the tail or flight number with `info`. If `info` finds nothing while the plane is flying, it may not be broadcasting, or it may be in the FAA's privacy program, whose aircraft can't be tracked by tail number anywhere.
- For a flight number, some airlines broadcast a different callsign (see **Watching planes and flights**).

### "Too many requests" in System

The free ADS-B feeds limit how often anyone can ask. TailWatcher switches to the other feed and backs off automatically. If it keeps happening, raise **Check every** in **⚙ Settings**.

### Someone says their invite link has expired

Invites work for the number of days you picked. Open **Connect phone** for that person and create a new one.

### The Connect phone link doesn't open the app

Install the ntfy app first, then tap the link again. If it still doesn't open (some iPhones), use the web link under it, or add the topic by hand in the app: **+**, **Use another server**, then the server and topic shown in the dialog.

### Text commands get no reply

- Make sure **Text commands** is on in **⚙ Settings**.
- With this server's NTFY, run **Set up NTFY for me** again. Watchers created before version 0.12 have `tailwatcher_…` topics, which need their old NTFY permissions or a new topic (below).

### Give someone a new topic

**Edit** the watcher and tick **Give them a new topic**, then send them a fresh **Connect phone** link. Their old subscription stops getting alerts.

### My flight was renumbered or cancelled

With an AeroDataBox key, TailWatcher tells you and suggests the new flight number; reply with the `change` it suggests. Otherwise, `change 1 NEW123` (with the trip number from `trips`) updates the flight.

### AeroDataBox says the key was rejected or the quota is used up

Check the key in **⚙ Settings** (paste it again to replace it). The free plan resets monthly; TailWatcher keeps tracking trips you entered by hand meanwhile.

### I lost a password

- **The dashboard password:** StartOS → TailWatcher → **Actions → Show Web UI Password** (or **Reset Web UI Password**).
- **NTFY's admin password:** NTFY → **Actions → Reset User Password** → admin.

## Good to know

- Data comes from free, community-run ADS-B feeds (adsb.fi and adsb.lol). They're unfiltered, so planes hidden from FlightAware and Flightradar24 (FAA LADD) still appear.
- If NTFY is briefly unreachable, alerts are retried for 30 minutes and sent only to people who haven't received them yet.
- TailWatcher only sends an NTFY token to your own or a custom server, never to ntfy.sh.
