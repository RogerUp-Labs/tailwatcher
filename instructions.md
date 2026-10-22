# TailWatcher

TailWatcher sends push notifications to the people in your household when a plane they care about takes off or lands: a family member's flight, a friend's Cessna, or the plane flying in for your next trip. It works with any airline or aircraft, using free public ADS-B data, and delivers alerts through the free **ntfy** app.

## Getting started

1. Open TailWatcher's **Web UI**. The first time, it asks how people will sign in: no sign-in, one shared password, or **family accounts** so each person has their own login (see **Family accounts**). You can change it later in **⚙ Settings**.
2. Tap **+ Add watcher** for each person who should get alerts. A name is all it needs.
3. Tap **Connect phone** on that watcher and send them the link (see **Connecting a phone**).
4. Add what they want to follow with **+ Aircraft**: a tail number like `N12345` or a flight number like `UA1234`. They can also text these in themselves (see **Text commands**).
5. Optional: add a free **AeroDataBox** key in **⚙ Settings** so trips find the plane flying in for your flight on their own.

Nothing else is needed: alerts go through the public ntfy.sh service by default, so there's no NTFY package, account or token to set up. To keep alerts on your own server instead, see **Settings and where alerts go**.

## Connecting a phone

Each watcher has their own notification topic, a long random name that TailWatcher picks. Open **Connect phone** on that watcher. Distance doesn't matter: someone in another state gets alerts the same way.

