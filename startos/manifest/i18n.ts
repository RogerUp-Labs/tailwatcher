export const short = {
  en_US: 'Get a push notification when an aircraft you follow takes off.',
}

export const long = {
  en_US:
    'TailWatcher watches tail numbers on public, unfiltered ADS-B data (adsb.lol or adsb.fi) and publishes to your NTFY server the moment one of them departs. Set up a watcher for each person, with their own NTFY topic and aircraft list, which they can change by texting their topic (send a tail number to add it, "list" to see it). Each alert gives the nearest airport, altitude, speed and heading, and a button that opens the aircraft live on ADS-B Exchange. It can also tell you when the aircraft lands.',
}

export const installAlert = {
  en_US:
    'TailWatcher sends alerts through NTFY on this server. Before configuring it, open NTFY → Actions → Provision Publisher, enter Publisher ID "tailwatcher" and Topic "tailwatcher*", and copy the token it returns. Then run TailWatcher → Configure, add a watcher with your tail numbers and paste the token.',
}
