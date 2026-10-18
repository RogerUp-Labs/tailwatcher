export const short = {
  en_US:
    'Get a push notification when an aircraft or flight you follow takes off.',
}

export const long = {
  en_US:
    'TailWatcher watches tail numbers and airline flight numbers on public, unfiltered ADS-B data (adsb.lol or adsb.fi) and publishes to your NTFY server the moment one of them departs. Watch a flight number after booking a trip and the alert names the aircraft flying it. Set up a watcher for each person, with their own NTFY topic and list, which they can change by texting their topic ("N12345", "UA1234 for 2 days", "list"); trip entries remove themselves when they expire. Each alert gives the nearest airport, altitude, speed and heading, and a button that opens the aircraft live on ADS-B Exchange. It can also tell you when the aircraft lands, "info N12345" looks up any aircraft (type, FAA owner, live position and a photo), and "inbound UA1234" follows the plane flying in for your flight, warning you if it is running late. Share a trip and family get your flight\'s departure and landing. A web dashboard shows every watcher\'s aircraft and trips and recent alerts, and lets you add and edit them.',
}

export const installAlert = {
  en_US:
    'Open the TailWatcher Web UI, add a watcher for each person, and use "Connect phone" to send them a one-tap link for the free ntfy app. Alerts go through the public ntfy.sh service by default; to keep them on your own hardware instead, install NTFY and use "Set up NTFY for me" in the Web UI\'s Settings.',
}
