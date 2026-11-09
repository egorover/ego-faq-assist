(() => {
  const panel = document.querySelector(".faq-panel[data-faq-api-url]");
  if (!panel) return;

  const apiUrl = panel.dataset.faqApiUrl.trim();
  const form = document.getElementById("faq-form");
  const input = document.getElementById("faq-question");
  const submitButton = document.getElementById("faq-submit");
  const newChatButton = document.getElementById("faq-new-chat");
  const conversation = document.getElementById("faq-conversation");
  const status = document.getElementById("faq-status");
  if (
    !apiUrl ||
    !form ||
    !input ||
    !submitButton ||
    !newChatButton ||
    !conversation ||
    !status
  ) {
    return;
  }

  const storageKey = "ego-promptfolio.faq.session-id";
  let sessionId = null;
  let storageAvailable = true;
  let isLoading = false;

  try {
    const storedSessionId = window.sessionStorage.getItem(storageKey);
    if (storedSessionId && storedSessionId.length <= 100) {
      sessionId = storedSessionId;
    } else if (storedSessionId) {
      window.sessionStorage.removeItem(storageKey);
    }
  } catch {
    storageAvailable = false;
  }

  const setStatus = (message, kind = "info") => {
    status.className = `faq-status alert mb-4 alert-${kind}`;
    status.textContent = message;
  };

  if (!storageAvailable) {
    setStatus(
      "Хранилище сессии недоступно: продолжение диалога после перезагрузки может не сохраниться.",
      "warning"
    );
  } else if (sessionId) {
    setStatus(
      "Предыдущая сессия будет продолжена. Сообщения до перезагрузки здесь не отображаются.",
      "info"
    );
  } else {
    setStatus("Задайте вопрос. Подключение к ассистенту проверяется при отправке.", "info");
  }

  input.disabled = false;
  submitButton.disabled = false;
  newChatButton.disabled = false;

  const appendText = (parent, tagName, className, value) => {
    const element = document.createElement(tagName);
    if (className) element.className = className;
    element.textContent = value;
    parent.append(element);
    return element;
  };

  const appendExchange = (question, answer, sources) => {
    const exchange = document.createElement("article");
    exchange.className = "faq-exchange";

    const userMessage = document.createElement("div");
    userMessage.className = "faq-message faq-message-user";
    appendText(userMessage, "h2", "faq-message-label", "Вы");
    appendText(userMessage, "p", "faq-message-text", question);
    exchange.append(userMessage);

    const assistantMessage = document.createElement("div");
    assistantMessage.className = "faq-message faq-message-assistant";
    appendText(assistantMessage, "h2", "faq-message-label", "FAQ-ассистент");
    appendText(assistantMessage, "p", "faq-message-text", answer);

    if (sources.length === 0) {
      appendText(
        assistantMessage,
        "p",
        "faq-no-sources",
        "Подтверждённый ответ в базе знаний не найден."
      );
    } else {
      const sourceList = document.createElement("ul");
      sourceList.className = "faq-sources";
      appendText(assistantMessage, "h3", "faq-sources-title", "Источники");
      sources.forEach((source) => {
        const item = document.createElement("li");
        item.className = "faq-source";
        appendText(item, "span", "faq-source-question", source.question);
        appendText(item, "span", "faq-source-name", source.source);
        appendText(
          item,
          "span",
          "faq-source-similarity",
          `Similarity: ${source.similarity.toFixed(3)}`
        );
        sourceList.append(item);
      });
      assistantMessage.append(sourceList);
    }

    exchange.append(assistantMessage);
    conversation.append(exchange);
    exchange.scrollIntoView({ behavior: "smooth", block: "nearest" });
  };

  const errorMessageFor = (httpStatus) => {
    if (httpStatus === 413 || httpStatus === 422) {
      return "Проверьте вопрос: он не должен быть пустым и не может превышать 4000 символов.";
    }
    if (httpStatus === 502 || httpStatus === 503) {
      return "Сервис временно недоступен. Проверьте подключение и попробуйте ещё раз.";
    }
    return "Не удалось получить ответ. Попробуйте ещё раз.";
  };

  const setLoading = (loading) => {
    isLoading = loading;
    input.disabled = loading;
    submitButton.disabled = loading;
    newChatButton.disabled = loading;
    conversation.setAttribute("aria-busy", String(loading));

    if (loading) {
      status.className = "faq-status alert mb-4 alert-info";
      status.replaceChildren();
      const spinner = document.createElement("span");
      spinner.className = "faq-loading-spinner spinner-border spinner-border-sm me-2";
      spinner.setAttribute("aria-hidden", "true");
      status.append(spinner, document.createTextNode("Отправляем вопрос…"));
    }
  };

  const saveSessionId = (value) => {
    sessionId = value;
    if (!storageAvailable) return;
    try {
      window.sessionStorage.setItem(storageKey, value);
    } catch {
      storageAvailable = false;
      setStatus(
        "Ответ получен, но хранилище сессии недоступно: продолжение после перезагрузки может не сохраниться.",
        "warning"
      );
    }
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isLoading) return;

    const message = input.value.trim();
    if (!message) {
      setStatus("Введите вопрос перед отправкой.", "warning");
      input.focus();
      return;
    }
    if (message.length > 4000) {
      setStatus("Вопрос не может превышать 4000 символов.", "warning");
      input.focus();
      return;
    }

    const payload = { message };
    if (sessionId) payload.session_id = sessionId;

    setLoading(true);
    try {
      const response = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        credentials: "omit",
      });
      if (!response.ok) {
        throw new Error(String(response.status));
      }

      const data = await response.json();
      if (
        typeof data.answer !== "string" ||
        typeof data.session_id !== "string" ||
        data.session_id.length < 1 ||
        data.session_id.length > 100 ||
        !Array.isArray(data.sources) ||
        !data.sources.every(
          (source) =>
            source &&
            typeof source.question === "string" &&
            typeof source.source === "string" &&
            typeof source.similarity === "number" &&
            Number.isFinite(source.similarity)
        )
      ) {
        throw new Error("invalid-response");
      }

      saveSessionId(data.session_id);
      appendExchange(message, data.answer, data.sources);
      input.value = "";
      if (storageAvailable) {
        setStatus(
          data.sources.length
            ? "Ответ получен."
            : "Ответ получен; подтверждённые источники не найдены.",
          data.sources.length ? "success" : "warning"
        );
      } else {
        setStatus(
          "Ответ получен, но продолжение диалога после перезагрузки может не сохраниться.",
          "warning"
        );
      }
    } catch (error) {
      const errorMessage = typeof error?.message === "string" ? error.message : "";
      const httpStatus = /^\d{3}$/.test(errorMessage) ? Number(errorMessage) : null;
      setStatus(
        httpStatus ? errorMessageFor(httpStatus) : "Сервис временно недоступен. Попробуйте ещё раз.",
        "danger"
      );
    } finally {
      setLoading(false);
    }
  });

  newChatButton.addEventListener("click", () => {
    if (isLoading) return;
    sessionId = null;
    conversation.replaceChildren();
    if (storageAvailable) {
      try {
        window.sessionStorage.removeItem(storageKey);
      } catch {
        storageAvailable = false;
      }
    }
    input.value = "";
    setStatus(
      storageAvailable
        ? "Начат новый диалог. Подключение проверяется при отправке вопроса."
        : "Не удалось очистить сохранённую сессию. После перезагрузки предыдущая сессия может восстановиться.",
      storageAvailable ? "info" : "warning"
    );
    input.focus();
  });
})();
