# Election Night — Apple TV app

A full-screen, always-on results board for the 2026 Senate and House races (no governors):

- **Senate**: seats won and leading per party (including the 65 seats not up), a bar with the 51-seat
  line, and a state map colored by each race (won / leading / polls closed / polls open). The small
  north-eastern states are drawn as labeled boxes off the coast.
- **House**: the same scoreboard against 218, and a tile map with one square per district, laid out
  roughly where each district sits and grouped by state.
- **Key races**: Lean and Tossup races (plus Likely Senate races), anything within 5 points with votes in,
  and every flip, four at a time, rotating every 10 seconds.
- Refreshes every 15 minutes until the first polls close (6 pm ET), then every 5 minutes; **Play/Pause**
  on the Siri Remote refreshes immediately. Demo mode steps every minute.
- Keeps the screen awake (the Apple TV won't dim or start its screen saver while the app is open).

The data is the same as the website's (`site/live.js`): live votes and race calls from the AP via The New
York Times' results feed (CNN as backup), with the results desk's manual overrides
(`data/results.json`) on top, and the site's saved snapshot (`data/results-auto.json`) when the feeds
can't be reached. Race names, sides, ratings and model margins come from the published
`data/races.json` / `summary.json` / `schedule.json`.

## Put it on your Apple TV

1. On the Apple TV: **Settings → Remotes and Devices → Remote App and Devices** (Mac and Apple TV on the
   same network).
2. On the Mac: open `tvos/ElectionNight.xcodeproj` in Xcode, then **Window → Devices and Simulators**,
   pick the Apple TV under *Discovered* and enter the code it shows.
3. Choose the **ElectionNight** scheme and your Apple TV as the run destination, then **Run** (⌘R).
   Signing uses team `VHFS4A7KDU` (the team the Bedroom Apple TV is registered to); change it under
   *Signing & Capabilities* if needed. Xcode must be signed in to that team (Settings → Accounts).

Or try it in the simulator: pick an Apple TV simulator as the destination and Run.

**Demo mode** fills the board with made-up returns that advance each refresh, for checking the screen
before polls close: *Product → Scheme → Edit Scheme → Run → Arguments*, add `-demo`.

## Rebuilding the project and assets

The Xcode project is generated from `project.yml`:

```bash
cd tvos && xcodegen generate
```

Map data (`ElectionNight/Resources/maps.json`) comes from Census files: the 1:20m state cartographic
boundaries (`cb_2024_us_state_20m.zip`) and the 119th Congress district gazetteer
(`2024_Gaz_119CDs_national.zip`). Unzip both, then:

```bash
uv run --with pyshp python tvos/tools/make_maps.py <states_dir> <2024_Gaz_119CDs_national.txt> tvos/ElectionNight/Resources/maps.json
```

The House tiles use 2024 district locations only to place each seat; states that redrew lines for 2026
keep the same number of seats, so the board is unaffected. App icon and Top Shelf images:

```bash
uv run --with pillow python tvos/tools/make_icons.py
```
