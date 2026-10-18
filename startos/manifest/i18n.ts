export const short = {
  en_US: 'Get a push notification when an aircraft you follow takes off.',
}

export const long = {
  en_US:
    'TailWatcher watches a list of tail numbers on public, unfiltered ADS-B data (adsb.lol or adsb.fi) and publishes to your NTFY server the moment one of them departs. Each alert gives the nearest airport, altitude, speed and heading, and a button that opens the aircraft live on ADS-B Exchange. It can also tell you when the aircraft lands.',
}

export const installAlert = {
  en_US:
    'TailWatcher sends alerts through NTFY on this server. Before configuring it, open NTFY → Actions → Provision Publisher, enter Publisher ID "tailwatcher" and the topic you want (e.g. "tailwatcher"), and copy the token it returns. Then run TailWatcher → Configure, add your tail numbers and paste the token.',
}
