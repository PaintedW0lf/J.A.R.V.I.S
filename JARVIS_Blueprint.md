# J.A.R.V.I.S. — Build Blueprint

*Personal productivity assistant for Vanshika · v0.1 built · Updated October 22, 2026*

This document describes what Jarvis is, how it is built, and what comes next. For setup steps, see `jarvis/README.md`.

## 1. What we are building

J.A.R.V.I.S. ("Just A Rather Very Intelligent System") started as Tony Stark's butler-turned-AI in the Iron Man films (2008). He was named after Edwin Jarvis, the Avengers' human butler in the comics. What makes the character feel intelligent isn't the voice or the holograms. It's that he already knows what Stark needs. Peter Diamandis' essay *JARVIS Is Coming* puts it the same way: picture the world's best executive assistant, "all-knowing and almost psychic," who handles things before you have to ask.

The alfred_ review turns that idea into a test we can measure. A real Jarvis has to be **proactive** (it tells you before you ask) and **autonomous** (it does the work without step-by-step instructions). The Instagram reel you shared (lukebuildsai) gives us the architecture: Jarvis isn't one AI. It's an **orchestrator coordinating a team of specialized agents**, each with its own job.

So our Jarvis does these things:

- **Reads your IBM Outlook email** and flags what needs your answer.
- **Tracks the replies you're waiting on**, and drafts a nudge when someone hasn't answered.
- **Reads your Outlook calendar.** It spots overlapping meetings and finds free blocks.
- **Sends a morning brief** at 06:30 (configurable): what needs you, the meetings ahead, and the best IBM goal to work on today.
- **Drafts replies in your voice.** You review every draft. Nothing is sent without your approval.
- **Reads your IBM Goals, MyScore and YourLearning** and matches them to your free time to say what you can do today.
- **Takes voice and text input**, including double-clap to wake, in the holographic interface you chose to keep.

## 2. Decisions made

| Question | Decision |
|---|---|
| Email and calendar | **Outlook, IBM work account (@ibm.com)** via Microsoft Graph. Google/Gmail is out of scope for now. |
| Where it runs | **Locally on your Mac** (`127.0.0.1:8765`). Private GitHub repo for the code only. Free cloud later, once IBM agrees. |
| AI | **IBM Consulting Advantage (ICA)** APIs ("Claude Advantage Assist", "ICA Assist"). Base URL, model, key and API style are set in Settings. The key lives in the macOS Keychain. |
| IBM data | **Now:** you drop saved pages in `~/Jarvis/IBM Drop`. **Later, with permission:** a Chrome extension (click-to-send). **Later still:** official SuccessFactors API if IBM grants access. |
| Interface | Kept the holographic look you liked. Added status lights (AI / Outlook / IBM), a Settings panel and a goals panel. |

## 3. Architecture (as built)

```
 Voice / Text ──▶  Orchestrator (chat)  ◀── Scheduler (sync every 5 min, brief at 06:30)
 (browser)               │
   ┌───────────┬─────────┼─────────┬──────────┬───────────┐
   ▼           ▼         ▼         ▼          ▼           ▼
 Inbox      Follow-ups  Calendar  Drafting  Briefing   IBM Goals
 triage                                                  agent
   │           │         │         │          │           │
   └───────────┴────┬────┴─────────┴──────────┴───────────┘
                    ▼
     Outlook (Microsoft Graph)      IBM drop folder / extension
                    ▼
        SQLite (~/.jarvis/jarvis.db) · Keychain · audit log
                    ▼
          Approval gate: only "Approve and send" sends mail
```

| Agent | Job |
|---|---|
| Inbox triage | Sorts new mail into *needs you*, *FYI* or *noise* and pulls out a one-line task and due date. Uses your AI when configured, simple rules otherwise. |
| Follow-ups | Finds mail you sent that asked something and got no reply after 3 days. Drafts a nudge. |
| Calendar | Today's meetings, overlaps, and free blocks of 30 minutes or more inside work hours. Can add a focus block after you confirm. |
| Drafting | Writes replies in your tone, using your recent sent mail as samples. Uses [brackets] for anything you need to fill in. |
| Briefing | Builds the morning brief. Falls back to a plain-text brief if no AI key is set. |
| IBM Goals | Reads Goals, MyScore and YourLearning. Ranks overdue, due-soon and "Not Met" items, and assigns each a free slot today. |
| Orchestrator | The chat. Routes your question to the right agent and proposes actions (draft, block time). |

