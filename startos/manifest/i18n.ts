export const short = {
  en_US:
    'Get a push notification when an aircraft or flight you follow takes off.',
}

export const long = {
  en_US:
    'TailWatcher watches tail numbers and airline flight numbers on public, unfiltered ADS-B data (adsb.lol or adsb.fi) and publishes to your NTFY server the moment one of them departs. Watch a flight number after booking a trip and the alert names the aircraft flying it. Set up a watcher for each person, with their own NTFY topic and list, which they can change by texting their topic ("N12345", "UA1234 for 2 days", "list"); trip entries remove themselves when they expire. Each alert gives the nearest airport, altitude, speed and heading, and a button that opens the aircraft live on ADS-B Exchange. It can also tell you when the aircraft lands, and "info N12345" looks up any aircraft: type, FAA owner, live position and a photo.',
}

export const installAlert = {
  en_US:
    'TailWatcher sends alerts through NTFY on this server. Before configuring it, open NTFY → Actions → Provision Publisher, enter Publisher ID "tailwatcher" and Topic "tailwatcher*", and copy the token it returns. Then run TailWatcher → Configure, add a watcher with your tail numbers and paste the token.',
}
