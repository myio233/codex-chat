const starterPrompts = [
  {
    title: "重构一个页面",
    description: "把当前页面收紧成更像对话产品的桌面体验，并直接落地实现。",
    prompt: "帮我把当前页面改得更像成熟对话产品，重点优化桌面端层级、留白和聊天区结构。",
  },
  {
    title: "分析一个 bug",
    description: "定位为什么 SSE 卡住、按钮状态没恢复，或某个接口报错。",
    prompt: "帮我分析这个项目里最近一个前端 bug 的可能原因，并给出修复建议。",
  },
  {
    title: "设计一个功能",
    description: "为 Plus、支付或权限流设计完整的前后端衔接方案。",
    prompt: "帮我设计 Plus 会员升级流程，包括前端入口、状态控制和后端接口衔接。",
  },
  {
    title: "直接生成代码",
    description: "直接给出可运行代码，并说明要改哪些文件。",
    prompt: "帮我直接写一段可运行的前端代码，并说明要改哪些文件。",
  },
];

const state = {
  token: localStorage.getItem("codex_chat_token") || "",
  user: null,
  internalOnly: true,
  allowPublicSignup: false,
  authMode: "login",
  sessions: [],
  activeSessionId: "",
  sending: false,
  adminUsers: [],
};

const refs = {
  loginView: document.getElementById("loginView"),
  chatView: document.getElementById("chatView"),
  chatMain: document.querySelector(".chat-main"),
  loginForm: document.getElementById("loginForm"),
  loginTab: document.getElementById("loginTab"),
  registerTab: document.getElementById("registerTab"),
  nameField: document.getElementById("nameField"),
  nameInput: document.getElementById("nameInput"),
  emailInput: document.getElementById("emailInput"),
  passwordInput: document.getElementById("passwordInput"),
  authSubmitButton: document.getElementById("authSubmitButton"),
  authHint: document.getElementById("authHint"),
  loginMessage: document.getElementById("loginMessage"),
  userNameText: document.getElementById("userNameText"),
  userEmailText: document.getElementById("userEmailText"),
  accountAvatar: document.getElementById("accountAvatar"),
  planBadge: document.getElementById("planBadge"),
  modeSummaryText: document.getElementById("modeSummaryText"),
  signupSummaryText: document.getElementById("signupSummaryText"),
  roleSummaryText: document.getElementById("roleSummaryText"),
  adminPanel: document.getElementById("adminPanel"),
  adminPanelToggle: document.getElementById("adminPanelToggle"),
  adminSummaryText: document.getElementById("adminSummaryText"),
  adminUsersList: document.getElementById("adminUsersList"),
  sessionList: document.getElementById("sessionList"),
  newChatButton: document.getElementById("newChatButton"),
  mobileNewChatButton: document.getElementById("mobileNewChatButton"),
  mobileSidebarToggle: document.getElementById("mobileSidebarToggle"),
  logoutButton: document.getElementById("logoutButton"),
  chatTitle: document.getElementById("chatTitle"),
  chatSubtext: document.getElementById("chatSubtext"),
  messageList: document.getElementById("messageList"),
  composerForm: document.getElementById("composerForm"),
  composerInput: document.getElementById("composerInput"),
  composerStatus: document.getElementById("composerStatus"),
  sendButton: document.getElementById("sendButton"),
  internalBadge: document.getElementById("internalBadge"),
  tierBadge: document.getElementById("tierBadge"),
};

function authHeaders() {
  return state.token ? { Authorization: `Bearer ${state.token}` } : {};
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    let detail = "请求失败";
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      detail = await response.text();
    }
    throw new Error(detail);
  }

  return response.json();
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatTime(timestamp) {
  return new Date(timestamp * 1000).toLocaleString();
}

function setLoginVisible(visible) {
  refs.loginView.classList.toggle("hidden", !visible);
  refs.chatView.classList.toggle("hidden", visible);
}

function updateChatLayoutMode(hasMessages) {
  refs.chatMain.classList.toggle("chat-main-empty", !hasMessages);
  refs.chatMain.classList.toggle("chat-main-has-messages", Boolean(hasMessages));
}

function displayRole(user) {
  if (!user) {
    return "游客";
  }
  if (user.role === "admin") {
    return "管理员";
  }
  return user.plan === "plus" ? "Plus 用户" : "普通用户";
}

