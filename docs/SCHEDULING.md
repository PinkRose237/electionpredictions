# Scheduling updates

## GitHub Actions (hosted)
`.github/workflows/update.yml` rebuilds the 2028 model in a self-sustaining loop: each run ends by waiting for the
next clock slot and dispatching the next run, so updates land at :00, :15, :30 and :45 (`FORECAST_INTERVAL_MIN`,
default 15). The :00 run refreshes the hourly sources (polls, primaries, approval, ratings, news, markets) on the
hour, Eastern time. GitHub
throttles busy cron schedules, so the cron (`7,37 * * * *`) only restarts the loop if it ever stops; set the
repository variable `FORECAST_PAUSED=true` to pause. Also on demand
(Actions → Update forecast (2028) → Run workflow; tick *dry_run* to skip saving and deploying). Each run restores the
model state from the `forecast-data` branch (database + published data, one commit replaced every run) and the HTTP
cache from `actions/cache`, runs the pipeline, pushes the new state and deploys `site/` to GitHub Pages.
Setup: enable Pages with source "GitHub Actions" and add the `OPENCODE_API_KEY` secret; `FEC_API_KEY` is optional.
GitHub may start the backstop cron late, or skip it, when it is busy; the loop itself does not depend on it.

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
