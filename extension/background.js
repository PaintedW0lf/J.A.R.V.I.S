// Phase B. Don't install until you've confirmed IBM allows it.
// When you click the extension icon on a Goals, MyScore or YourLearning page,
// it copies the visible page text and sends it to Jarvis on your own Mac
// (127.0.0.1). Nothing goes anywhere else. Jarvis reads it like a dropped file.

function sourceFor(url) {
  if (/sapsf\.com\/.*goal/i.test(url)) return "goals";
  if (/myscore/i.test(url)) return "myscore";
  if (/yourlearning\.ibm\.com/i.test(url)) return "learning";
  return null;
}

chrome.action.onClicked.addListener(async (tab) => {
  const source = sourceFor(tab.url || "");
  if (!source) return badge(tab.id, "?", "Open your Goals, MyScore or YourLearning page first");
  const [{ result: text }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id }, func: () => document.body.innerText,
  });
  const blob = new Blob([text], { type: "text/plain" });
  const fd = new FormData();
  fd.append("file", blob, `${source}-from-extension.txt`);
  try {
    const r = await fetch("http://127.0.0.1:8765/api/ibm/upload", { method: "POST", body: fd });
    badge(tab.id, r.ok ? "✓" : "!", r.ok ? "Sent to Jarvis" : "Jarvis couldn't read the page");
  } catch {
    badge(tab.id, "!", "Start Jarvis on your Mac first");
  }
});

function badge(tabId, text, title) {
  chrome.action.setBadgeText({ tabId, text });
  chrome.action.setTitle({ tabId, title });
  setTimeout(() => chrome.action.setBadgeText({ tabId, text: "" }), 4000);
}