function updateModeSummary() {
  refs.modeSummaryText.textContent = state.internalOnly ? "内测锁定" : "公开模式";
  refs.signupSummaryText.textContent = state.allowPublicSignup ? "公开注册已开启" : "公开注册未开启";
  refs.roleSummaryText.textContent = displayRole(state.user);
}

function setAuthMode(mode) {
  state.authMode = mode === "register" ? "register" : "login";
  const register = state.authMode === "register";
  refs.loginTab.classList.toggle("active", !register);
  refs.registerTab.classList.toggle("active", register);
  refs.nameField.classList.toggle("hidden", !register);
  refs.authSubmitButton.textContent = register ? "注册并进入" : "登录进入";
  refs.passwordInput.autocomplete = register ? "new-password" : "current-password";
  refs.authHint.textContent = state.internalOnly
    ? "当前只开放已创建的内部账号进入。"
    : state.allowPublicSignup
      ? "注册成功后即可登录，管理员可手动将用户升级为 Plus。"
      : "当前未开放公开注册，请联系管理员开通账号。";
}

function updateChatSubtext() {
  const session = state.sessions.find((item) => item.session_id === state.activeSessionId);
  if (!session || !session.messages.length) {
    refs.chatSubtext.textContent = "把需求、上下文和 Codex 返回结果都留在同一条对话里。";
    return;
  }

  const completedCount = session.messages.filter((item) => item.status === "completed").length;
  refs.chatSubtext.textContent = `当前会话累计 ${completedCount} 条消息，结果由 Codex CLI 流式回传。`;
}

function initials(name) {
  const trimmed = (name || "").trim();
  return (trimmed[0] || "Y").toUpperCase();
}

function setUser(user, internalOnly) {
  state.user = user;
  state.internalOnly = internalOnly;

  refs.userNameText.textContent = user?.name || "-";
  refs.userEmailText.textContent = user?.email || "-";
  refs.accountAvatar.textContent = initials(user?.name);

  const plan = (user?.plan || "free").toUpperCase();
  refs.planBadge.textContent = plan;
  refs.planBadge.classList.toggle("plus", user?.plan === "plus");
  refs.tierBadge.textContent = plan;
  refs.tierBadge.classList.toggle("meta-chip-strong", user?.plan === "plus");

  refs.internalBadge.textContent = internalOnly ? "Internal only" : "Public";
  refs.adminPanel.classList.toggle("hidden", user?.role !== "admin");
  refs.adminPanel.classList.add("admin-panel-collapsed");

  updateModeSummary();
  updateChatSubtext();
  updateComposerState();
}

function sessionPreview(session) {
  const lastMessage = [...(session.messages || [])].reverse().find((item) => item.content?.trim());
  if (!lastMessage) {
    return "新会话，等待第一条消息。";
  }
  return lastMessage.content.replace(/\s+/g, " ").slice(0, 58);
}

function renderSessions() {
  refs.sessionList.innerHTML = "";

  if (!state.sessions.length) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.innerHTML = "<strong>还没有会话</strong><p>点击上方“新对话”，从一个明确的需求开始。</p>";
    refs.sessionList.appendChild(empty);
    return;
  }

  state.sessions.forEach((session) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `session-item${session.session_id === state.activeSessionId ? " active" : ""}`;
    button.innerHTML = `
      <strong>${escapeHtml(session.title || "New chat")}</strong>
      <p>${escapeHtml(sessionPreview(session))}</p>
      <small>${formatTime(session.updated_at)}</small>
    `;
    button.addEventListener("click", () => openSession(session.session_id));
    refs.sessionList.appendChild(button);
  });
}

