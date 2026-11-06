# Scheduling updates

## GitHub Actions (hosted)
`.github/workflows/update.yml` rebuilds the 2028 model every 15 minutes (cron `7,22,37,52 * * * *`) and on demand
(Actions → Update forecast (2028) → Run workflow; tick *dry_run* to skip saving and deploying). Each run restores the
model state from the `forecast-data` branch (database + published data, one commit replaced every run) and the HTTP
cache from `actions/cache`, runs the pipeline, pushes the new state and deploys `site/` to GitHub Pages.
Setup: enable Pages with source "GitHub Actions" and add the `OPENCODE_API_KEY` secret; `FEC_API_KEY` is optional.
GitHub may start scheduled runs late, or skip some, when it is busy; the next run catches up.

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
