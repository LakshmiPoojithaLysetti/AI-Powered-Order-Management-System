// ============================================================================
// UI Components & State
// ============================================================================

const chat = document.getElementById("chat");
const input = document.getElementById("msg");
const sendBtn = document.getElementById("send");
const channelSel = document.getElementById("channel");
const clearBtn = document.getElementById("clearBtn");
const emptyState = document.getElementById("emptyState");
const settingsBtn = document.getElementById("settingsBtn");
const systemPanel = document.getElementById("systemPanel");
const panelToggle = document.getElementById("panelToggle");
const loadDataBtn = document.getElementById("loadDataBtn");
const clearDataBtn = document.getElementById("clearDataBtn");
const loadingStatus = document.getElementById("loadingStatus");
const neo4jDot = document.getElementById("neo4jDot");
const neo4jStatusBadge = document.getElementById("neo4jStatusBadge");
const neo4jDetails = document.getElementById("neo4jDetails");

let isWaitingForHumanInput = false;
let panelCollapsed = false;

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  checkNeo4jStatus();
  // Check status every 30 seconds
  setInterval(checkNeo4jStatus, 30000);
});

function setupEventListeners() {
  sendBtn.addEventListener("click", send);
  clearBtn.addEventListener("click", clearChat);
  
  if (settingsBtn) {
    settingsBtn.addEventListener("click", togglePanel);
  }
  
  if (panelToggle) {
    panelToggle.addEventListener("click", togglePanel);
  }
  
  if (loadDataBtn) {
    loadDataBtn.addEventListener("click", () => loadNeo4jData(false));
  }
  
  if (clearDataBtn) {
    clearDataBtn.addEventListener("click", () => loadNeo4jData(true));
  }
  
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });

  document.querySelectorAll(".quick-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const action = btn.dataset.action;
      handleQuickAction(action);
    });
  });
}

// ============================================================================
// Message Rendering
// ============================================================================

function addMessage(role, content, type = "text", metadata = null) {
  // Clear empty state
  if (emptyState && emptyState.parentNode) {
    emptyState.remove();
  }
  
  const message = renderMessage(role, content, type, metadata);
  chat.appendChild(message);
  chat.scrollTop = chat.scrollHeight;
}

function renderMessage(role, content, type = "text", metadata = null) {
  const item = document.createElement("div");
  item.className = `message ${role}`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "U" : "A";

  const bubble = document.createElement("div");
  bubble.className = `bubble ${type}`;

  if (type === "email") {
    bubble.appendChild(renderEmailContent(content));
  } else if (type === "table") {
    bubble.appendChild(renderTableContent(content));
  } else if (type === "review") {
    bubble.appendChild(renderReviewContent(content));
  } else if (type === "error") {
    bubble.appendChild(renderErrorContent(content));
  } else {
    bubble.appendChild(renderTextContent(content));
  }

  item.appendChild(avatar);
  item.appendChild(bubble);

  if (metadata) {
    const meta = document.createElement("div");
    meta.className = "metadata";
    meta.textContent = metadata;
    item.appendChild(meta);
  }

  return item;
}

function renderTextContent(text) {
  const content = document.createElement("div");
  content.className = "text-content";
  content.textContent = text;
  return content;
}

function renderEmailContent(emailText) {
  const container = document.createElement("div");
  container.className = "email-content";
  
  const lines = emailText.split("\n\n");
  const subject = lines[0]?.replace("Subject:", "").trim() || "Regarding your request";
  const body = lines.slice(1).join("\n\n") || emailText;

  const subjectEl = document.createElement("div");
  subjectEl.className = "email-subject";
  subjectEl.textContent = subject;

  const bodyEl = document.createElement("div");
  bodyEl.className = "email-body";
  bodyEl.textContent = body;

  container.appendChild(subjectEl);
  container.appendChild(bodyEl);
  return container;
}

function renderTableContent(queryJson) {
  const container = document.createElement("div");
  container.className = "table-content";
  
  try {
    const query = typeof queryJson === "string" ? JSON.parse(queryJson) : queryJson;
    
    if (query.type === "Part" && query.propertiesFilter) {
      const table = document.createElement("table");
      table.className = "results-table";
      
      const thead = document.createElement("thead");
      thead.innerHTML = "<tr><th>Property</th><th>Value</th></tr>";
      table.appendChild(thead);
      
      const tbody = document.createElement("tbody");
      const expressions = query.propertiesFilter.expressions || [];
      
      expressions.forEach(expr => {
        const row = document.createElement("tr");
        row.innerHTML = `
          <td>${expr.property || "N/A"}</td>
          <td>${expr.value || "N/A"}</td>
        `;
        tbody.appendChild(row);
      });
      
      table.appendChild(tbody);
      container.appendChild(table);
    } else {
      container.innerHTML = `<pre>${JSON.stringify(query, null, 2)}</pre>`;
    }
  } catch (e) {
    container.innerHTML = `<div class="error-text">Failed to parse query: ${e.message}</div>`;
  }
  
  return container;
}