function renderAdminUsers() {
  refs.adminUsersList.innerHTML = "";
  refs.adminSummaryText.textContent = `当前 ${state.adminUsers.length} 个账号`;

  if (!state.user || state.user.role !== "admin") {
    return;
  }

  if (!state.adminUsers.length) {
    const empty = document.createElement("div");
    empty.className = "admin-user-card";
    empty.innerHTML = "<strong>还没有其他用户</strong><small>公开注册开启后，新用户会出现在这里。</small>";
    refs.adminUsersList.appendChild(empty);
    return;
  }

  state.adminUsers.forEach((user) => {
    const isCurrentUser = user.user_id === state.user?.user_id;
    const card = document.createElement("div");
    card.className = "admin-user-card";
    card.innerHTML = `
      <div class="admin-user-head">
        <div>
          <strong>${escapeHtml(user.name)}</strong>
          <small>${escapeHtml(user.email)}</small>
        </div>
        <strong class="plan-badge ${user.plan === "plus" ? "plus" : ""}">${user.plan.toUpperCase()}</strong>
      </div>
      <small>${isCurrentUser ? "当前管理员账号，前端里不允许自我禁用或降级。" : `角色：${user.role} · 状态：${user.enabled ? "启用" : "禁用"}`}</small>
      <small class="linux-user-line">Linux: ${escapeHtml(user.linux_username || "未分配")}</small>
      <div class="admin-user-actions">
        <button class="mini-button ${user.plan === "free" ? "active" : ""}" data-action="set-plan" data-user-id="${user.user_id}" data-plan="free" type="button" ${isCurrentUser ? "disabled" : ""}>设为 Free</button>
        <button class="mini-button ${user.plan === "plus" ? "active" : ""}" data-action="set-plan" data-user-id="${user.user_id}" data-plan="plus" type="button" ${isCurrentUser ? "disabled" : ""}>设为 Plus</button>
        <button class="mini-button ${user.enabled ? "danger" : ""}" data-action="toggle-enabled" data-user-id="${user.user_id}" data-enabled="${user.enabled ? "false" : "true"}" type="button" ${isCurrentUser ? "disabled" : ""}>${user.enabled ? "禁用" : "启用"}</button>
      </div>
    `;
    refs.adminUsersList.appendChild(card);
  });
}

function renderEmptyState() {
  const userName = state.user?.name || "你";
  refs.messageList.innerHTML = `
    <section class="welcome-panel">
      <div class="welcome-copy">
        <p class="eyebrow">Codex Agent</p>
        <h3>${escapeHtml(userName)}，今天要让 Agent 处理什么？</h3>
        <p>
          直接给任务、补上下文、继续追问。左边保留会话，右边只做一件事: 把需求和结果都收进同一条线程。
        </p>
      </div>
      <div class="prompt-grid">
        ${starterPrompts
          .map(
            (item) => `
              <button class="prompt-card" type="button" data-prompt="${escapeHtml(item.prompt)}">
                <strong>${escapeHtml(item.title)}</strong>
                <p>${escapeHtml(item.description)}</p>
              </button>
            `
          )
          .join("")}
      </div>
    </section>
  `;
}

function renderMessages() {
  const session = state.sessions.find((item) => item.session_id === state.activeSessionId);
  refs.chatTitle.textContent = session?.title || "New chat";
  updateChatSubtext();

  if (!session || !session.messages.length) {
    updateChatLayoutMode(false);
    renderEmptyState();
    return;
  }

  updateChatLayoutMode(true);

  refs.messageList.innerHTML = session.messages
    .map((message) => {
      const rowClass = message.status === "failed" ? "failed" : message.role;
      const label = message.role === "user" ? "You" : "Codex Agent";
      const avatar = message.role === "user" ? initials(state.user?.name) : "AI";
      const content = message.content || (message.status === "streaming" ? "正在生成..." : "");

      return `
        <article class="message-row ${rowClass}">
          <div class="message-avatar">${escapeHtml(avatar)}</div>
          <div class="message-card">
            <div class="message-head">
              <strong>${label}</strong>
              <span>${formatTime(message.created_at)}</span>
            </div>
            <div class="message-body">${escapeHtml(content)}</div>
            ${message.error ? `<div class="message-error">${escapeHtml(message.error)}</div>` : ""}
          </div>
        </article>
      `;
    })
    .join("");

  refs.messageList.scrollTop = refs.messageList.scrollHeight;
}

function resizeComposer() {
  refs.composerInput.style.height = "0px";
  refs.composerInput.style.height = `${Math.min(refs.composerInput.scrollHeight, 220)}px`;
}

