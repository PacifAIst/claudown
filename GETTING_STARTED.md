# Getting started with claudown

> **Just want it working?** The [Beginner quick start](README.md#beginner-quick-start) has three short recipes (terminal, VS Code, web) that use the default settings. This guide explains the same steps in more detail.

This guide assumes you've never used a terminal. Every unfamiliar word is explained the first time it appears. Read it top to bottom once; after that you'll only need the parts for the way you use Claude.

> ⚠️ **Read part 4 (Safety) before you switch claudown on for real.** claudown can turn your computer off.

---

## 1. What is the 5-hour limit?

When you use **Claude Code** (Claude's coding assistant) on a Pro, Max or Ultra plan, your usage is counted in a **rolling 5-hour window**.

Think of it like a **phone plan's data allowance**, except that the "month" is only five hours long:

- The window **starts with your first message**.
- Everything you do in the next five hours counts toward the same allowance.
- About **five hours later the window resets** and you start from zero again.

Usage is counted in **tokens**. A token is a small piece of text, **roughly ¾ of a word**. You don't need to count them; Claude Code keeps track for you and shows the result as a **percentage** of your allowance.

**What claudown does:** it watches that percentage. When it reaches the limit you choose (95 % unless you change it), claudown:

1. **stops Claude from doing anything else**, so it can't burn through what's left, and
2. **turns off your computer**, so you don't come back to a session that stopped halfway through.

claudown **never spends any of your allowance to do this**. It only reads files that are already on your computer.

---

## Before you start: three things you need

1. **Claude Code** already installed and working.
2. **Python**, a free program that runs claudown's small scripts.
   - **Windows:** download it from [python.org/downloads](https://www.python.org/downloads/). On the first installer screen, **tick "Add python.exe to PATH"**, then click *Install Now*.
   - **Mac:** it's usually already there. If a window later asks you to install "command line developer tools", click *Install*.
   - **Linux:** it's already there.
3. **The claudown files.** Click **[Download claudown.zip](https://github.com/PacifAIst/claudown/releases/latest/download/claudown.zip)** and unzip it somewhere easy to find, such as your *Documents* folder. On Windows, right-click the file and choose **Extract All…**. The folder is called **`claudown`**. Use the one that contains `README.md` and a `scripts` folder; Windows sometimes puts one `claudown` inside another.

### What's a "terminal"?

A **terminal** is a window where you type a command and press **Enter** instead of clicking buttons. You'll only need it for a few copy-and-paste steps. The easiest way to open one is inside **VS Code** (the code editor):

1. In VS Code, choose **File → Open Folder…** and pick the unzipped `claudown` folder.
2. Choose **Terminal → New Terminal** from the top menu. A panel opens at the bottom of the window. That's the terminal, already "standing" inside the claudown folder.

When this guide shows a grey box like the one below, copy the line, paste it into the terminal, and press **Enter**.

```
python --version
```

If you see something like `Python 3.12.4`, you're ready. On Mac or Linux, type `python3` instead of `python` everywhere in this guide.

---

## 2. The easiest setup (VS Code users)

### 2A. Install claudown (one line)

In the VS Code terminal, run:

```
python scripts/claudown_setup.py
```

That one line:

- copies claudown's scripts into Claude's settings folder (`.claude/claudown` inside your user folder),
- adds claudown to Claude Code's settings file. It saves a backup copy first, and keeps anything you already had there.
- starts claudown in **practice mode** (called **DRY RUN**): it writes down what it *would* do but never turns anything off.

Close Claude Code and open it again so it notices the change.

**What happens inside VS Code:** the Claude Code panel in VS Code checks with claudown before every action. That check is what Claude Code calls a **hook**: a small helper that runs automatically at a certain moment. If you're over your limit, claudown says "stop", and Claude stops.

One catch: the VS Code panel doesn't show Claude Code's **status line** (a one-line summary at the bottom of the terminal version, and the place where the exact percentage comes from). So in the panel, claudown reads Claude's own history files to work out your usage. To make that accurate, do this **once**:

1. Open a terminal, type `claude`, and press Enter. That starts Claude Code in the terminal, where the status line *does* work. Use it normally until the bottom line shows `claudown ▸ 5h` with at least **5%**.
2. Then run:
   ```
   python scripts/vscode_transcript_sensor.py --calibrate --write
   ```
   This teaches claudown what "100%" looks like for your plan.

Until you've done that, claudown **doesn't guess**. It writes a warning in its log file and lets Claude keep working. It will still react if you actually hit the limit.

> 💡 **Even simpler:** in VS Code, open **Settings**, search for **Claude Code: Use Terminal**, and tick it. Claude Code then opens in terminal style inside VS Code, the status line works, and you don't need to calibrate anything.

### 2B. See and change claudown's settings without editing text files (optional)

Claude Code's settings live in a text file. If you'd rather click than type:

- **Built into Claude Code (newest versions):** in the Claude Code panel, open the command menu and choose **Hooks**. You'll see claudown's entries listed under *PreToolUse*, *UserPromptSubmit* and *StopFailure*. You can check or remove them there.
- **"Claude Code Config Manager" extension** (free, by agnislav, from the VS Code Extensions view): open the Command Palette (**Ctrl+Shift+P**, or **Cmd+Shift+P** on a Mac), choose **Claude Config: Add Hook**, and enter:

  | Field | What to enter |
  |---|---|
  | Event | `PreToolUse` |
  | Matcher | `*` (means "every action") |
  | Command | the `pretooluse_gate.py` line the installer printed, or `python "<your claudown folder>/scripts/pretooluse_gate.py"` (use forward slashes `/`, even on Windows) |

  You only need this if you skipped the installer. The installer already adds everything.

- **"Claude Statusline" extension** (free, by Brainmetrix): shows your usage in VS Code's bottom bar. According to its store page, it writes its own status line script into Claude's settings. **Install it *before* you run claudown's installer**: claudown then keeps it and shows its line above claudown's. If you install it afterwards, run `python scripts/claudown_setup.py` again. Like claudown's own sensor, its numbers come from the status line, so they update when Claude runs in terminal style.

### 2C. Claude Code on the web (in your browser)

When you use Claude Code **in a web browser**, Claude runs on a computer in the cloud, not on yours. **Nothing running there can turn off your laptop.** That includes Claude's "computer use" feature: it can look at the cloud screen, but it can't reach your machine.

So claudown works in two halves:

- **In the cloud:** a small watcher notices when you're near the limit and sends a short message (a **webhook**: think of it as a text message between programs) to an address you choose.
- **On your laptop:** a small listener waits for that message and turns the laptop off.

**Step 1: add claudown to your project.** In a terminal, run this, replacing the path with your project's folder:

```
python scripts/claudown_setup.py --project "C:/path/to/your/project"
```

Then save (commit) and upload (push) the new `.claude` folder with the rest of your project, the same way you normally save work to GitHub.

**Step 2: start the listener on your laptop.** Pick a password of at least 16 characters (letters and numbers), then run:

```
python scripts/local_webhook_listener.py --token "PUT-YOUR-LONG-PASSWORD-HERE"
```

Leave that window open. Your laptop needs a public address the cloud can reach, so install the free [Cloudflare Tunnel tool](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) and run this in a **second** terminal:

```
cloudflared tunnel --url http://localhost:8383
```

It prints an address ending in `.trycloudflare.com`. Copy it. (It changes every time you restart the tunnel.)

**Step 3: tell the cloud where to send the message.** Open the settings of your Claude Code on the web **environment**. Add two **environment variables**, which are named settings the cloud computer can read, and allow the tunnel's address in its network settings. The screen looks roughly like this *(illustration; the real page may look different)*:

```
┌─ Environment settings ───────────────────────────────────────────┐
│                                                                  │
│  Network access:  ( ) None   ( ) Trusted   (•) Custom            │
│     Allowed domains:  *.trycloudflare.com                        │
│                                                                  │
│  Environment variables                                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ WEBHOOK_URL=https://your-words-here.trycloudflare.com      │◀── paste the tunnel address
│  │ WEBHOOK_TOKEN=PUT-YOUR-LONG-PASSWORD-HERE                  │◀── the same password as step 2
│  └────────────────────────────────────────────────────────────┘  │
│                                                   [ Save ]       │
└──────────────────────────────────────────────────────────────────┘
```

> 🔒 **Never put the password in your project files.** Anyone who can see your project could use it to turn off your laptop.

**Practice mode applies on both sides.** The cloud only *logs* the message, and your laptop only *logs* the shutdown, until you switch each side on:

- **Cloud side:** run the step 1 line again with `--arm` at the end, then commit and push again.
- **Laptop side:** stop the listener (press **Ctrl+C** in its window) and start it again with `--arm` at the end:
  ```
  python scripts/local_webhook_listener.py --token "PUT-YOUR-LONG-PASSWORD-HERE" --arm
  ```

---

## 3. The manual setup (people who use Claude Code in a terminal)

1. **Copy the settings.** Open [`settings/settings.json.example`](settings/settings.json.example) and copy its contents into Claude's settings file:
   - Windows: `C:\Users\<you>\.claude\settings.json`
   - Mac/Linux: `~/.claude/settings.json` (`~` means your home folder)

   If that file already has content, merge carefully. The installer (`python scripts/claudown_setup.py`) does this merge for you and is the safer choice.
2. **Copy the scripts.** Put everything from the `scripts` folder into `.claude/claudown/` in your home folder.
3. **Edit the paths.** The example uses `python3 ~/.claude/claudown/…`. On Windows, change `python3` to `python`.
4. **Test the sensor** (Mac/Linux/Git Bash):
   ```
   bash scripts/statusline_sensor.sh
   ```
   It feeds in a pretend "42% used" reading, kept in a temporary folder so your real numbers aren't touched. You should see `claudown ▸ 5h 42%`.
5. **Start a new Claude Code session.** The bottom line should now show `claudown ▸ 5h …%`. It says `waiting for data` until Claude has answered once.

---

## 4. Safety warnings: please read

**claudown really turns your computer off.** When it's armed and the limit is reached, it shuts down straight away, the same as choosing *Shut Down* from the menu. **Anything you haven't saved, in any program, is lost.**

**Always practise first.** claudown starts in **DRY RUN** (practice mode). To see exactly what it would do:

```
python scripts/shutdown_orchestrator.py --test
```

Its diary (log file) is `.claude/claudown.log` in your home folder. When you're happy, arm it:

```
python scripts/claudown_setup.py --arm
```

To go back to practice mode, run `python scripts/claudown_setup.py` again without `--arm`. If it's armed and you urgently need Claude to keep going, create an empty file named `claudown.disabled` inside the `.claude` folder in your home folder. claudown stops acting until you delete it.

**Mac and Linux: permission to shut down.** Turning off a Mac or Linux computer normally needs your administrator password (that's what `sudo` means: "do this as administrator"). claudown runs in the background, where nobody can type a password, so:

- claudown first tries a method that doesn't need a password: the normal *Shut Down* on a Mac, or `systemctl poweroff` on most Linux desktops. On a Mac, the first time, a box may ask you to allow "System Events". Click **OK**.
- If that doesn't work, you can give permission for **this one command only**. In a terminal, run `sudo visudo -f /etc/sudoers.d/claudown`, type your password, and add the single line below, replacing `yourname` with your login name. Then save (in the default editor: press `Esc`, type `:wq`, press Enter).
  ```
  yourname ALL=(root) NOPASSWD: /sbin/shutdown -h now
  ```
  On Linux, use `/usr/bin/systemctl poweroff` instead of `/sbin/shutdown -h now`. This allows **only** the shutdown command without a password. Nothing else changes.
- Alternatively, you can start Claude Code from a terminal that already has administrator rights. That's less safe, so the rule above is the better choice.

**Windows** needs no extra permission.

Even when the shutdown can't run, **claudown still stops Claude** at the limit, so your allowance is protected either way.

---

## 5. Troubleshooting

| What you see | What it means / what to do |
|---|---|
| **VS Code: claudown never seems to react** | The VS Code panel ignores the status line. Do the one-time calibration in part 2A, or tick **Claude Code: Use Terminal** in Settings, or install the optional bridge in `vscode_bridge_extension/`. The log says `usage unknown … NOT guessing` until one of these is done. |
| **The bottom line says `waiting for data`** | Normal at the start of a session: send one message. If it never changes, your account may not get usage numbers (API-key accounts don't). claudown will still react if you actually hit the limit. |
| **No `claudown` line at the bottom at all** | Close and reopen Claude Code. Make sure `python --version` works in a terminal, then run the installer again. |
| **Using Claude in the browser, and the laptop didn't turn off** | Expected: the cloud can't turn off your laptop by itself. Use the listener from part 2C. Check that the listener and tunnel windows are still open, that the address and password in the environment settings match, and that both sides are armed. |
| **`computer-use` doesn't appear in `/mcp`** | That optional feature needs a **Mac**, a **Pro, Max or Ultra plan** (not Team or Enterprise), a claude.ai login and an up-to-date Claude Code. You don't need it: claudown's normal shutdown works without it. |
| **The log says `DRY_RUN: would execute`** | Practice mode is working. Arm it when you're ready (part 4). |
| **The log says `all shutdown commands failed`** | Mac/Linux: add the permission line from part 4. |
| **It acted once and then never again** | That's intentional: it acts once per 5-hour window. It resets when the window does. |
| **I installed another status line tool after claudown** | Run `python scripts/claudown_setup.py` again. claudown keeps the other tool and shows both lines. |
| **I want to remove claudown** | Run `python scripts/claudown_setup.py --uninstall`. Your previous settings are restored. |
