# Scheduling daily updates

## GitHub Actions (hosted)
`.github/workflows/update.yml` runs every day at 11:17 UTC and on demand (Actions → Update forecast → Run workflow).
It caches `data/` between runs, commits `site/data/` and deploys `site/` to GitHub Pages.
Setup: push the repo to GitHub, enable Pages with source "GitHub Actions", optionally add an
`FEC_API_KEY` secret.

## cron (Linux/macOS)
```
15 7 * * * cd /path/to/electionpredictions && /usr/local/bin/uv run electionpredictions run >> data/run.log 2>&1
```

## launchd (macOS)
Save as `~/Library/LaunchAgents/com.electionpredictions.update.plist`, then
`launchctl load ~/Library/LaunchAgents/com.electionpredictions.update.plist`.
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.electionpredictions.update</string>
  <key>ProgramArguments</key><array>
    <string>/bin/zsh</string><string>-lc</string>
    <string>cd /Users/jamesgriffis/electionpredictions &amp;&amp; uv run electionpredictions run &gt;&gt; data/run.log 2&gt;&amp;1</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>15</integer></dict>
  <key>RunAtLoad</key><false/>
</dict></plist>
```
