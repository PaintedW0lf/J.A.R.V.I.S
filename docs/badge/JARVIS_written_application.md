# J.A.R.V.I.S: Written application answers

Answers for the IBM Generative & Agentic AI Developer (Experienced) badge application.

## 1. Generative or Agentic AI Client or Project (limit 1000)

Project: J.A.R.V.I.S ("Just A Rather Very Intelligent System"), a personal AI work assistant I am designing and building myself. Ongoing, early phase. Dates: [MM/YYYY to present].

Business problem: the things I am measured on live in three separate IBM tools that don't talk to each other or to my calendar: MyScore (my yearly credential goals), SuccessFactors (my 2026 Goal Plan: Business Outcomes and Skills) and YourLearning (my courses and learning queue). Add my calendar and email, and deadlines are easy to miss, and learning never finds a slot in a full week. Most assistants are reactive: you ask, they answer.

Objective: a proactive assistant that tells me what matters before I ask. Multiple agents work behind one interface, coordinated by a central "reactor". It brings MyScore, SuccessFactors and YourLearning together with my calendar in a spoken and written morning brief, and proposes next steps. I make every final call.

## 2. watsonx or Strategic Partner Experience (limit 1000)

Model plane: IBM Consulting Advantage (ICA), using the Anthropic Claude models it provides (Claude Advantage Assist). One ICA credential, kept in the macOS Keychain, and no direct model-vendor calls, so the work stays inside IBM's data boundary. The provider is swappable (any Anthropic- or OpenAI-compatible endpoint).

How Claude is used agentically: each job has its own role and instructions: a MyScore credentials agent, a SuccessFactors goals agent, a YourLearning agent, a calendar agent, a morning brief agent, and (next) inbox triage, follow-up and drafting agents. A central reactor coordinates them. Claude reads my exported MyScore, SuccessFactors and YourLearning data plus my calendar, connects them (for example, a credential deadline against my free time), and proposes actions such as a study block. It never acts without my confirmation.

I also used Claude as a build partner for design, code and testing. Live ICA behaviour is still being verified.

## 3. Application, Work Product, or Deliverable (limit 3000)

Deliverables: (1) a planning blueprint with design detail, (2) an architecture diagram, and (3) a working local web application with a holographic dashboard. A central reactor shows the agent nodes. I wake it with a double clap and talk to it or type. Everything below runs on demo data.

MY IBM WORK DATA, THE CORE OF THE PROJECT

1. MyScore, credential goals. JARVIS reads my yearly credential goals and their status (Met / Not Met / Not Applicable). It flags credentials due this quarter and links them to my calendar. Example: an AZ-900 exam due tomorrow becomes a proposed study block today ("Block 3:45 to 5:00 for exam prep?"), added only after I confirm.

2. SuccessFactors, 2026 Goal Plan. JARVIS imports my exported goal plan (Business Outcomes and Skills). Goal extraction from the PDF is still being tuned: the current build imports the file but does not yet extract individual goal items, so this is in progress.

3. YourLearning, courses and learning queue. JARVIS reads my queue and compares it with open slots in my week. Example: "two courses in your queue fit this week's free time", so learning gets a real slot instead of staying a someday list.

THE BRIEF THAT TIES IT TOGETHER
Morning brief: a spoken and written summary of my day: meetings ahead, tasks due, credentials due, goals at risk, and learning that fits. It is ready before I ask.

OTHER WORKING CAPABILITIES
Calendar agent: finds free time and proposes blocks. Voice and text: "What's my afternoon like?", "What should I prioritise this week?"

HOW THE DATA GETS IN
These tools sit behind w3id sign-in with no open connector for a personal assistant, so nothing reads them directly. I export my own data and drop the files in a watched folder; a schedule file stands in for my calendar.

ENGINEERING
I added the schedule-file mode so I could build without Outlook access. Testing showed the assistant repeating apologies and promising actions it could not take. I fixed it by limiting chat history, starting free blocks at the next quarter hour, and telling it to report only completed actions.

NEXT, NOT YET CONNECTED
Email: inbox triage, follow-up and drafting agents will flag what needs my answer, track replies I'm waiting on, and draft replies for my review. Nothing is sent without approval. IBM Outlook needs IT admin consent. I have written a browser extension that could read my own w3 pages while I'm logged in, but it is not installed or used. It stays off until IBM confirms it is allowed. I will approach the right permissions and security team first.

## 4. Approach, Methods, and Tools (limit 1000)

I treated it as a product build: blueprint first, then a working UI prototype, then small, tested steps. Each agent has one job (for example, one for MyScore credentials, one for SuccessFactors goals, one for YourLearning), and the reactor coordinates them, so each can be tested and changed on its own.

Platform: IBM Consulting Advantage as the model layer, with Claude. Hosting is local on my Mac, with code in a private repository.

Data approach: MyScore, SuccessFactors and YourLearning have no open connector for a personal assistant. I started with files I export myself. A browser extension is written but not installed, and Outlook is a later step that needs approval. A schedule-file mode let me keep building without Outlook.

Method: I built with Claude as a design and coding partner, tested each use case on demo data, recorded what failed and why, and fixed it before moving on.

## 5. Management of Risks and Ethical Concerns (limit 1000)

Risks: the assistant acting beyond what I asked, a wrong suggestion, private work data (goals, credentials, learning records) leaking, a model claiming it did something it did not, and reading IBM systems without authorisation.

Controls: human in the loop. No calendar change or send without my click. Credentials are in the macOS Keychain, not in code or the repository. My MyScore, SuccessFactors and YourLearning data comes only from files I export myself. I have written a browser extension that could read those pages, but it is not installed or used, and it stays off until IBM confirms it is allowed. Before any browser extension or Outlook connection, I will consult the permissions and security teams. I found the assistant could claim actions it had not taken and fixed it to report only completed actions.

This follows IBM's Trustworthy AI principles: transparency, privacy, accountability and human oversight.
