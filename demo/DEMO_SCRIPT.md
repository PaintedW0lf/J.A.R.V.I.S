# Jarvis demo: 4-minute screen recording

**Before you record**

1. Copy the demo files into your drop folder: `cp demo/schedule.json demo/demo_mail.json ~/Jarvis/"IBM Drop"/` and copy `demo_goals.txt` to `~/Jarvis/"IBM Drop"/goals.txt` and `myscore_demo.txt` to `.../myscore.txt`.
2. Run `./start.sh`. In Settings, set Outlook to **Schedule file**, click **Check schedule file**, and make sure the AI shows Ready.
3. Use the sample data only. Don't show real IBM mail, your API key, or real goals on screen.
4. Turn on Do Not Disturb, close other tabs, set Chrome zoom to 110%, and test the mic once.
5. Edit `schedule.json` so the dates match the day you record (today's events must be on today's date).

---

## 0:00 Hook (say it to camera or over the screen)

"Most assistants wait for you to ask. I wanted one that shows up with the answer first. This is Jarvis, a personal assistant I built that reads my inbox, watches my calendar, tracks my goals, and tells me what to do before I ask."

Show: the Jarvis screen, glowing, with the morning brief at the top.

## 0:20 The morning brief (proactive)

Say: "Every morning at 6:30 it builds this brief by itself. I didn't ask for it."
Show: click **Refresh**, let it read aloud. Point to: 2 emails need me, 1 reply I'm waiting on, today's meetings, and the AZ-900 certification due soon.

## 1:00 Email that needs me (flags + drafts, never sends alone)

Say: "It reads the inbox and sorts what needs me from newsletters."
Show: the **Needs you** list. Click **Draft reply** on Priya's email.
Say: "It writes in my tone, but nothing goes out until I approve."
Show: edit one line, then click **Approve**. Say: "In this demo mode nothing is sent. With my real Outlook it would be."

## 1:50 Waiting on replies (follow-ups)

Show: **Waiting on replies**, with Daniel at 5 days. Click **Nudge** and show the polite follow-up it drafts.
Say: "I never have to remember who I'm waiting on."

## 2:20 Calendar and goals (autonomous)

Show: today's meetings and any free blocks. Open the goals panel on **Next up**.
Say: "It connects my IBM goals, MyScore and learning to my free time. AZ-900 is tomorrow, so it tells me to protect today for it."
Show: **Block** a focus slot and confirm it. The event appears in the schedule file.

## 3:00 Voice

Show: click the mic, or clap twice. Say: "What's on my plate today?" Let it answer aloud.
Say: "I can change its voice and make it deeper in Settings."

## 3:30 How I built it (30 seconds)

Say: "It's one small app on my laptop. A team of small agents: inbox, follow-ups, calendar, drafting, goals and a briefing agent, with one coordinator. It uses IBM's Consulting Advantage AI, and my data stays on my machine. I built it by describing what I wanted to Claude and iterating: blueprint first, then the interface, then the connectors."
Show: Settings screen (hide the key), then the GitHub repo.

## 3:50 Close

"The principle: Jarvis isn't a voice. It's showing up with the answer before you ask. If you want to build your own, the code and README are in the repo."

---

## Tips

- Record in one take per section, then cut together.
- If something fails live, say "demo mode" and move on. Don't debug on camera.
- Read the numbers and names off the screen, never real client or colleague names.
- Check IBM guidance before sharing the recording outside IBM.
