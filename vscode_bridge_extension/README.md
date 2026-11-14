# claudown bridge (optional VS Code extension)

> **Optional community workaround, not the default path.** You don't need it for claudown to protect you in VS Code: the gate runs as a hook there and reads your transcripts automatically.

## Why it exists

The Claude Code panel in VS Code runs **hooks** but never runs the **`statusLine`** command. claudown's exact, zero-token sensor lives in `statusLine`, so inside the panel claudown falls back to estimating usage from local transcript files.

This stub does three things:

1. Runs `vscode_transcript_sensor.py --write` every 60 seconds. It reads local files only and makes no network calls.
2. Shows the newest reading in VS Code's status bar (`claudown 5h 42%`). It uses the exact status line number when it's fresh, and the transcript estimate otherwise.
3. Adds the command **claudown: Switch Claude Code to terminal mode**, which turns on Claude Code's own `claudeCode.useTerminal` setting. Terminal mode runs `statusLine`, which restores the full, exact sensor path inside VS Code.

If it can't determine usage, the status bar shows `claudown 5h ?` with an explanation. It never guesses.

## Build and install

You need [Node.js](https://nodejs.org) 18 or later.

```bash
cd vscode_bridge_extension
npx @vscode/vsce package          # creates claudown-bridge-0.2.0.vsix
code --install-extension claudown-bridge-0.2.0.vsix
```

`vsce` may warn that the extension has no icon or that its repository link points to the parent repo. Both warnings are harmless.

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `claudown.pythonPath` | `python` (Windows) / `python3` | Python used to run the sensor |
| `claudown.sensorScript` | `~/.claude/claudown/vscode_transcript_sensor.py` | Where the installer put the sensor |
| `claudown.intervalSeconds` | `60` | How often to read transcripts |
| `claudown.threshold` | `95` | Only colours the status bar. The real threshold is in your Claude Code settings. |