**Autonomy rules.**

- **Automatic:** reading, classifying, flagging, tracking, summarizing, preparing drafts.
- **Needs your approval:** sending email, adding calendar blocks.
- **Never:** deleting email, or sending data anywhere except your Mac, Outlook and your configured AI endpoint.

## 4. Connectors

**Outlook (Microsoft Graph).** Sign-in uses the device-code flow, so there is no redirect URL or client secret. Delegated scopes: `Mail.ReadWrite`, `Mail.Send`, `Calendars.ReadWrite`, `User.Read`. It needs a one-time Entra app registration. IBM will likely require **admin consent**, so expect to ask IBM IT. The README has the wording for the request.

**AI (ICA).** Jarvis speaks two API styles: Anthropic (`/v1/messages`) and OpenAI-compatible (`/chat/completions`). Authentication is either `x-api-key` or `Authorization: Bearer`. You pick whichever matches ICA's example request.

**IBM portals.** They sit behind w3id, so employees can't create API keys. We read the pages instead:

| Page | What Jarvis extracts |
|---|---|
| SuccessFactors Goals (2026 Goal Plan) | Business Outcomes and Skills goals, due dates, status |
| MyScore metrics | Yearly credential goals: Met / Not Met / Not Applicable, current and expected level |
| YourLearning | Courses in progress |
| YourLearning queue | Courses you're enrolled in or have queued |

Formats accepted: PDF, HTML, MHTML, XLSX, CSV, TXT, JSON. The built-in reader understands the layouts in your screenshots. If your AI is set up it does the extraction, with the built-in reader as backup.

**"Tells me what can be done."** The goals agent combines your goals, how urgent each is, and today's free calendar blocks. Example from the tests: *"On your IBM goals, AZ-900 certification is due in 9 days. Use 10:15–11:00 today."*

## 5. Voice

- **Speech in and out:** the browser's Web Speech API. It's free and works in Chrome and Edge.
- **Clap to wake:** the page listens for a double clap through the microphone and then starts listening for your command. Microphone audio is analysed in the browser only.
- **Same path for everything:** voice and text go through the same orchestrator.

## 6. Tech stack (as built)

| Layer | Choice |
|---|---|
| Interface | Single HTML page served by the local app |
| Backend | Python FastAPI |
| Data | SQLite in `~/.jarvis/` |
| Scheduling | APScheduler (mail sync every 5 minutes, brief at the time you set) |
| Outlook | MSAL + Microsoft Graph |
| Secrets | macOS Keychain via `keyring` (file fallback with owner-only permissions) |
| IBM files | pypdf, BeautifulSoup, openpyxl |

## 7. Roadmap

1. **Phase 1 (done):** blueprint and UI prototype.
2. **Phase 2 (built, v0.1):** local app, Outlook connector, AI client, triage, follow-ups, calendar, drafting with approval, morning brief, IBM drop-folder reader, Settings, voice.
3. **Phase 2.5 (you, next):** register the Outlook app and get IBM admin consent, add the ICA key, drop your four IBM pages, and test with real data. Real-world checks I could not do myself: real Outlook, the real ICA endpoint, a real IBM PDF export.
4. **Phase 3:** Chrome extension for click-to-send, once IBM permits. Meeting prep briefs 15 minutes before each meeting. Weekly goals review. Start at login.
5. **Phase 4:** SMS or email delivery of the brief, a free cloud option (only after IBM approval), a mobile view.
6. **Phase 5:** more agents (research, travel, learning planner), a better voice, and a "Hey Jarvis" wake word.

## 8. Risks and open items

- **IBM admin consent for Outlook** may take time or be refused. If refused, the fallback is manual forwarding or no Outlook connection (goals and chat still work).
- **IBM data policy.** Sending work mail and goals to the ICA endpoint should be fine since it is IBM's own gateway. Check before using any outside AI service or cloud host.
- **Browser extension** only after permission. Scraping IBM portals without approval is off the table.
- **Not yet verified:** the new interface visually, the ICA connection, and a real PDF export from IBM.
- **The 06:30 brief** needs Jarvis running. The README includes a start-at-login option.
