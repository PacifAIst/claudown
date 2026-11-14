# claudown

[![PyPI](https://img.shields.io/pypi/v/claudown)](https://pypi.org/project/claudown/) [![Python](https://img.shields.io/pypi/pyversions/claudown)](https://pypi.org/project/claudown/) [![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/PacifAIst/claudown/blob/main/LICENSE) [![Download](https://img.shields.io/badge/download-claudown.zip-brightgreen)](https://github.com/PacifAIst/claudown/releases/latest/download/claudown.zip)

**Leave Claude Code working and go to sleep.** claudown watches your **5-hour and weekly** usage limits without spending a single token. When either one gets close, it lets Claude **wrap up and save its work**, then stops Claude from spending more **and shuts down your computer.** In **sleep mode** it also shuts down as soon as Claude **finishes the job**, even if no limit was reached. On Claude Code on the web, where a shutdown can't reach your laptop, it sends a webhook to a listener on your laptop instead.

![Tutorial](https://raw.githubusercontent.com/PacifAIst/claudown/main/tutorial.jpg "Tutorial")

> **New to this?** Jump to the **[Beginner quick start](#beginner-quick-start)** below: three short recipes, no settings to change. For more detail, read **[GETTING_STARTED.md](https://github.com/PacifAIst/claudown/blob/main/GETTING_STARTED.md)**.

> [!CAUTION]
> **This tool can turn off your computer without warning.** When it's armed and the threshold is reached, it runs `shutdown /s /t 0` (Windows), `sudo shutdown -h now` (macOS) or `sudo systemctl poweroff` (Linux). **Unsaved work in every application is lost.** claudown installs in **DRY RUN** mode and only logs what it would do until you set `DRY_RUN=false` yourself.

**Core principle: never spend tokens to detect a token limit.** claudown senses usage only from local data: the JSON Claude Code already pipes to its status line, local transcript files and small state files. It acts only through local hooks. It never imports the Anthropic SDK and never calls the Anthropic API. The single exception is the web surface: a cloud VM can't power off your laptop, so it sends one webhook to a URL **you** configure.

- **Two limits:** the rolling **5-hour** window and the **weekly** (7-day) limit, each with its own threshold (95 % by default). Hitting the weekly limit at, say, 43 % of the 5-hour window still triggers the shutdown.
- **Nothing cut mid-step:** at the threshold Claude gets a few tool calls to save its work, and the computer goes off when it ends its turn (or after 10 minutes at the latest).
- **Sleep mode:** run `claudown --sleep` before bed, and the computer powers off once Claude finishes its current task.
- **Standard library only:** Python 3.8+, no dependencies.
- **Three surfaces:** the Claude Code CLI, the VS Code extension, and Claude Code on the web.
- **Fires once per window:** an atomic lock means the action runs once per window, however many hooks fire. It keeps blocking tool calls until the limit resets.

> [!NOTE]
> **claudown and Claude's "auto-recharge" setting do different jobs. Use both.** Turning off auto-recharge (extra usage) in your Claude account settings makes sure you're **never billed** beyond your plan. But when the limit hits, your computer stays on and Claude's work just stops wherever it was. claudown adds the rest: it **wraps up the work and powers the machine off**. It doesn't change any account or billing settings.

> [!IMPORTANT]
> **Model-specific limits (for example a Fable-only limit) are not supported yet.** Claude Code only passes the 5-hour and weekly percentages to local tools (plus a spend limit behind a company gateway). There's no per-model figure to read without spending tokens. claudown will add it if a future Claude Code version exposes one locally. Until then, the **5-hour and weekly limits are the ones covered**.

---

## Beginner quick start

Pick the recipe that matches how you use Claude. Each one keeps the default settings: it acts at **95 %** of your 5-hour **or** weekly allowance, lets Claude wrap up first, and starts in **practice mode**, where it only writes down what it would do and never turns anything off.

### You need, once

1. **Python.**
   - **Windows:** install it from [python.org/downloads](https://www.python.org/downloads/) and **tick "Add python.exe to PATH"** on the first screen.
   - **Mac and Linux:** it's already installed.
2. **claudown.** **[⬇ Download claudown.zip](https://github.com/PacifAIst/claudown/releases/latest/download/claudown.zip)** (latest release) and unzip it, for example into *Documents*. On Windows, right-click the file and choose **Extract All…**. You get a folder named **`claudown`**. Use the `claudown` folder that contains `README.md` and a `scripts` folder (Windows sometimes puts one `claudown` inside another).
3. **A terminal opened in that folder.** A terminal is a window where you paste a line and press **Enter**.
   - **Windows:** open the `claudown` folder, click the address bar at the top, type `cmd` and press **Enter**.
   - **Mac:** open *Terminal*, type `cd ` (with a space after it), drag the folder into the window, and press **Enter**.
   - **VS Code:** use **File → Open Folder…**, then **Terminal → New Terminal**.

On **Mac and Linux**, type `python3` wherever these recipes say `python`.

> **Comfortable with pip?** For recipes 1 and 2 you can skip the download: run `pip install claudown`, then use `python -m claudown.claudown_setup` wherever a recipe says `python scripts/claudown_setup.py`. Recipe 3 uses the downloaded folder, so start with the ZIP for that one.

### Recipe 1: Claude Code in a terminal

| Step | Do this |
|---|---|
| 1. Install | Paste `python scripts/claudown_setup.py` and press Enter. |
| 2. Restart | Close Claude Code and open it again. The bottom line now shows **`claudown ▸ 5h …% · 7d …%`**. |
| 3. Practise | Use Claude as normal. Check what claudown *would* do with `python scripts/shutdown_orchestrator.py --test`. |
| 4. Switch it on | Save your work, then paste `python scripts/claudown_setup.py --arm`. From now on, at 95 % of either limit, Claude wraps up and then the computer **really turns off**. |

### Recipe 2: Claude Code in VS Code

| Step | Do this |
|---|---|
| 1. Install | Same as recipe 1: `python scripts/claudown_setup.py`. |
| 2. One tick | In VS Code, open **Settings** (Ctrl+, or Cmd+,), search for **Claude Code: Use Terminal** and **tick it**. The VS Code chat panel can't show usage numbers; this setting fixes that. |
| 3. Restart | Close and reopen VS Code. Claude Code now shows **`claudown ▸ 5h …% · 7d …%`** at the bottom. |
| 4. Switch it on | When you're happy: `python scripts/claudown_setup.py --arm`. |

If you'd rather keep the chat panel, skip step 2. claudown still stops Claude when you actually hit the limit, but the weekly percentage is only available with step 2. See [GETTING_STARTED.md, part 2A](https://github.com/PacifAIst/claudown/blob/main/GETTING_STARTED.md#2a-install-claudown-one-line) for how to make it act earlier.

### Recipe 3: Claude Code on the web (in your browser)

A website can't turn off your laptop by itself, so a small helper on your laptop waits for a message from the web.

| Step | Do this |
|---|---|
| 1. Add it to your project | `python scripts/claudown_setup.py --project "PATH-TO-YOUR-PROJECT"`, then save and upload (commit and push) the project as usual. |
| 2. Choose a password | Make up one of 16 or more letters and numbers, for example `blue-river-42-lamp-sky`. |
| 3. Start the helper on your laptop | `python scripts/local_webhook_listener.py --token "YOUR-PASSWORD"`. Leave the window open. |
| 4. Give it a web address | Install [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/), then in a **second** window run `cloudflared tunnel --url http://localhost:8383`. Copy the `https://….trycloudflare.com` address it prints. |
| 5. Tell the web where to send the message | In your Claude Code on the web **environment settings**, add `WEBHOOK_URL` = that address and `WEBHOOK_TOKEN` = your password, and allow `*.trycloudflare.com` in network access. [Picture of where to paste them](https://github.com/PacifAIst/claudown/blob/main/GETTING_STARTED.md#2c-claude-code-on-the-web-in-your-browser). |
| 6. Switch it on | Web: run `python scripts/claudown_setup.py --project "PATH-TO-YOUR-PROJECT" --arm`, then commit and push again. Laptop: stop the helper (Ctrl+C) and start it again with `--arm` at the end of the line from step 3. |

### Going to bed? Sleep mode (works with recipes 1 and 2)

| Step | Do this |
|---|---|
| 1. Give Claude its task | Ask Claude for the long job as usual and let it start. |
| 2. Tell claudown you're off to bed | In another terminal window, in the claudown folder, run `python scripts/shutdown_orchestrator.py --sleep`. |
| 3. Sleep | When Claude finishes the task, the computer turns off. If a limit comes first, Claude wraps up and then the computer turns off. Either way, it happens only once. |

Changed your mind? `python scripts/shutdown_orchestrator.py --wake` cancels it. Sleep mode switches itself off after 12 hours.

**Tip:** Claude can't continue while it's waiting for you to approve something. Before you leave, choose a permission mode that doesn't keep asking (for example, accept edits), so Claude doesn't sit waiting all night.

### Three things worth knowing

- **Emergency stop:** create an empty file named `claudown.disabled` in the `.claude` folder inside your user folder. Delete it to turn claudown back on.
- **Uninstall:** `python scripts/claudown_setup.py --uninstall` puts your settings back.
- **Mac/Linux shutdown asks for a password?** See [part 4 of the guide](https://github.com/PacifAIst/claudown/blob/main/GETTING_STARTED.md#4-safety-warnings-please-read). It's a one-time fix. Even without it, claudown still stops Claude at the limit.

Everything below this point is the technical reference.

---

## Which mechanism each surface supports

| Surface | Sensor (zero tokens) | Gate | Action | Backstop |
|---|---|---|---|---|
| **CLI** (primary, full support) | `statusLine` → `statusline_sensor.py` (exact %) | `PreToolUse` hook | local shutdown | `StopFailure` / `rate_limit` |
| **VS Code extension** | `statusLine` is **not run** by the panel → `vscode_transcript_sensor.py` reads local transcripts | same `PreToolUse` hook (hooks *do* run) | local shutdown | same |
| **Claude Code on the web** | statusLine/transcripts inside the cloud VM, polled by `web_limit_watcher.py` | same hook, inside the VM | **webhook POST** → `local_webhook_listener.py` on your laptop → local shutdown | same, inside the VM |

```
 CLI ──statusLine JSON──▶ statusline_sensor.py ──writes──▶ ~/.claude/claudown_state.json
                                                                  │
 VS Code panel (no statusLine) ──▶ vscode_transcript_sensor.py ◀──┤ (gate falls back automatically
                                    reads ~/.claude/projects/*.jsonl   when the sensor is silent)
                                                                  ▼
 Any surface ──PreToolUse / UserPromptSubmit──▶ pretooluse_gate.py ── 5h ≥ threshold OR weekly ≥ threshold?
                                                                            │ yes
                                         WRAP-UP: block once, tell Claude to save its work (N grace tool calls)
                                                                            │
 Any surface ──Stop (Claude ended its turn)──▶ shutdown_orchestrator.py ────┤◀── or the wrap-up deadline
             (also: sleep mode, task finished)                              ▼
                                                     shutdown_orchestrator.trigger() (once per window)
                                                        ├─ local machine: shutdown command
                                                        └─ cloud VM:      webhook ──▶ local_webhook_listener.py ──▶ shutdown
 Any surface ──StopFailure (matcher "rate_limit")──▶ shutdown_orchestrator.py   BACKSTOP (after the fact, immediate)
```

| File | Runs as | What it does |
|---|---|---|
| [`scripts/statusline_sensor.py`](https://github.com/PacifAIst/claudown/blob/main/scripts/statusline_sensor.py) (+ [`.sh`](https://github.com/PacifAIst/claudown/blob/main/scripts/statusline_sensor.sh) wrapper) | `statusLine` command | Copies `rate_limits.five_hour` and `rate_limits.seven_day` (`used_percentage`, `resets_at`) into `~/.claude/claudown_state.json`. Prints `claudown ▸ 5h 42% · 7d 63% / gate 95% · resets 15:30 · DRY RUN`. |
| [`scripts/pretooluse_gate.py`](https://github.com/PacifAIst/claudown/blob/main/scripts/pretooluse_gate.py) | `PreToolUse` + `UserPromptSubmit` hook | Checks both limits. At a threshold it starts the wrap-up (block once, then a few grace calls). After the action has fired it keeps blocking (exit code 2). |
| [`scripts/shutdown_orchestrator.py`](https://github.com/PacifAIst/claudown/blob/main/scripts/shutdown_orchestrator.py) | library + `Stop` + `StopFailure` hooks, and the `claudown` command | Cross-platform shutdown or webhook, once per window, respects `DRY_RUN`. **Stop:** finishes a wrap-up, or acts in sleep mode. **StopFailure:** backstop, fires at once. CLI: `--status`, `--sleep`, `--wake`, `--test`, `--reset`. |
| [`scripts/vscode_transcript_sensor.py`](https://github.com/PacifAIst/claudown/blob/main/scripts/vscode_transcript_sensor.py) | called by the gate; `--watch` timer | Estimates usage from local `.jsonl` transcripts. If it can't, it logs a clear warning and reports *unknown*. It never guesses. |
| [`scripts/web_limit_watcher.py`](https://github.com/PacifAIst/claudown/blob/main/scripts/web_limit_watcher.py) | `SessionStart` hook in a web session | Background poller inside the cloud VM. At the threshold it POSTs `session_id`, `timestamp` and `usage_pct` to `WEBHOOK_URL`. It never shuts down. |
| [`scripts/local_webhook_listener.py`](https://github.com/PacifAIst/claudown/blob/main/scripts/local_webhook_listener.py) | you run it on your laptop | Receives that webhook (shared-secret token required) and runs the local shutdown. |
| [`scripts/cli_computer_use_shutdown.py`](https://github.com/PacifAIst/claudown/blob/main/scripts/cli_computer_use_shutdown.py) | optional, you run it | Checks whether the CLI's built-in computer-use server can be used on this Mac and, if so, lets you opt in. See below. |
| [`scripts/claudown_setup.py`](https://github.com/PacifAIst/claudown/blob/main/scripts/claudown_setup.py) / [`setup.sh`](https://github.com/PacifAIst/claudown/blob/main/setup.sh) | installer | Copies scripts to `~/.claude/claudown/`, merges `settings.json` (with a backup), and keeps your existing status line. |
| [`vscode_bridge_extension/`](https://github.com/PacifAIst/claudown/blob/main/vscode_bridge_extension/) | optional VS Code extension | Status bar reading plus a one-click switch to terminal mode. |

The status line runs locally and costs no API tokens. Per the [Claude Code docs](https://code.claude.com/docs/en/statusline), `rate_limits` is present only for **claude.ai Pro, Max and Ultra subscribers**, and only after the first API response in a session.

---

## Limits, wrap-up and sleep mode

**Which limits are watched**

| Limit | Setting | Source (zero tokens) | Notes |
|---|---|---|---|
| 5-hour window | `SHUTDOWN_THRESHOLD` (95) | status line, or transcripts when the status line is silent | Exact in the CLI, estimated in the VS Code panel. |
| Weekly (7-day) | `WEEKLY_THRESHOLD` (95, or `off`) | status line only | Needs the status line: the CLI, or VS Code with **Use Terminal**. A stale weekly reading still counts, because weekly usage only grows within a window. Once it fires, the lock lasts until the **weekly** reset. |
| Per-model (e.g. Fable) | none | **not available** | Claude Code doesn't pass a per-model figure to local tools. Support will be added if a future version does. |

**Wrap-up: nothing is cut mid-step.** When a threshold is reached, the gate blocks one tool call and tells Claude (through the hook's exit-2 message) to save its work: it may use up to `WRAP_UP_TOOL_CALLS` (5) more tool calls, for example to commit or write a progress note, and should then end its turn with a summary. The `Stop` hook fires when Claude ends its turn, and that runs the action. A detached timer runs the action after `WRAP_UP_MAX_SECONDS` (600) anyway, in case Claude never stops. The wrap-up is skipped (immediate action) when there's no headroom left: the limit is at 100 %, a "limit reached" message appears in the transcripts, or `StopFailure`/`rate_limit` fires. `WRAP_UP=false` restores the immediate behaviour. The 5 % margin below the limit is the token budget the wrap-up uses.

**Sleep mode: shut down when the job is done.** `claudown --sleep` (or `python scripts/shutdown_orchestrator.py --sleep [HOURS]`) creates `~/.claude/claudown.sleep`. The next time Claude ends its turn, the `Stop` hook runs the action. The flag is one-shot: any firing clears it, so a rebooted machine never shuts down again by itself. It also expires after `SLEEP_HOURS` (12). `--wake` cancels it. Creating an empty `claudown.sleep` file by hand works too. Claude must be able to keep going unattended: permission prompts pause it, so choose a permission mode that doesn't ask.

---

## Surface 1: Claude Code CLI (primary)

```bash
git clone https://github.com/PacifAIst/claudown.git
cd claudown
python3 scripts/claudown_setup.py      # or ./setup.sh   (Windows: python scripts\claudown_setup.py)
```

That installs to `~/.claude/claudown/`, merges `~/.claude/settings.json` (backed up to `settings.json.bak.<timestamp>`), and stays in **DRY RUN**. Start a **new** Claude Code session; the `claudown ▸ 5h …%` status line should appear. Then:

```bash
python3 ~/.claude/claudown/shutdown_orchestrator.py --status   # what claudown sees right now
python3 ~/.claude/claudown/shutdown_orchestrator.py --test     # prints the exact shutdown command
tail -f ~/.claude/claudown.log
python3 scripts/claudown_setup.py --arm [--threshold 90]       # arm it (DRY_RUN=false)
python3 scripts/claudown_setup.py --uninstall                  # remove it
```

The installer writes hook commands with the absolute path of the Python that ran it, using forward slashes (and 8.3 short paths if there are spaces), so they work whether Claude Code runs hooks through Git Bash or PowerShell on Windows. To configure by hand instead, start from [`settings/settings.json.example`](https://github.com/PacifAIst/claudown/blob/main/settings/settings.json.example).

### Shutdown permissions (macOS / Linux)

Hooks have no terminal, so `sudo` can't ask for a password. claudown runs `sudo -n` (non-interactive) and, if that fails, tries a fallback that needs no sudo:

| OS | First try | Fallback |
|---|---|---|
| Windows | `shutdown /s /t 0` | none needed |
| macOS | `sudo -n shutdown -h now` | `osascript -e 'tell application "System Events" to shut down'` (may show an Automation prompt the first time) |
| Linux | `sudo -n systemctl poweroff` | `systemctl poweroff` (works without sudo for the active desktop user on most polkit setups) |

To allow the canonical command without a password, add a **narrow** sudoers rule with `sudo visudo -f /etc/sudoers.d/claudown`:

```
yourname ALL=(root) NOPASSWD: /sbin/shutdown -h now          # macOS
yourname ALL=(root) NOPASSWD: /usr/bin/systemctl poweroff    # Linux
```

If every command fails, claudown logs `all shutdown commands failed` and exits cleanly. **The gate still blocks tool calls**, so your tokens are protected even if the machine stays on. `SHUTDOWN_COMMAND` replaces the built-in commands, for example `systemctl suspend`, `pmset sleepnow`, or `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`.

### Optional: computer-use shutdown (macOS only)

The Claude Code CLI includes a built-in `computer-use` MCP server ([docs](https://code.claude.com/docs/en/computer-use)). Its constraints:

- **macOS only.** It isn't available in the CLI on Linux or Windows.
- **claude.ai Pro, Max or Ultra plan only.** It isn't available on Team or Enterprise plans, with an API key, or through Bedrock or Vertex.
- You **enable it yourself in an interactive session with `/mcp`**. It requires Claude Code v2.1.85+ and doesn't work with `claude -p`.

Because a script can't enable or drive it, `cli_computer_use_shutdown.py` doesn't start Claude. `--check` reports eligibility (macOS, `claude --version`, and whether the sensor has ever received subscriber rate-limit data). `--enable` opts you in only if the check passes. After that, when the armed gate blocks, its message also asks Claude to shut the Mac down with the computer-use tool. That costs a few tokens, so it's off by default. **It's never the primary path:** the shutdown command always runs first, and if computer-use isn't in `/mcp`, nothing changes.

### Backstop

The `StopFailure` hook with `matcher: "rate_limit"` fires **after** the limit is hit. It's a last-resort safety net. Primary detection is predictive: the sensor plus the gate.

---

## Surface 2: VS Code extension

The native VS Code panel **doesn't run `statusLine`**, so a solution that relies on it fails silently there. Hooks do run (`~/.claude/settings.json` is shared between the CLI and the extension), so the **same gate protects you in VS Code**. Only the sensor changes:

1. **Automatic transcript sensor.** If the state file hasn't been updated for `SENSOR_STALE_SECONDS` (900 s), the gate calls `vscode_transcript_sensor.py`. It reads `~/.claude/projects/**/*.jsonl` and:
   - rebuilds the current 5-hour block,
   - reports **100 %** if a "usage limit reached" error appears in that block,
   - otherwise estimates `weighted tokens / TOKEN_BUDGET_5H`.
2. **Calibrate once.** Use Claude Code in a terminal until the status line shows at least 5 %, then run:
   ```bash
   python3 ~/.claude/claudown/vscode_transcript_sensor.py --calibrate --write
   ```
3. **No data, no guessing.** Without a budget, the sensor logs `WARNING … Not guessing` (at most once an hour), and the gate fails open. It will still catch a limit that was actually hit.
4. **Exact sensor in VS Code:** enable Claude Code's **Use Terminal** setting (`claudeCode.useTerminal`). Terminal mode runs `statusLine`.
5. **Optional bridge:** [`vscode_bridge_extension/`](https://github.com/PacifAIst/claudown/blob/main/vscode_bridge_extension/) is a small community-workaround extension. It runs the transcript sensor on a timer, shows the reading in VS Code's status bar, and has a one-click switch to terminal mode. It's optional and isn't the default path.

> [!NOTE]
> The transcript number is an **approximation**. Anthropic doesn't publish how subscription usage is weighted. claudown counts input, output and cache-creation tokens fully, and cache reads at `CACHE_READ_WEIGHT` (0.1). Leave a margin, for example a 90 % threshold.

---

## Surface 3: Claude Code on the web

Web sessions run in a cloud VM. **A shutdown inside the VM would only stop the VM, not your laptop.** That's also true for Computer Use in the cloud: Claude might *see* the limit on screen, but it **can't power off your local machine**. Don't expect it to.

So on the web claudown detects the limit inside the VM, at zero tokens, and sends **one HTTP POST** to a webhook you control:

1. Install into the repository you work on:
   ```bash
   python3 scripts/claudown_setup.py --project /path/to/your-repo
   cd /path/to/your-repo && git add .claude && git commit -m "Add claudown" && git push
   ```
   This adds a `SessionStart` hook that starts `web_limit_watcher.py`, plus the same gate and backstop (paths use `$CLAUDE_PROJECT_DIR`, `ACTION=notify`). See [`settings/settings.web.json.example`](https://github.com/PacifAIst/claudown/blob/main/settings/settings.web.json.example).
2. On your **laptop**, run the listener and expose it through a tunnel you control:
   ```bash
   python3 scripts/local_webhook_listener.py --token "<16+ random characters>"   # 127.0.0.1:8383
   cloudflared tunnel --url http://localhost:8383        # or Tailscale Funnel, etc.
   ```
3. In the **cloud environment's settings** (not in the repo), set `WEBHOOK_URL` to the tunnel's https URL and `WEBHOOK_TOKEN` to the same secret. Also allow that domain in the environment's network access settings.

Payload (JSON): `session_id`, `timestamp` (ISO 8601 UTC), `limit` (`5-hour`, `weekly`, …), `usage_pct`, `threshold`, `weekly_threshold`, `reason`, `source`, `resets_at`, `host`. The token travels only in the `X-Claudown-Token` / `Authorization: Bearer` headers, never in the body. The listener binds to `127.0.0.1`, uses a constant-time token comparison, accepts bodies up to 16 KB, and respects **the laptop's own** `DRY_RUN`. Add `--arm` to the listener command to make it really shut down.

---

## Configuration

Set values in the `"env"` block of `settings.json` or in `~/.claude/claudown/config.json`. Precedence: environment, then `config.json`, then defaults.

| Variable | Default | Meaning |
|---|---|---|
| `SHUTDOWN_THRESHOLD` | `95` | Percent of the 5-hour window at which the gate acts. |
| `WEEKLY_THRESHOLD` | `95` | Percent of the weekly (7-day) limit at which the gate acts. `off` disables it. |
| `WRAP_UP` | `true` | Let Claude save its work and finish its turn before the action. |
| `WRAP_UP_TOOL_CALLS` | `5` | Tool calls Claude may still make while wrapping up. |
| `WRAP_UP_MAX_SECONDS` | `600` | Act at the latest this long after the wrap-up starts. |
| `SLEEP_HOURS` | `12` | `--sleep` expires after this many hours. |
| `DRY_RUN` | `true` | Logs instead of executing. **Armed only when it's `false`.** |
| `ACTION` | `auto` | `auto` (shutdown locally, notify on the web), `shutdown`, `notify`, `both`, `none` (block only). |
| `BLOCK_TOOLS` | `true` | Block tool calls and prompts at the threshold. |
| `BACKSTOP_ENABLED` | `true` | Act on `StopFailure` / `rate_limit`. |
| `SHUTDOWN_DELAY_SECONDS` | `0` | Grace period. A desktop notification is shown first. |
| `SHUTDOWN_COMMAND` | *(empty)* | Replaces the built-in OS commands. |
| `WEBHOOK_URL` | *(empty)* | Where the web watcher POSTs. |
| `WEBHOOK_TOKEN` | *(empty)* | Shared secret, sent as a header and checked by the listener. |
| `WEBHOOK_FORMAT` | `json` | `json`, or `text` (ntfy-style endpoints). |
| `WEB_POLL_SECONDS` | `30` | Web watcher polling interval. |
| `SENSOR_STALE_SECONDS` | `900` | Status line data older than this switches the gate to the transcript sensor. |
| `TOKEN_BUDGET_5H` | *(empty)* | Transcript sensor: weighted tokens that count as 100 %. Set it with `--calibrate --write`. |
| `CACHE_READ_WEIGHT` | `0.1` | Transcript sensor: weight of cache-read tokens. |
| `STATUSLINE_CHAIN_COMMAND` | *(empty)* | Your previous status line, shown above claudown's. |
| `COMPUTER_USE_SHUTDOWN` | `false` | Optional macOS computer-use request (see above). |

**Emergency off switch:** create the file `~/.claude/claudown.disabled` to turn off the gate and backstop immediately. Delete it to turn them back on.

**Files:** `~/.claude/claudown_state.json` (readings), `~/.claude/claudown_trigger.json` (once-per-window lock), `~/.claude/claudown_wrapup.json` (wrap-up in progress), `~/.claude/claudown.sleep` (sleep mode on), `~/.claude/claudown.log` (everything claudown did). `CLAUDE_CONFIG_DIR` is honoured.

---

## Install from PyPI

claudown is on PyPI: **https://pypi.org/project/claudown/**

```bash
pip install claudown
claudown-setup            # same installer as scripts/claudown_setup.py
claudown --status
```

If your shell says `claudown-setup: command not found` (common on Windows, where pip's Scripts folder often isn't on PATH), run the same commands through Python instead:

```bash
python -m claudown.claudown_setup            # installer (accepts --arm, --threshold, --uninstall, ...)
python -m claudown.shutdown_orchestrator --status
```

Release notes and a ready-to-unzip `claudown.zip` are on the [Releases page](https://github.com/PacifAIst/claudown/releases). Maintainers: see [PUBLISHING.md](https://github.com/PacifAIst/claudown/blob/main/PUBLISHING.md).

Console commands: `claudown` (orchestrator), `claudown-gate`, `claudown-setup`, `claudown-sensor`, `claudown-vscode-sensor`, `claudown-web-watcher`, `claudown-listener`.

---

## Safety design

- **Dry run by default.** Any `DRY_RUN` value other than an explicit false value (`false`, `0`, `no`, `off`) is a dry run.
- **Once per window.** The lock is created with `O_CREAT | O_EXCL`, so concurrent hooks can't double-fire. It expires at the window's `resets_at`. `--reset` clears it.
- **Ignores old readings.** A reading whose `resets_at` has passed counts as 0 %.
- **Fails open on unknowns, fails safe on errors.** A crash in the gate allows the call; a crash in the sensor still prints a status line; a failed shutdown is logged and the script exits 0.
- **Network is isolated.** The only network code is a lazy `urllib.request` import inside the webhook sender.

## Testing

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
```

[`tests/test_dry_run_no_api_calls.py`](https://github.com/PacifAIst/claudown/blob/main/tests/test_dry_run_no_api_calls.py) runs every script as a real subprocess with an isolated `CLAUDE_CONFIG_DIR`. A `sitecustomize.py` makes **any socket connection fail the suite**. The tests cover:

- the zero-network/zero-SDK import rules,
- gate thresholds, idempotency and fail-open behaviour,
- the weekly limit (fires at 43 % of the 5-hour window, blocks until the weekly reset, stale and expired readings, `off`),
- wrap-up (grace calls, `Stop` finishes it, deadline timer, skipped when exhausted, backstop overrides),
- sleep mode (fires on `Stop`, one-shot, `--wake`, expiry, plain flag file),
- the backstop,
- armed mode, using a harmless override command, plus graceful failure,
- the web watcher only notifying and never shutting down,
- the webhook payload and listener token checks,
- computer-use gating off macOS,
- transcript estimation, calibration and the no-guess warning,
- the installer's merge, chaining, idempotency, uninstall and project mode,
- package imports and the `pyproject.toml` entry points.

## Troubleshooting

See [GETTING_STARTED.md → Troubleshooting](https://github.com/PacifAIst/claudown/blob/main/GETTING_STARTED.md#5-troubleshooting) for the plain-language version.

| Symptom | Fix |
|---|---|
| No `claudown ▸` status line in the CLI | Start a new session. Run `claude --debug`. Re-run the installer with the Python you want to use. |
| `waiting for data` | `rate_limits` appears only for Pro/Max/Ultra, after the first response. API-key users have no 5-hour data, so use `TOKEN_BUDGET_5H` or rely on the backstop. |
| VS Code: gate never fires | That's expected without a budget. Calibrate, enable **Use Terminal**, or install the bridge. `--status` shows `unknown:no-budget`. |
| `DRY_RUN: would execute` but nothing happened | That's correct. Arm it with `--arm`. |
| `all shutdown commands failed` | Add the sudoers rule, or set `SHUTDOWN_COMMAND`. |
| Blocked but want to keep working | Create `~/.claude/claudown.disabled`. |
| Fired once and never again | That's intended (once per window). `shutdown_orchestrator.py --reset` clears it. |
| `computer-use` missing from `/mcp` | You need macOS, a Pro/Max/Ultra plan, a claude.ai login and v2.1.85+. claudown keeps using the hook path. |
| Sleep mode on, but the computer didn't turn off | Claude was probably waiting for your approval (that pauses it without ending the turn). Use a permission mode that doesn't ask. Check `claudown --status` → `sleep_mode`. |
| Weekly % missing (`7d` not shown) | The weekly figure only comes from the status line. Use the CLI, or VS Code with **Use Terminal**. API-key accounts have no weekly data. |
| Want a Fable-only limit | Not possible yet: Claude Code doesn't expose per-model usage locally. See the note at the top. |
| Web webhook never arrives | Check `WEBHOOK_URL`, the environment's network allow list, the tunnel, and the token. `DRY_RUN=true` only logs. |

## License

[Apache License 2.0](https://github.com/PacifAIst/claudown/blob/main/LICENSE). Part of the PacifAIst open-source tools.

claudown is an independent project and isn't affiliated with or endorsed by Anthropic. "Claude" and "Claude Code" are trademarks of Anthropic.

---

<p align="center">Made with ❤️ for the Local AI Community by PacifAIst</p>