function updateComposerState(statusText) {
  const loggedIn = Boolean(state.user);
  const plusEnabled = state.user?.plan === "plus";
  const disabled = !loggedIn || !plusEnabled || state.sending;

  refs.composerInput.disabled = disabled;
  refs.sendButton.disabled = disabled;
  refs.sendButton.textContent = state.sending ? "处理中" : "发送";
  refs.composerInput.placeholder = plusEnabled
    ? "给 Codex Agent 发消息，例如：帮我把会员页改成 DeepSeek 风格。"
    : "当前账号不是 Plus，管理员升级后才可发送消息。";

  if (typeof statusText === "string") {
    refs.composerStatus.textContent = statusText;
    return;
  }

  refs.composerStatus.textContent = !loggedIn
    ? "登录后才可进入工作区。"
    : plusEnabled
      ? "当前账号是 Plus，可直接使用 Codex Agent。"
      : "当前账号不是 Plus，暂时不能发起 Codex Agent。";
}

async function maybeLoadAdminUsers() {
  if (!state.user || state.user.role !== "admin") {
    state.adminUsers = [];
    renderAdminUsers();
    return;
  }

  const payload = await api("/api/admin/users");
  state.adminUsers = payload.items || [];
  renderAdminUsers();
}

async function loadSessions() {
  const payload = await api("/api/chat/sessions");
  state.sessions = payload.items || [];
  if (!state.activeSessionId && state.sessions.length) {
    state.activeSessionId = state.sessions[0].session_id;
  }
  renderSessions();
  renderMessages();
}

async function openSession(sessionId) {
  const payload = await api(`/api/chat/sessions/${sessionId}`);
  const index = state.sessions.findIndex((item) => item.session_id === sessionId);
  if (index >= 0) {
    state.sessions[index] = payload;
  } else {
    state.sessions.unshift(payload);
  }
  state.activeSessionId = sessionId;
  renderSessions();
  renderMessages();
}

async function createSession() {
  const payload = await api("/api/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ title: "New chat" }),
  });

  state.sessions = state.sessions.filter((item) => item.session_id !== payload.session_id);
  state.sessions.unshift(payload);
  state.activeSessionId = payload.session_id;
  renderSessions();
  renderMessages();
  refs.composerInput.focus();
}

function upsertSession(updatedSession) {
  const index = state.sessions.findIndex((item) => item.session_id === updatedSession.session_id);
  if (index >= 0) {
    state.sessions[index] = updatedSession;
  } else {
    state.sessions.unshift(updatedSession);
  }
}

async function sendMessage(content) {
  if (state.sending) {
    return;
  }

  if (state.user?.plan !== "plus") {
    updateComposerState("当前账号不是 Plus，暂时不能发起 Codex Agent。");
    return;
  }

  if (!state.activeSessionId) {
    await createSession();
  }

  state.sending = true;
  updateComposerState("Codex Agent 正在处理这条消息。");

  try {
    const response = await fetch(`/api/chat/sessions/${state.activeSessionId}/messages`, {
      method: "POST",
      headers: {
        ...authHeaders(),
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({ content }),
    });

    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "发送失败");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";

      for (const part of parts) {
        applySseChunk(part);
      }
    }
  } catch (error) {
    updateComposerState(error.message || "发送失败");
    throw error;
  } finally {
    state.sending = false;
    updateComposerState();
  }
}

function applySseChunk(chunk) {
  const lines = chunk.split("\n");
  let eventName = "message";
  let data = "";

  for (const line of lines) {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  }

  if (!data) {
    return;
  }

  const payload = JSON.parse(data);

  if (eventName === "meta") {
    upsertSession(payload.session);
    state.activeSessionId = payload.session.session_id;
  } else if (eventName === "assistant" || eventName === "done") {
    const active = state.sessions.find((item) => item.session_id === state.activeSessionId);
    if (active) {
      const index = active.messages.findIndex((item) => item.message_id === payload.message.message_id);
      if (index >= 0) {
        active.messages[index] = payload.message;
      } else {
        active.messages.push(payload.message);
      }
      if (eventName === "done" && payload.session) {
        upsertSession(payload.session);
      }
    }
  } else if (eventName === "error") {
    const active = state.sessions.find((item) => item.session_id === state.activeSessionId);
    if (active) {
      const index = active.messages.findIndex((item) => item.message_id === payload.message.message_id);
      if (index >= 0) {
        active.messages[index] = payload.message;
      }
    }
    refs.composerStatus.textContent = payload.detail || "Codex 执行失败";
  }

  renderSessions();
  renderMessages();
}