function renderReviewContent(content) {
  const container = document.createElement("div");
  container.className = "review-content";
  
  const message = typeof content === "object" ? content.message : content;
  const orderId = typeof content === "object" ? content.orderId : null;
  
  const text = document.createElement("div");
  text.className = "review-text";
  text.textContent = message;
  container.appendChild(text);
  
  if (orderId) {
    const orderInfo = document.createElement("div");
    orderInfo.className = "review-order-id";
    orderInfo.textContent = `Order ID: ${orderId}`;
    container.appendChild(orderInfo);
  }
  
  const actions = document.createElement("div");
  actions.className = "review-actions";
  
  const approveBtn = document.createElement("button");
  approveBtn.className = "review-btn approve";
  approveBtn.textContent = "✓ Approve";
  approveBtn.onclick = () => handleHumanInput("yes", orderId);
  
  const rejectBtn = document.createElement("button");
  rejectBtn.className = "review-btn reject";
  rejectBtn.textContent = "✗ Reject";
  rejectBtn.onclick = () => handleHumanInput("no", orderId);
  
  actions.appendChild(approveBtn);
  actions.appendChild(rejectBtn);
  container.appendChild(actions);
  
  return container;
}

function renderErrorContent(error) {
  const content = document.createElement("div");
  content.className = "error-content";
  content.textContent = error;
  return content;
}

// ============================================================================
// Typing Indicator
// ============================================================================

let typingEl = null;

function showTyping() {
  if (typingEl) return;
  typingEl = document.createElement("div");
  typingEl.className = "message assistant typing";
  typingEl.innerHTML = `
    <div class="avatar">A</div>
    <div class="bubble typing">
      <div class="typing-indicator">
        <span></span><span></span><span></span>
      </div>
    </div>
  `;
  chat.appendChild(typingEl);
  chat.scrollTop = chat.scrollHeight;
}

function hideTyping() {
  if (typingEl) {
    typingEl.remove();
    typingEl = null;
  }
}

// ============================================================================
// API Communication
// ============================================================================

async function send() {
  const message = input.value.trim();
  if (!message || isWaitingForHumanInput) return;

  addMessage("user", message);
  input.value = "";
  input.disabled = true;
  sendBtn.disabled = true;

  try {
    showTyping();

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        channel: channelSel.value,
        conversationId: "demo"
      })
    });

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(errorData.detail || `Server error: ${res.status}`);
    }

    const data = await res.json();
    console.log("API Response:", data);
    
    hideTyping();

    // Handle response rendering
    let responseDisplayed = false;
    
    if (data.needsHumanReview && data.reviewMessage) {
      isWaitingForHumanInput = true;
      addMessage("assistant", {
        message: data.reviewMessage,
        orderId: data.entities?.orderId
      }, "review");
      responseDisplayed = true;
    } else if (data.parsed_query) {
      addMessage("assistant", data.parsed_query, "table");
      responseDisplayed = true;
    } else if (data.response) {
      const type = channelSel.value === "email" ? "email" : "text";
      addMessage("assistant", data.response, type);
      responseDisplayed = true;
    }
    
    if (!responseDisplayed) {
      console.warn("No response to display. Data received:", data);
      addMessage("assistant", "I received your message but couldn't generate a response. Please try again.", "error");
    }

    // Add metadata
    const metaParts = [];
    if (data.intent) metaParts.push(`intent: ${data.intent}`);
    if (data.entities && Object.keys(data.entities).length > 0) {
      metaParts.push(`entities: ${JSON.stringify(data.entities)}`);
    }
    if (data.isFastenerSearch) metaParts.push("workflow: fastener_search");
    if (metaParts.length > 0) {
      const meta = document.createElement("div");
      meta.className = "metadata";
      meta.textContent = metaParts.join(" | ");
      chat.appendChild(meta);
      chat.scrollTop = chat.scrollHeight;
    }

  } catch (e) {
    hideTyping();
    console.error("Error:", e);
    addMessage("assistant", `⚠️ Error: ${e.message}`, "error");
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
  }
}

