# Scheduling updates

## GitHub Actions (hosted)
`.github/workflows/update.yml` rebuilds the 2028 model twice a day, at 2:00 AM and 2:00 PM Eastern year-round (both possible UTC hours are scheduled; a gate job keeps the one matching EDT/EST) and on demand
(Actions → Update forecast (2028) → Run workflow; tick *dry_run* to skip committing and deploying).
It caches `data/` between runs (the database holds the model's version history), commits `site/data/` and
deploys `site/` to GitHub Pages. Setup: enable Pages with source "GitHub Actions" and add the
`OPENCODE_API_KEY` secret (the revision step); `FEC_API_KEY` is optional.

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
