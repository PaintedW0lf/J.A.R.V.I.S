# J.A.R.V.I.S.

Your proactive work assistant. It reads your IBM Outlook, flags what needs you, tracks replies you're waiting on, reads your calendar, follows your IBM Goals, MyScore and YourLearning, and has a morning brief ready at 6:30. It drafts replies, but **nothing is sent or added to your calendar until you approve it.**

## How it runs

Jarvis is one app that runs **on your Mac**. It's a small Python server at `http://localhost:8765` and the holographic interface you open in Chrome. It's a team of agents inside one program, not one agent doing everything: Inbox, Follow-ups, Calendar, Drafting, Briefing and IBM goals each have one job, and the orchestrator decides who handles what.

- **Your data stays on this Mac.** Mail, goals and the brief are stored in `~/.jarvis/jarvis.db`. The server only listens on `127.0.0.1`, so nobody else on your network can reach it.
- **Secrets go in the macOS Keychain.** Your AI key is stored there, and the Outlook sign-in token is in `~/.jarvis/` with owner-only permissions.
- **GitHub is only for the code.** Push this folder to a *private* repo for backup and version history. `.gitignore` already keeps your database, keys and IBM files out of it.
- **The brief needs Jarvis running.** Scheduled jobs (sync every 5 minutes, brief at 6:30) only run while Jarvis is running. See "Keep it running" below.
- **The cloud is optional and later.** If you want the brief to arrive while your laptop is off, a cloud server would have to hold your IBM mail, and that needs IBM's sign-off first.

## Start it

1. Install Python 3.10 or newer if you don't have it: `python3 --version`. If needed, get it from python.org or run `brew install python`.
2. Open Terminal in this folder and run:

   ```bash
   chmod +x start.sh
   ./start.sh
   ```

   The first run installs everything in about a minute. Chrome then opens `http://localhost:8765`.
3. Click **Settings** and connect the three services below.

Use Chrome or Edge, because voice input and clap to wake need them.

## 1. Add your AI key (ICA)

Use your **IBM Consulting Advantage** key for work data, not a personal Anthropic key.

1. Open the ICA API or developer page and copy three things: the **base URL**, the **model name** (for example the Claude model behind Claude Advantage Assist) and **your API key**.
2. In Jarvis, go to **Settings → AI provider**:
   - **API style:** if ICA's example request calls `/v1/messages`, choose *Anthropic format*. If it calls `/chat/completions`, choose *OpenAI format*.
   - **Key goes in:** use whatever header ICA's example uses, either `x-api-key` or `Authorization: Bearer`.
   - Paste the base URL, model and key.
3. Click **Save and test**. You should see "Connected. The AI replied: ready."

If the test fails, the message says why. A rejected key usually means the wrong "key goes in" choice. A 404 usually means the base URL needs or shouldn't have `/v1`.

**Without a key**, Jarvis still works using built-in rules, with a plain brief and simple triage. The key adds better triage, drafts in your voice and free-form questions.

## 2. Connect IBM Outlook

Jarvis signs in to Microsoft 365 the way the Teams or Outlook apps do. You use your normal `@ibm.com` login and MFA, and you don't give Jarvis your password.

**One-time app registration.** Microsoft requires every app to have an ID.

1. Go to entra.microsoft.com → **App registrations → New registration**. Name it `Jarvis (personal)` and choose *Accounts in this organizational directory only*.
2. Under **Authentication**, turn on **Allow public client flows**.
3. Under **API permissions → Microsoft Graph → Delegated**, add `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite` and `User.Read`.
4. Copy the **Application (client) ID** and the **Directory (tenant) ID** into Jarvis Settings → Outlook.

If IBM doesn't let you create app registrations, IBM IT has to create one for you or approve one. Ask the IT service desk for "a personal productivity app using Microsoft Graph delegated permissions (Mail.ReadWrite, Mail.Send, Calendars.ReadWrite), device-code sign-in, data stored only on my laptop." If your request is for internal ICA tooling, mention that too. **Admin consent is likely required at IBM.** If sign-in says "Need admin approval," that's the step you're waiting on.

**Sign in:** click **Connect Outlook**. Jarvis shows a code and opens microsoft.com/devicelogin. Enter the code, sign in, and you're done. Your inbox and calendar appear within a minute.