async function bootstrap() {
  const config = await api("/api/config", { headers: {} });
  state.internalOnly = config.internal_only;
  state.allowPublicSignup = Boolean(config.allow_public_signup);
  refs.registerTab.classList.toggle("hidden", !state.allowPublicSignup);
  updateModeSummary();
  setAuthMode("login");
  updateChatLayoutMode(false);
  renderEmptyState();
  updateComposerState();
  resizeComposer();

  if (!state.token) {
    setLoginVisible(true);
    return;
  }

  try {
    const payload = await api("/api/me");
    setUser(payload.user, payload.internal_only);
    setLoginVisible(false);
    await loadSessions();
    await maybeLoadAdminUsers();
  } catch (error) {
    localStorage.removeItem("codex_chat_token");
    state.token = "";
    setLoginVisible(true);
  }
}

refs.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  refs.loginMessage.textContent = "";

  try {
    const endpoint = state.authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const body = {
      email: refs.emailInput.value.trim(),
      password: refs.passwordInput.value,
    };

    if (state.authMode === "register") {
      body.name = refs.nameInput.value.trim();
    }

    const payload = await api(endpoint, {
      method: "POST",
      headers: {},
      body: JSON.stringify(body),
    });

    state.token = payload.token;
    localStorage.setItem("codex_chat_token", payload.token);
    state.activeSessionId = "";
    setUser(payload.user, payload.internal_only);
    setLoginVisible(false);
    await loadSessions();
    await maybeLoadAdminUsers();
  } catch (error) {
    refs.loginMessage.textContent = error.message;
  }
});

refs.loginTab.addEventListener("click", () => {
  setAuthMode("login");
});

refs.registerTab.addEventListener("click", () => {
  if (!state.allowPublicSignup) {
    return;
  }
  setAuthMode("register");
});

refs.newChatButton.addEventListener("click", async () => {
  await createSession();
});

refs.mobileNewChatButton.addEventListener("click", async () => {
  await createSession();
});

refs.mobileSidebarToggle.addEventListener("click", () => {
  refs.sessionList.scrollIntoView({ behavior: "smooth", block: "start" });
});

refs.logoutButton.addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch (error) {
    // ignore logout failure
  }

  localStorage.removeItem("codex_chat_token");
  state.token = "";
  state.user = null;
  state.sessions = [];
  state.activeSessionId = "";
  state.adminUsers = [];
  refs.composerInput.value = "";
  updateModeSummary();
  updateComposerState();
  renderSessions();
  renderMessages();
  renderAdminUsers();
  setLoginVisible(true);
  resizeComposer();
});

refs.adminUsersList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const userId = button.dataset.userId;
  const action = button.dataset.action;

  try {
    if (action === "set-plan") {
      await api(`/api/admin/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ plan: button.dataset.plan }),
      });
    } else if (action === "toggle-enabled") {
      await api(`/api/admin/users/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: button.dataset.enabled === "true" }),
      });
    }
    await maybeLoadAdminUsers();
  } catch (error) {
    refs.composerStatus.textContent = error.message;
  }
});

refs.adminPanelToggle.addEventListener("click", () => {
  refs.adminPanel.classList.toggle("admin-panel-collapsed");
});

refs.messageList.addEventListener("click", async (event) => {
  const card = event.target.closest("[data-prompt]");
  if (!card) {
    return;
  }

  refs.composerInput.value = card.dataset.prompt || "";
  resizeComposer();
  refs.composerInput.focus();
});

refs.composerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = refs.composerInput.value.trim();
  if (!content) {
    return;
  }

  refs.composerInput.value = "";
  resizeComposer();

  try {
    await sendMessage(content);
  } catch (error) {
    refs.composerInput.value = content;
    resizeComposer();
  }
});

refs.composerInput.addEventListener("input", () => {
  resizeComposer();
});

refs.composerInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey) {
    return;
  }
  event.preventDefault();
  refs.composerForm.requestSubmit();
});

bootstrap().catch((error) => {
  refs.loginMessage.textContent = error.message;
  setLoginVisible(true);
});
