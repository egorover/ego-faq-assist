const form = document.querySelector("#chat-form");
const input = document.querySelector("#message-input");
const messages = document.querySelector("#messages");
const sendButton = document.querySelector("#send-button");
const newChatButton = document.querySelector("#new-chat");

let sessionId = null;
let sending = false;

function addMessage(text, role, sources = []) {
  const article = document.createElement("article");
  article.className = `message ${role === "user" ? "user-message" : "assistant-message"}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  article.append(bubble);
  if (sources.length) {
    const sourceList = document.createElement("div");
    sourceList.className = "sources";
    sourceList.append(document.createTextNode("Источники: "));
    sources.forEach((source, index) => {
      if (index) sourceList.append(document.createTextNode(" · "));
      sourceList.append(document.createTextNode(`${source.question} (${source.source})`));
    });
    bubble.append(sourceList);
  }
  messages.append(article);
  messages.scrollTop = messages.scrollHeight;
  return article;
}

function setSending(value) {
  sending = value;
  sendButton.disabled = value;
  input.disabled = value;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || sending) return;

  addMessage(message, "user");
  input.value = "";
  setSending(true);
  const typing = addMessage("Думаю над ответом…", "assistant");
  typing.classList.add("typing");

  try {
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `Ошибка сервера (${response.status})`);
    sessionId = payload.session_id;
    typing.remove();
    addMessage(payload.answer, "assistant", payload.sources);
  } catch (error) {
    typing.remove();
    addMessage(`Не удалось получить ответ: ${error.message}. Попробуйте ещё раз.`, "assistant");
  } finally {
    setSending(false);
    input.focus();
  }
});

input.addEventListener("input", () => {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

newChatButton.addEventListener("click", () => {
  sessionId = null;
  messages.replaceChildren();
  addMessage("Новый диалог начат. Чем могу помочь?", "assistant");
  input.focus();
});
