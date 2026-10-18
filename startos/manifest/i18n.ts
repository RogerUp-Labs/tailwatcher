export const short = {
  en_US:
    'Get a push notification when an aircraft or flight you follow takes off.',
}

export const long = {
  en_US:
    'TailWatcher watches tail numbers and airline flight numbers on public, unfiltered ADS-B data (adsb.lol or adsb.fi) and publishes to your NTFY server the moment one of them departs. Watch a flight number after booking a trip and the alert names the aircraft flying it. Set up a watcher for each person, with their own NTFY topic and list, which they can change by texting their topic ("N12345", "UA1234 for 2 days", "list"); trip entries remove themselves when they expire. Each alert gives the nearest airport, altitude, speed and heading, and a button that opens the aircraft live on ADS-B Exchange. It can also tell you when the aircraft lands, "info N12345" looks up any aircraft (type, FAA owner, live position and a photo), and "inbound UA1234" follows the plane flying in for your flight, warning you if it is running late.',
}

export const installAlert = {
  en_US:
    'TailWatcher sends alerts through NTFY on this server. Before configuring it, in NTFY run Create User "tailwatcher", then Grant User Topic Access for tailwatcher on topic "tailwatcher*" with Read-Write. Log in to the NTFY web UI as tailwatcher and create an access token under Account → Access tokens. Then run TailWatcher → Configure, paste the token and add a watcher with your tail numbers.',
}
