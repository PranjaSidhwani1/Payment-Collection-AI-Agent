const chatWindow = document.getElementById("chat-window");
const messageInput = document.getElementById("message-input");
const sendBtn = document.getElementById("send-btn");
const resetBtn = document.getElementById("reset-btn");
const typingIndicator = document.getElementById("typing-indicator");
const statusDot = document.getElementById("status-dot");
const subtitle = document.getElementById("subtitle");

function addMessage(role, text) {
  const row = document.createElement("div");
  row.className = `row ${role}`;
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role}`;
  bubble.textContent = text;
  row.appendChild(bubble);
  chatWindow.appendChild(row);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function setBusy(busy) {
  messageInput.disabled = busy;
  sendBtn.disabled = busy;
  typingIndicator.classList.toggle("hidden", !busy);
  if (!busy) {
    messageInput.focus();
  } else {
    chatWindow.scrollTop = chatWindow.scrollHeight;
  }
}

function setOnline(online) {
  statusDot.classList.toggle("online", online);
  subtitle.textContent = online ? "Online" : "Connecting...";
}

async function callApi(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return response.json();
}

async function startConversation() {
  setBusy(true);
  try {
    const data = await callApi("/api/start");
    addMessage("agent", data.message);
    setOnline(true);
  } catch (err) {
    addMessage("agent", "Couldn't connect to the agent. Please refresh to try again.");
    setOnline(false);
  } finally {
    setBusy(false);
  }
}

async function sendMessage() {
  const text = messageInput.value.trim();
  if (!text) return;

  addMessage("user", text);
  messageInput.value = "";
  setBusy(true);

  try {
    const data = await callApi("/api/chat", { message: text });
    addMessage("agent", data.message);
  } catch (err) {
    addMessage("agent", "Something went wrong reaching the agent. Please try again.");
  } finally {
    setBusy(false);
  }
}

async function resetConversation() {
  chatWindow.innerHTML = "";
  await startConversation();
}

sendBtn.addEventListener("click", sendMessage);
messageInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendMessage();
  }
});
resetBtn.addEventListener("click", resetConversation);

startConversation();
