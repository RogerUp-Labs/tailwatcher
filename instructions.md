# TailWatcher

TailWatcher sends a push notification to your phone, through NTFY on this server, when an aircraft you follow takes off.

## Setup

1. **Create a publisher in NTFY.** Open **NTFY → Actions → Provision Publisher**. Enter Publisher ID `tailwatcher` and Topic `tailwatcher` (or any topic name you like). Copy the **token** (`tk_…`) it shows.
2. **Configure TailWatcher.** Open **TailWatcher → Actions → Configure**:
   - Add each **tail number** (e.g. `N12345`), with an optional nickname.
   - Set **NTFY Topic** to the topic from step 1, and paste the **token**.
3. **Subscribe on your phone.** In the NTFY Android app, add your server and subscribe to the same topic. Your NTFY user needs read access to it; grant it with **NTFY → Grant User Topic Access**.
4. Run **TailWatcher → Actions → Send Test Notification** to confirm it arrives.

## When you get an alert

- **Departed:** the aircraft was seen on the ground, then in the air.
- **Is airborne:** it appeared already flying after being off the radar for 20+ minutes. Many small airports have no ADS-B coverage at ground level, so this is often the first sign of a departure.
- **Landed / likely landed** (optional): it touched down, or dropped off the radar below 3,000 ft.

Tapping the alert opens the aircraft live on ADS-B Exchange (or adsb.lol, set in Configure).

## Good to know

- Data comes from free, community-run ADS-B feeds (adsb.lol or adsb.fi). Coverage depends on volunteer receivers, so remote areas can have gaps.
- These feeds are unfiltered: aircraft that FlightAware and Flightradar24 hide under the FAA's LADD program still appear. Aircraft in the FAA's privacy (PIA) program broadcast a rotating address and can't be tracked by tail number anywhere.
- The service's health check shows which watched aircraft are airborne right now.
- If the feed rate-limits TailWatcher, it backs off automatically (up to 10 minutes). Raise **Check Every** if you watch many aircraft.
