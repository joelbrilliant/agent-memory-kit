# Scheduled ingest

`ingest.py` does a full rebuild every run, so keeping the index fresh is just a
matter of running it on a schedule. For a corpus of a few thousand files this
takes about a second, so a daily rebuild is more than enough. Both examples
below write ingest output to `ingest.log` in the repo (gitignored).

Adjust the paths to match your clone. Use `which python3` to find your
interpreter if `python3` is not on the scheduler's PATH.

## macOS (launchd)

Save this as `~/Library/LaunchAgents/com.example.agent-memory-ingest.plist`,
then load it with `launchctl load ~/Library/LaunchAgents/com.example.agent-memory-ingest.plist`.
It runs daily at 08:45 local time.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.example.agent-memory-ingest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/path/to/agent-memory-kit/ingest.py</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>45</integer>
  </dict>
  <key>StandardOutPath</key>
  <string>/path/to/agent-memory-kit/ingest.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/agent-memory-kit/ingest.log</string>
</dict>
</plist>
```

To unload it later: `launchctl unload ~/Library/LaunchAgents/com.example.agent-memory-ingest.plist`.

## Linux (cron)

Add this line with `crontab -e`. It runs daily at 08:45 and appends output to
`ingest.log`.

```
45 8 * * * /usr/bin/python3 /path/to/agent-memory-kit/ingest.py >> /path/to/agent-memory-kit/ingest.log 2>&1
```