// ============================================================================
// Human Review Handling
// ============================================================================

async function handleHumanInput(decision, orderId) {
  if (!isWaitingForHumanInput) return;
  
  isWaitingForHumanInput = false;
  addMessage("user", decision === "yes" ? "Approve" : "Reject");

  try {
    showTyping();

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: decision === "yes" ? "Approved" : "Rejected",
        channel: channelSel.value,
        conversationId: "demo",
        humanInput: decision
      })
    });

    const data = await res.json();
    hideTyping();

    if (data.response) {
      const type = channelSel.value === "email" ? "email" : "text";
      addMessage("assistant", data.response, type);
    }
  } catch (e) {
    hideTyping();
    addMessage("assistant", `⚠️ Error: ${e.message}`, "error");
  }
}

// ============================================================================
// Quick Actions
// ============================================================================

function handleQuickAction(action) {
  const prompts = {
    order: "Check order status for order 12345",
    track: "Track order 12345",
    fastener: "Show me PEM self-clinching standoffs",
    policy: "What is your return policy?"
  };

  const prompt = prompts[action];
  if (prompt) {
    input.value = prompt;
    send();
  }
}

// ============================================================================
// UI Utilities
// ============================================================================

function clearChat() {
  chat.innerHTML = "";
  if (emptyState) {
    chat.appendChild(emptyState);
  }
  isWaitingForHumanInput = false;
}

// ============================================================================
// System Management Panel
// ============================================================================

function togglePanel() {
  panelCollapsed = !panelCollapsed;
  if (systemPanel) {
    if (panelCollapsed) {
      systemPanel.classList.add("collapsed");
      if (panelToggle) panelToggle.textContent = "☰";
    } else {
      systemPanel.classList.remove("collapsed");
      if (panelToggle) panelToggle.textContent = "✕";
    }
  }
}

async function checkNeo4jStatus() {
  try {
    const res = await fetch("/api/neo4j/status");
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({ message: `HTTP ${res.status}` }));
      throw new Error(errorData.message || `Status check failed: ${res.status}`);
    }
    
    const data = await res.json();
    updateNeo4jStatus(data.connected, data.message || "Connected");
  } catch (e) {
    console.error("Neo4j status check error:", e);
    updateNeo4jStatus(false, e.message || "Connection check failed");
  }
}

function updateNeo4jStatus(connected, message) {
  if (neo4jDot) {
    neo4jDot.className = `status-dot ${connected ? "connected" : "disconnected"}`;
  }
  
  if (neo4jStatusBadge) {
    neo4jStatusBadge.className = `status-badge ${connected ? "connected" : "disconnected"}`;
    neo4jStatusBadge.textContent = connected ? "Connected" : "Disconnected";
  }
  
  if (neo4jDetails) {
    neo4jDetails.innerHTML = `<p>${message}</p>`;
  }
}

async function loadNeo4jData(clearExisting = false) {
  if (loadDataBtn) loadDataBtn.disabled = true;
  if (clearDataBtn) clearDataBtn.disabled = true;
  
  if (loadingStatus) {
    loadingStatus.style.display = "block";
  }
  
  try {
    const res = await fetch("/api/neo4j/load-data", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clearExisting })
    });
    
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(errorData.detail || `Server error: ${res.status}`);
    }
    
    const data = await res.json();
    
    // Show success message
    if (loadingStatus) {
      loadingStatus.innerHTML = `
        <div style="color: var(--secondary); margin-bottom: 12px;">✓ Success!</div>
        <p style="font-size: 12px; color: var(--text-muted);">
          Executed ${data.statements_executed || 0} statements
        </p>
      `;
      
      setTimeout(() => {
        loadingStatus.style.display = "none";
      }, 3000);
    }
    
    // Update status
    await checkNeo4jStatus();
    
    // Show notification in chat
    addMessage("assistant", `✅ Data loaded successfully! ${data.statements_executed || 0} statements executed.`, "text");
    
  } catch (e) {
    console.error("Error loading data:", e);
    if (loadingStatus) {
      loadingStatus.innerHTML = `
        <div style="color: var(--danger); margin-bottom: 12px;">✗ Error</div>
        <p style="font-size: 12px; color: var(--text-muted);">
          ${e.message}
        </p>
      `;
    }
    addMessage("assistant", `⚠️ Error loading data: ${e.message}`, "error");
  } finally {
    if (loadDataBtn) loadDataBtn.disabled = false;
    if (clearDataBtn) clearDataBtn.disabled = false;
  }
}