**Send an invite link** (best when they're not with you): type your name, pick how long the link should work (7 days by default), tap **Create invite link**, then **Send invite** to text it, or send it by iMessage, Signal or email. It's a normal web link, so it's tappable in any messaging app. It opens a page that walks them through installing ntfy and subscribing in two taps. Active invites are listed in the dialog, where **Cancel** stops one. Invite links need TailWatcher to have a public address (in StartOS, for example through StartTunnel; with Docker, see **Running without a Start9**); without one, they only work on your home network.

**With their phone in hand**, use the steps under the invite box:

1. Install the free **ntfy** app (Google Play, F-Droid or the App Store; the links are in the dialog).
2. Tap the subscribe link on their phone. **Send link** shares it; **Copy link** copies it. The ntfy app opens with their alerts ready to subscribe.

On Android the subscription gets a friendly name like **TailWatcher · Dad** from the link. The iPhone app can't rename subscriptions, so it shows the server and topic (see **The ntfy app shows a long random topic name**).

If the link doesn't open the app, open the web link shown under it, or in the ntfy app tap **+**, turn on **Use another server**, and enter the server and topic shown in the dialog.

**With your own NTFY**, phones also have to trust its https certificate. A Start9 signs its addresses (.local, LAN and public IP addresses, including StartTunnel's) with its own root certificate, which phones don't know, so a phone that hasn't installed it gets a certificate error in the ntfy app (see **The ntfy app says "Trust anchor for certification path not found"**). That's easy to miss when your own phone trusted it long ago. StartTunnel forwards traffic to your Start9 but doesn't change the certificate: on its public IP address, phones still see the Start9's own. Two ways around it:

- **Recommended for people outside your household:** give NTFY a public domain (a domain name you own) through your StartTunnel gateway, with a Let's Encrypt certificate. Every phone trusts that already. See Start9's [public access guide](https://docs.start9.com/start-os/0.4.0.x/public-access.html); do the same for TailWatcher's Web UI so invite links use the domain too. TailWatcher picks up both domains by itself and prefers them over a public IP; then send new **Connect phone** links or invites.
- **For your own phones:** install your Start9's root certificate on each one ([Start9's guide](https://docs.start9.com/start-os/0.4.0.x/trust-ca.html)).

ntfy.sh needs neither.

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

### Keep plane alerts separate from trips

Plane spotters can give these alerts their own topic, so the main topic carries only trips, shared trips and replies. **Edit** the watcher and tick **Separate topic for plane alerts**, then open **Connect phone** and subscribe to the second link too. Text commands work in either topic, and the reply comes back in the topic you typed in. Untick it to send plane alerts back to the main topic.

## Text commands

People can manage their own trips and watch list by typing in their topic in the ntfy app (the message bar at the bottom). TailWatcher replies in the same conversation. `help` sends the same list, trip commands first.

| Send | Does |
|---|---|
| `inbound UA1234 N38473 dep 4:30pm` | Follow the plane flying in for your flight |
| `inbound UA1234 11/14 return UA5678 11/21` | A round trip: your flight out and your flight home together |
| `inbound UA1234 then UA567` | A connecting flight: I'll tell you how long you'll have to make it |
| `trips` | Your trips, numbered |
| `change 1 AA5678` | Update trip 1: a new flight number, `dep 5:10pm`, a plane, a date `11/15`, `from DFW` or `to DEN` |
| `return 1 UA5678 11/21` | Add the flight home to trip 1 |
| `connect 1 UA567` | Add a connecting flight after trip 1 |
| `cancel 1` | Stop tracking trip 1 (and its connections and return; `cancel 1 only` for just that flight) |
| `share 1 Mom & Dad` | Send another watcher your flight's departure and landing (`unshare` to stop). Covers every flight of the trip |
| `N12345` | Watch tail number N12345 |
| `UA1234` (or `DL 89`) | Watch a flight number |
| `add N12345 Vegas trip` | Watch it with a nickname (or rename one you already watch) |
| `UA1234 for 2 days` | Watch it, then stop automatically. Also `3d`, `12h`, `until fri`, `until tomorrow` |
| `remove N12345` | Stop watching |
| `info N12345` | Look up any aircraft: what it is, who owns it, where it is now |
| `list` | Your trips and watch list, what's airborne, and time left on expiring entries |
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

**Round trips.** Going and coming back? Enter both flights at once: open **Return flight** on **+ Add trip** and fill it in, or text `inbound UA1234 11/14 return UA5678 11/21`. Without an AeroDataBox key, give each flight its plane and time: `inbound UA1234 N38473 11/14 dep 4:30pm return UA5678 N12345 11/21 dep 6pm`. Already added your flight out? Text `return 1 UA5678 11/21` to add the flight home to trip 1.

- The flight home leaves from where your flight out lands. Add `from LAS` after the return flight if it doesn't.
- Times you type are local to the airport the flight leaves from: `dep 6pm from LAS` means 6pm in Las Vegas. If TailWatcher doesn't know that airport yet (no AeroDataBox key and no `from`), it reads the time in its own time zone (**⚙ Settings**), so add `from LAS` to a return that leaves from another time zone. Messages and the dashboard always show times in TailWatcher's time zone.
- Both flights are listed together and numbered one after the other. `change` edits one flight; `share` and `cancel` cover both, unless you add `only` (`cancel 2 only`).
- With an AeroDataBox key, each flight is checked on its own schedule, so a round trip booked a month ahead uses about 40 of the 400 free monthly requests.

**Connecting flights.** Changing planes on the way? Add the next flight with `then`: `inbound UA1234 11/14 then UA567`, or tap **+ Add connection** on **+ Add trip** once for each flight after the first. It works on the way back too: **+ Add return connection**, or `… return UA5678 11/21 then UA910`. Already added the first flight? Text `connect 1 UA567`, or **Edit** the last flight and add it there. Up to 8 flights in a row each way.

- A connection is on the same day as the flight before it and leaves from where that flight lands. A time earlier than the first flight's means the next morning. Add a date or `from DEN` if not.
- Without an AeroDataBox key, give the connection its own time and plane: `inbound UA1234 N38473 dep 8am from IAD then UA567 N12345 dep 1:10pm from DEN`. Add `from` when the connection leaves from another time zone, so the time is read right.
- On the day, TailWatcher follows your first flight once it takes off and tells you how many minutes you'll have to make the next one, ⏳ if that drops under 40 minutes, ⚠️ under 15, and 🛬 when you land with how long until your connection leaves. With an AeroDataBox key it also warns ahead of time if the scheduled connection is tight or doesn't work.
- Each flight still gets its own where's-my-plane alerts. All the flights are listed and numbered together; `share` and `cancel` cover them all unless you add `only`.

**A flight with a stop** (one flight number, e.g. Chicago → Denver → Las Vegas): with an AeroDataBox key TailWatcher assumes you board where the flight starts and stay on to the end, and says so. Add `from DEN` if you board at the stop, or `to DEN` if you get off there. Family you share it with get the landing alert at your destination, not at the stop.

**If the airline renumbers or cancels your flight**, TailWatcher notices on its next check, tells you, and suggests the likely new flight number. Reply with the `change` it suggests to switch; it never switches by itself.

Arrival estimates come from the plane's live position and speed, so treat them as an early warning rather than the airline's official time. Trips clear themselves a few hours after departure.

## Importing a trip

Instead of typing flight numbers, tap **Import** next to **+ Add trip** and paste your booking confirmation or choose a file. TailWatcher finds the flights and fills in the **Add trip** form, with connections and the flight home where it can tell them apart. Check every field, fix anything it got wrong, then tap **Add trip**. Nothing is saved until you do.

| What you give it | What it reads |
| --- | --- |
| Pasted text from a confirmation email, an airline app or a booking site | Flight numbers (`UA 1234`, `United 1234`), with the date, departure time and airport codes nearest each |
| A saved email (.eml) | The hidden flight details most airlines and booking sites include for Gmail's flight cards; otherwise a calendar invite attached to it; otherwise its text |
| A calendar file (.ics), from an airline's "Add to calendar", TripIt or Kayak Trips | One flight per event, at the event's start time |
| A web page (.html) or text file (.txt) | The same as pasted text |

- **PDFs, screenshots and Word files can't be read.** Open the file, select all the text, copy it and paste it into the box instead.
- **Saving an email as .eml:** in Gmail on a computer, open the email, then ⋮ → **Download message**. In Outlook, **File → Save As**. In Apple Mail, drag the email to the desktop. On a phone, pasting the email's text is easiest.
- Flights a day or less apart, each leaving from where the one before lands, become connections; a later flight becomes the return. Flights that look like a separate trip are listed so you can add them on their own.
- Times are read as written in the confirmation, which is local to the airport each flight leaves from.
- Reading a confirmation happens on your server and uses none of your AeroDataBox requests. Lookups start once you add the trip, as usual.

## Sharing a trip with family

Your trip alerts are about the plane coming to get *you*; family usually wants to know when your flight leaves and lands. Tick their names under **Share with** on the trip form, or text `share 1 Mom & Dad`.

With **family accounts**, the list shows everyone on this TailWatcher by name, and the trip also appears under **Shared with me** on their dashboard: your flight, where it is once it's in the air, and the plane flying in for it. They can't change it. **Stop following** there takes them off it and lets you know.

They get a note that you shared a flight, a heads-up if the time changes or the flight disappears (with an AeroDataBox key), and departure and landing alerts on the day. They don't get your inbound-plane updates. TailWatcher follows your flight only around departure, so a flight shared weeks ahead won't alert on the other days it flies. Changing or cancelling the trip updates them too. Sharing a round trip or connecting flights covers every flight, with one note listing them all. When you land somewhere to change planes, their landing alert says which flight you're connecting to.

## Looking up a plane

`info N12345` works for any aircraft, watched or not, and replies with what it is, its owner and registration (US N-numbers, from the FAA registry: city and state only; the **FAA record** button has the rest), its engine, where it is right now, and a photo when one exists. `info UA1234` looks up whichever plane is flying that flight right now. Flags show military aircraft and planes hidden from FlightAware and Flightradar24.

## Family accounts

Family accounts give each person their own login, so they see only their own watchers and trips. Trips are the private part: nobody else in the household sees where you're flying unless you share the trip with them.

1. Turn it on at first setup or in **⚙ Settings → Signing in to this page → Family accounts**. You pick your own username and password and become the first admin. Every existing watcher starts out as yours.
2. Add each family member from **👥 People**, one of two ways:
    - **Sign-up link** (easiest; needs a public address, like invite links): text them the link. They open it, pick their own username and password, and they're signed in, with a watcher of their own and the steps to get alerts on their phone. Each link works once and expires (7 days unless you pick otherwise); cancel an unused one on the People page.
    - **+ Add person**: you pick a username, their name and a temporary password, then send them this page's address with both. **Make them a watcher too** gives them their own alerts and trips.
3. Already had a watcher for them? Pick their name next to it under **People** to move it to their account. Tick **give it a new topic** first if your phone was subscribed to it, so your phone stops getting their alerts.
4. Anyone can change their password, name and time zone under **👤 My account**.

What each person sees:

| | Their own | Shared with them | An admin who isn't them |
|---|---|---|---|
| Watchers and planes | See and change | No | Names only (People) |
| Trips | See, change, share | Read only, under **Shared with me** | No |
| Activity | Their own alerts and texts | No | No |
| ⚙ Settings, People | Admins only | | |

A parent can look after a child's or grandparent's watcher from their own login: move it to their account. One account can have several watchers.

Good to know:

- Accounts keep things private from other people in the household, not from whoever runs the server, who can read TailWatcher's files.
- A person's phone talks to ntfy, not to TailWatcher, so anyone subscribed to their topic still gets their alerts and can text commands to it. Their topic and **Connect phone** link only show on their own dashboard.
- Forgot a password? Tap **Forgot your password?** on the sign-in page and type your username. TailWatcher sends a 6-digit code to your alerts in the ntfy app (your watchers' topics stand in for an email address); type it with a new password. Codes work for 10 minutes, one a minute. No watcher or no phone connected? An admin sets a new password with **Reset password** on the People page. For the admin, see **I lost a password**.
- Each person can have their own time zone (**My account**, or **Time zone** when editing a watcher). Their alerts, replies and "until fri" use it, and shared-trip alerts come in the recipient's time zone.

## Using the dashboard

The Web UI shows the watchers and trips you can see (everyone's, unless family accounts are on) in one place:

- **Trips:** route, departure, the plane flying in (and roughly where it is), how far along it is, and when TailWatcher checks next
- **Shared with me:** trips other people shared with you, when there are any
- **Watchers:** each person's planes and flights, what's airborne now, and live-map links. A plane that landed and went quiet shows **Parked** with when it was last seen, and its live-map link comes back when it's on the radar again. Next to the live-map link is roughly where the plane is ("near Denver, CO", "40 nm NE of Denver, CO", or the airport it's at), or where it was last seen
- **Activity:** recent alerts, replies, text commands and edits
- **System:** whether notifications, text commands and trip lookups are working

Add and change things right on the page: **+ Add trip**, **+ Add watcher**, **+ Aircraft**, and **Edit** on any trip, watcher or aircraft. The switch in the top corner picks a look, **Modern** or **Board** (an airport departures board with split-flap tiles), and each browser remembers it. **? Help** opens this guide as a full page, with the topics listed down the side (under **Contents** on a phone). Back closes it, and **Open in new tab** keeps it open next to the dashboard.

## Settings and where alerts go

**⚙ Settings** on the dashboard (or **Configure** in StartOS) holds:

- **Notification server**
    - **ntfy.sh** (default): the free public ntfy service. Nothing to install. Each person's topic is a long random name, which is what keeps their alerts private. iPhones get alerts instantly.
    - **This server's NTFY**: alerts stay on your hardware. Install NTFY, choose this option, enter NTFY's admin password and tap **Set up NTFY for me**. TailWatcher sets up its own NTFY user and token, and phones connect either **without a login** (recommended; just the Connect phone link) or with **one NTFY login per person** (TailWatcher creates them; **Connect phone** has a **Create NTFY login** button for people added later). The admin password is used for that one step and never saved. Phones must trust NTFY's https address: give it a public domain, or install your Start9's root certificate on each phone (see **Connecting a phone**).
    - **Another ntfy server**, at an address you enter.
- **AeroDataBox key** (optional): for trips that find their plane automatically. Subscribe to the free Basic plan at rapidapi.com/aedbx-aedbx/api/aerodatabox and paste the key.
- **ADS-B feed** and **Check every**: adsb.fi is the default. All planes are checked together, one request per cycle.
- **Time zone** (the default; each watcher can have their own), **map buttons** and **text commands**.
- **Signing in to this page:** no sign-in, **one shared password** (from **Actions → Show Web UI Password**), or **family accounts** (see **Family accounts**). Only admins see Settings.

## Running without a Start9

TailWatcher also runs as an ordinary Docker container: on a Synology, Unraid or TrueNAS NAS, a Raspberry Pi, or any computer with Docker. It's the same app, with the same dashboard and alerts.

1. Get **docker-compose.yml** from the `docker` folder of github.com/RogerUp-Labs/tailwatcher.
2. Start it. On a Synology: **Container Manager → Project → Create**, pick a folder (for example `/docker/tailwatcher`), choose **Upload docker-compose.yml**, and finish. Elsewhere: `docker compose up -d` in the folder with the file.
3. Find the dashboard password in the container's log (Container Manager → Container → tailwatcher → **Log**), then open `http://<your NAS>:8080` and sign in with it. The first time, choose how people sign in from then on.
4. Carry on with **Getting started**. Alerts use ntfy.sh unless you change it.

Settings that StartOS would fill in are set in docker-compose.yml instead:

| Setting | What it's for |
|---|---|
| `NTFY_URL` | Your own ntfy, as TailWatcher reaches it: `http://<your NAS>:<port>`, or `http://ntfy:80` for the ntfy service in the same file. Then pick **This server's NTFY** in **⚙ Settings**. |
| `NTFY_PHONE_URL` | The https address phones use for that ntfy, so **Connect phone** gives a one-tap link. Its certificate must be one phones trust (for example Let's Encrypt from your reverse proxy); a self-signed one gives a certificate error in the ntfy app. |
| `TAILWATCHER_PUBLIC_URL` | TailWatcher's own https address, if you put it behind a reverse proxy. Invite and sign-up links need it. |
| `TAILWATCHER_PASSWORD` | Your own dashboard password instead of the generated one. |

Good to know:

- Everything TailWatcher keeps (watchers, trips, history) is in the `data` folder next to docker-compose.yml. Back it up; there is no StartOS backup.
- The dashboard password is on by default with Docker, since a NAS port can be reachable from more places than a Start9's. You can turn it off, or switch to family accounts, in **⚙ Settings**.
- `docker exec tailwatcher python /app/tailwatcher.py accounts` lists the family accounts, and `reset-password USERNAME` gives one a new password.
- An ntfy server that allows anonymous publishing needs no token. If yours requires logins, either paste a token in **⚙ Settings** or use **Set up NTFY for me** with its admin password.
- To update: Container Manager → Project → tailwatcher → **Action → Build** (or `docker compose pull && docker compose up -d`).

## For people getting alerts

*A short version to send to the people who get alerts. The Copy button in Help copies it.*

TailWatcher sends you alerts in the ntfy app when planes you follow take off or land.

- **Departed / is airborne:** the plane just took off (or just appeared in the air). Tap the alert to see it on a live map.
- **Landed:** it's on the ground.
- **📣 shared a flight with you:** someone added you to their trip; you'll get its departure and landing.

You can type in your ntfy topic to manage your list: send a tail or flight number (`N12345`, `UA1234 for 2 days`) to follow it, `remove N12345` to stop, `list` to see your list, or `help` for everything.

On iPhone the subscription shows a long random topic name; that's normal (on Android it's called TailWatcher and the watcher's name). To stop all alerts, unsubscribe from the topic in the ntfy app. On Android, set the ntfy app's battery use to **Unrestricted** so alerts arrive on time.

## Troubleshooting

### I'm not getting any alerts

- Run **Actions → Send Test Notification** in StartOS (with Docker: `docker exec tailwatcher python /app/tailwatcher.py test`). If it reports a problem, the message says what to fix.
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

### The ntfy app says "Trust anchor for certification path not found"

This (or another certificate error, such as "certificate not trusted") means the phone doesn't trust your NTFY's https certificate. It only happens with your own NTFY, not ntfy.sh. A Start9 signs its .local, LAN and IP addresses, including a StartTunnel public IP, with its own root certificate, and a phone only trusts it once that certificate is installed. A NAS or reverse proxy with a self-signed certificate does the same.

- **For your own household's phones:** install your Start9's root certificate on the phone. Download it from StartOS (**System → Root CA**), then follow [Start9's guide](https://docs.start9.com/start-os/0.4.0.x/trust-ca.html) for Android or iPhone. On Android it's **Settings → Security → Encryption & credentials → Install a certificate → CA certificate**.
- **For anyone else:** give NTFY a public domain with a Let's Encrypt certificate through your StartTunnel gateway (Start9's [public access guide](https://docs.start9.com/start-os/0.4.0.x/public-access.html)), so every phone trusts it. A StartTunnel public IP alone isn't enough: Let's Encrypt doesn't issue certificates for IP addresses. Then send them a new **Connect phone** link or invite. With Docker, put ntfy behind a reverse proxy with a Let's Encrypt certificate and set `NTFY_PHONE_URL` to that address.
- **Or switch to ntfy.sh** in **⚙ Settings**, which needs no certificate setup, and send new links.

The invite page itself can show a browser warning for the same reason if TailWatcher's public address is a StartTunnel IP; a public domain fixes that too.

### The ntfy app says "not authorized" (HTTP 401 or 403)

This only happens with your own NTFY. Check these in order:

- **An old login saved in the app.** A wrong or outdated login is refused even on topics anyone can open. In the ntfy app, open **Settings → Manage users** and delete any user listed for your NTFY's address, then subscribe again.
- **An old topic.** Phones without a login can only open topics starting with `tw-`. Watchers made by older versions have `tailwatcher_…` topics: **Edit** the watcher, tick **Give them a new topic**, and send a fresh **Connect phone** link.
- **Logins per person.** If **⚙ Settings** has phones connect with one NTFY login per person, they need theirs from **Connect phone → Create NTFY login**, added in the app under **Settings → Manage users**.

### The ntfy app shows a long random topic name

Topics are long and random on purpose: on ntfy.sh, the name is the only lock. On **Android**, subscribe links and invites name the subscription after the watcher, like **TailWatcher · Dad**, when it's first added. To rename one added earlier, open it in the ntfy app and tap ⋮ → **Subscription settings** → **Display name**. In the ntfy **web app**, the topic's ⋮ menu has **Change display name**. The **iPhone** app has no display names yet, so it always shows the server and topic; each alert's title still says which plane or trip it's about.

### Someone says their invite link has expired

Invites work for the number of days you picked. Open **Connect phone** for that person and create a new one. A sign-up link also stops working once someone has used it; make a new one on the **People** page.

### The Connect phone link doesn't open the app

Install the ntfy app first, then tap the link again. If it still doesn't open (some iPhones), use the web link under it, or add the topic by hand in the app: **+**, **Use another server**, then the server and topic shown in the dialog.

### Text commands get no reply

- Make sure **Text commands** is on in **⚙ Settings**.
- With this server's NTFY, run **Set up NTFY for me** in **⚙ Settings** again. That's also the fix when **System** says text commands "can't read topic" (HTTP 403): the token TailWatcher uses has no access to that topic, usually because it was set up by hand before topics started with `tw-`. It covers older `tailwatcher_…` topics too.

### Give someone a new topic

**Edit** the watcher and tick **Give them a new topic**, then send them a fresh **Connect phone** link. Their old subscription stops getting alerts.

### My flight was renumbered or cancelled

With an AeroDataBox key, TailWatcher tells you and suggests the new flight number; reply with the `change` it suggests. Otherwise, `change 1 NEW123` (with the trip number from `trips`) updates the flight.

### AeroDataBox says the key was rejected or the quota is used up

Check the key in **⚙ Settings** (paste it again to replace it). The free plan resets monthly; TailWatcher keeps tracking trips you entered by hand meanwhile.

### I lost a password

- **The dashboard password:** StartOS → TailWatcher → **Actions → Show Web UI Password** (or **Reset Web UI Password**). With Docker, it's in the container's log, or run `docker exec tailwatcher python /app/tailwatcher.py password` (`reset-password` makes a new one).
- **Your family account:** tap **Forgot your password?** on the sign-in page for a code in your ntfy app, or ask an admin to use **Reset password** on the People page.
- **The admin's family account:** StartOS → TailWatcher → **Actions → Reset Web UI Password** makes a new password for the first admin; sign in with it and change it under **My account**. With Docker, run `docker exec tailwatcher python /app/tailwatcher.py reset-password USERNAME`.
- **NTFY's admin password:** NTFY → **Actions → Reset User Password** → admin.

## Good to know

- Data comes from free, community-run ADS-B feeds (adsb.fi and adsb.lol). They're unfiltered, so planes hidden from FlightAware and Flightradar24 (FAA LADD) still appear.
- If NTFY is briefly unreachable, alerts are retried for 30 minutes and sent only to people who haven't received them yet.
- TailWatcher only sends an NTFY token to your own or a custom server, never to ntfy.sh.
