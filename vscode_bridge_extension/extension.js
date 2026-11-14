// claudown bridge - optional VS Code extension stub (plain JavaScript, no build step).
//
// The Claude Code VS Code panel runs hooks but never runs `statusLine`, so the
// zero-token CLI sensor stays silent there. This extension:
//   1. runs vscode_transcript_sensor.py --write on a timer (local files only),
//   2. shows the newest reading (statusLine if fresh, else transcripts) in the status bar,
//   3. offers a one-click switch to Claude Code's terminal mode, which DOES run
//      statusLine and restores the full, exact sensor path.
// It makes no network requests and never talks to Claude.
"use strict";

const vscode = require("vscode");
const cp = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const STALE_SECONDS = 900;

function claudeDir() {
  return process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), ".claude");
}

function settings() {
  const cfg = vscode.workspace.getConfiguration("claudown");
  return {
    python: cfg.get("pythonPath") || (process.platform === "win32" ? "python" : "python3"),
    script: cfg.get("sensorScript") || path.join(claudeDir(), "claudown", "vscode_transcript_sensor.py"),
    interval: Math.max(10, cfg.get("intervalSeconds") || 60),
    threshold: cfg.get("threshold") || 95,
  };
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(path.join(claudeDir(), "claudown_state.json"), "utf8"));
  } catch (e) {
    return {};
  }
}

function pickReading(st) {
  const now = Date.now() / 1000;
  const fresh = st.updated_at && now - st.updated_at < STALE_SECONDS &&
    (!st.five_hour_resets_at || now < st.five_hour_resets_at);
  if (fresh && typeof st.five_hour_pct === "number") {
    return { pct: st.five_hour_pct, source: "status line (exact)" };
  }
  if (typeof st.transcript_pct === "number") {
    return { pct: st.transcript_pct, source: "transcripts (" + st.transcript_basis + ")" };
  }
  return { pct: null, source: st.transcript_basis || "no data yet" };
}

function activate(context) {
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  item.command = "claudown.refresh";
  context.subscriptions.push(item);
  let timer = null;

  function render() {
    const s = settings();
    const r = pickReading(readState());
    if (r.pct === null) {
      item.text = "$(shield) claudown 5h ?";
      item.tooltip = "claudown can't read your usage yet (" + r.source + "). It is not guessing. " +
        "See GETTING_STARTED.md > Troubleshooting, or run 'claudown: Switch Claude Code to terminal mode'.";
      item.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
    } else {
      item.text = "$(shield) claudown 5h " + Math.round(r.pct) + "%";
      item.tooltip = "5-hour usage from " + r.source + ". Gate at " + s.threshold + "%.";
      item.backgroundColor = r.pct >= s.threshold
        ? new vscode.ThemeColor("statusBarItem.errorBackground")
        : r.pct >= s.threshold * 0.8 ? new vscode.ThemeColor("statusBarItem.warningBackground") : undefined;
    }
    item.show();
  }

  function poll() {
    const s = settings();
    if (!fs.existsSync(s.script)) {
      item.text = "$(shield) claudown not installed";
      item.tooltip = "Couldn't find " + s.script + ". Run the claudown installer first.";
      item.show();
      return;
    }
    cp.execFile(s.python, [s.script, "--write"], { timeout: 30000, windowsHide: true }, () => render());
  }

  function schedule() {
    if (timer) clearInterval(timer);
    timer = setInterval(poll, settings().interval * 1000);
  }

  context.subscriptions.push(
    vscode.commands.registerCommand("claudown.refresh", poll),
    vscode.commands.registerCommand("claudown.openLog", () =>
      vscode.window.showTextDocument(vscode.Uri.file(path.join(claudeDir(), "claudown.log")))),
    vscode.commands.registerCommand("claudown.useTerminalMode", async () => {
      await vscode.workspace.getConfiguration("claudeCode")
        .update("useTerminal", true, vscode.ConfigurationTarget.Global);
      vscode.window.showInformationMessage(
        "Claude Code will now open in terminal mode, which runs claudown's exact status line sensor. " +
        "Close and reopen Claude Code to apply.");
    }),
    vscode.workspace.onDidChangeConfiguration((e) => { if (e.affectsConfiguration("claudown")) schedule(); }),
    { dispose: () => timer && clearInterval(timer) }
  );

  poll();
  schedule();
}

function deactivate() {}

module.exports = { activate, deactivate };