## 3. Connect IBM Goals, MyScore and YourLearning

These portals sit behind w3id and don't give employees API keys. So for now, you give Jarvis copies of the pages.

**Phase A: drop files (works today).** For each page:

| Page | How to save it | Name it with |
|---|---|---|
| SuccessFactors Goals (2026 Goal Plan) | Click **Print to PDF** on the page, or File → Save Page As → *Webpage, HTML Only* | `goals` |
| MyScore metrics | File → Save Page As, or Print → Save as PDF | `myscore` |
| YourLearning, in progress | Save Page As | `learning` |
| YourLearning, queue | Save Page As | `queue` |

Then either drag the files onto **Settings → IBM portals**, or drop them in the folder `~/Jarvis/IBM Drop`. Jarvis checks that folder every 5 minutes. When you save a newer version, Jarvis updates. When you delete a file, its items disappear.

If a page won't save cleanly, use the simplest method: press Cmd+A then Cmd+C on the page, paste into TextEdit, and save as `goals.txt`.

Jarvis reads the page with your ICA AI if one is set up, or with a built-in reader otherwise. The built-in reader already understands the layouts in your screenshots: Business Outcomes and Skills with due dates and statuses, and MyScore's Met, Not Met, Not Applicable and Current/Expected levels.

**Phase B: browser extension (after you get permission).** The `extension/` folder has a small Chrome extension. Open a Goals, MyScore or YourLearning page, click the Jarvis icon, and it sends that page's text to Jarvis on your Mac (`127.0.0.1`), nowhere else. It only runs when you click it. **Check that IBM policy allows it before installing.** To install it, open `chrome://extensions`, turn on Developer mode, click **Load unpacked**, and choose the `extension` folder.

**Later: official APIs.** If IBM grants SuccessFactors OData API access, it can feed in through `/api/ibm/import` without changing anything else.

## What you'll see

- **Morning brief:** what needs you, who owes you a reply, your meetings and any overlaps, and the single most useful IBM goal to work on in a free slot.
- **Needs you:** emails where someone expects your answer. Click **Draft reply** to review it, edit it, and then either **Approve and send** or **Save to Outlook drafts**.
- **Waiting on replies:** emails you sent that asked something and got no answer after 3 days. Click **Nudge** to draft a polite follow-up.
- **Today:** your meetings, overlaps, and free blocks. Click **Block** to add focus time, after you confirm.
- **IBM goals:** the "Next up" tab ranks what's overdue, due within 14 days, or a required MyScore credential that isn't met, and suggests a time slot today.
- **Voice:** click the mic, or turn on **Clap to wake** and clap twice. Say "mute" to stop spoken replies.

## Keep it running (optional)

To start Jarvis automatically when you log in, so the 6:30 brief is ready:

```bash
cat > ~/Library/LaunchAgents/com.jarvis.assistant.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.jarvis.assistant</string>
  <key>ProgramArguments</key><array>
    <string>$(pwd)/.venv/bin/uvicorn</string><string>jarvis.server:app</string>
    <string>--host</string><string>127.0.0.1</string><string>--port</string><string>8765</string>
  </array>
  <key>WorkingDirectory</key><string>$(pwd)</string>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
EOF
launchctl load ~/Library/LaunchAgents/com.jarvis.assistant.plist
```

Run this from the Jarvis folder after `./start.sh` has run once. If your Mac is asleep at 6:30, the brief is built the next time you open Jarvis, or you can click **Refresh**.

## Put the code on GitHub (private)

```bash
git init && git add . && git commit -m "Jarvis v0.1"
gh repo create jarvis --private --source=. --push   # or create a private repo on github.com and push
```

Keep the repo **private**. Before using IBM GitHub Enterprise or a public github.com account, check which one IBM expects for personal tools.

## Files

```
start.sh              start Jarvis
jarvis/server.py      local web server and API
jarvis/agents.py      the agent team: triage, follow-ups, calendar, goals, brief, drafting, chat
jarvis/outlook.py     Microsoft Graph connector (device-code sign-in)
jarvis/ibm.py         Goals / MyScore / YourLearning reader
jarvis/ai.py          ICA / Anthropic / OpenAI-format client
jarvis/config.py      settings (~/.jarvis/settings.json) and Keychain secrets
web/index.html        the interface
extension/            phase B Chrome extension (don't install until permitted)
```
