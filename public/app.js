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
const neo4jDot = document.getElementById("neo4jDot");
const neo4jStatusBadge = document.getElementById("neo4jStatusBadge");
const neo4jDetails = document.getElementById("neo4jDetails");
const orderPanelBtn = document.getElementById("orderPanelBtn");
const orderPanel = document.getElementById("orderPanel");
const orderPanelToggle = document.getElementById("orderPanelToggle");
const orderList = document.getElementById("orderList");
const orderDetailsSection = document.getElementById("orderDetailsSection");
const orderDetailsContent = document.getElementById("orderDetailsContent");
const closeOrderDetails = document.getElementById("closeOrderDetails");
const reviewOverlay = document.getElementById("reviewOverlay");
const reviewModalMessage = document.getElementById("reviewModalMessage");
const reviewModalOrderId = document.getElementById("reviewModalOrderId");
const reviewModalAmount = document.getElementById("reviewModalAmount");
const reviewModalReason = document.getElementById("reviewModalReason");
const reviewApproveBtn = document.getElementById("reviewApproveBtn");
const reviewRejectBtn = document.getElementById("reviewRejectBtn");
const reviewCloseBtn = document.getElementById("reviewCloseBtn");

let isWaitingForHumanInput = false;
let panelCollapsed = false;
let orderPanelCollapsed = false;
let selectedOrder = null;
let currentReviewContext = null;
let cachedOrders = [];

// ============================================================================
// Initialization
// ============================================================================

document.addEventListener("DOMContentLoaded", () => {
  setupEventListeners();
  checkNeo4jStatus();
  renderOrderListPlaceholder();
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
  
  if (orderPanelBtn) {
    orderPanelBtn.addEventListener("click", toggleOrderPanel);
  }
  
  if (orderPanelToggle) {
    orderPanelToggle.addEventListener("click", toggleOrderPanel);
  }
  
  if (closeOrderDetails) {
    closeOrderDetails.addEventListener("click", () => {
      orderDetailsSection.style.display = "none";
      selectedOrder = null;
    });
  }

  if (reviewApproveBtn) {
    reviewApproveBtn.addEventListener("click", () => {
      if (currentReviewContext) {
        handleHumanInput("approve", currentReviewContext.orderId, currentReviewContext.returnRequestId);
      }
    });
  }

  if (reviewRejectBtn) {
    reviewRejectBtn.addEventListener("click", () => {
      if (currentReviewContext) {
        handleHumanInput("reject", currentReviewContext.orderId, currentReviewContext.returnRequestId);
      }
    });
  }

  if (reviewCloseBtn) {
    reviewCloseBtn.addEventListener("click", () => hideReviewModal(false));
  }

  if (reviewOverlay) {
    reviewOverlay.addEventListener("click", (event) => {
      if (event.target === reviewOverlay) {
        hideReviewModal(false);
      }
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && reviewOverlay && !reviewOverlay.classList.contains("hidden")) {
      hideReviewModal(false);
    }
  });
  
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
}

function showReviewModal(details = null) {
  if (!reviewOverlay) return;

  const context = details || currentReviewContext || {};
  currentReviewContext = {
    orderId: context.orderId || context.order_id || null,
    amount: context.amount ?? null,
    reason: context.reason || null,
    returnRequestId: context.returnRequestId || context.return_request_id || context.refundId || null,
    message: context.message || null
  };

  if (reviewModalMessage) {
    reviewModalMessage.textContent =
      currentReviewContext.message ||
      "A refund request requires your approval before it can be processed.";
  }

  if (reviewModalOrderId) {
    reviewModalOrderId.textContent = currentReviewContext.orderId || "—";
  }

  if (reviewModalAmount) {
    const amountValue =
      currentReviewContext.amount !== null &&
      currentReviewContext.amount !== undefined &&
      !Number.isNaN(Number(currentReviewContext.amount))
        ? `$${Number(currentReviewContext.amount).toLocaleString("en-US", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
          })}`
        : "—";

    reviewModalAmount.textContent = amountValue;
    if (amountValue !== "—") {
      reviewModalAmount.classList.add("amount");
    } else {
      reviewModalAmount.classList.remove("amount");
    }
  }

  if (reviewModalReason) {
    reviewModalReason.textContent = currentReviewContext.reason || "Customer request";
  }

  reviewOverlay.classList.remove("hidden");
  reviewOverlay.setAttribute("aria-hidden", "false");

  requestAnimationFrame(() => {
    if (reviewApproveBtn) {
      reviewApproveBtn.focus();
    }
  });
}

function hideReviewModal(resetContext = true) {
  if (!reviewOverlay) return;
  reviewOverlay.classList.add("hidden");
  reviewOverlay.setAttribute("aria-hidden", "true");
  if (resetContext) {
    currentReviewContext = null;
  }
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
  
  // Simple markdown support for **bold** and *italic*
  let html = text
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/`(.+?)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>');
  
  content.innerHTML = html;
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
  
  // Handle both object and string content
  let message, orderId, amount, reason, returnRequestId;
  
  if (typeof content === "object") {
    message = content.message || content.response || "";
    orderId = content.orderId || content.order_id;
    amount = content.amount;
    reason = content.reason;
    returnRequestId = content.returnRequestId || content.refundId;
  } else {
    message = content;
    // Try to extract order ID and amount from message text
    const orderMatch = message.match(/Order ID[:\s]+(\d+)/i);
    if (orderMatch) orderId = orderMatch[1];
    
    const amountMatch = message.match(/\$([\d,]+\.?\d*)/);
    if (amountMatch) amount = parseFloat(amountMatch[1].replace(/,/g, ''));
    
    const reasonMatch = message.match(/Reason[:\s]+(.+?)(?:\n|$)/i);
    if (reasonMatch) reason = reasonMatch[1].trim();
  }
  
  // Check if this is a refund request
  const isRefund = message.toLowerCase().includes("refund") || 
                   message.toLowerCase().includes("return") ||
                   returnRequestId;
  
  if (isRefund) {
    container.classList.add("refund-review");
    
    // Header
    const header = document.createElement("div");
    header.className = "review-header";
    header.innerHTML = '<span class="review-icon">💰</span><span class="review-title">Refund Request Pending Approval</span>';
    container.appendChild(header);
    
    // Details card
    const detailsCard = document.createElement("div");
    detailsCard.className = "review-details-card";
    
    if (orderId) {
      const orderRow = document.createElement("div");
      orderRow.className = "review-detail-row";
      orderRow.innerHTML = `<span class="detail-label">Order ID:</span><span class="detail-value">${orderId}</span>`;
      detailsCard.appendChild(orderRow);
    }
    
    if (amount !== undefined && amount !== null) {
      const amountRow = document.createElement("div");
      amountRow.className = "review-detail-row";
      amountRow.innerHTML = `<span class="detail-label">Amount:</span><span class="detail-value amount">$${amount.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>`;
      detailsCard.appendChild(amountRow);
    }
    
    if (reason) {
      const reasonRow = document.createElement("div");
      reasonRow.className = "review-detail-row";
      reasonRow.innerHTML = `<span class="detail-label">Reason:</span><span class="detail-value">${reason}</span>`;
      detailsCard.appendChild(reasonRow);
    }
    
    container.appendChild(detailsCard);
    
    // Message text
    if (message && !message.includes("Order ID:") && !message.includes("Amount:")) {
      const text = document.createElement("div");
      text.className = "review-text";
      text.textContent = message;
      container.appendChild(text);
    }
  } else {
    // Generic review content
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
  }
  
  // Action buttons
  const actions = document.createElement("div");
  actions.className = "review-actions";
  
  const approveBtn = document.createElement("button");
  approveBtn.className = "review-btn approve";
  approveBtn.innerHTML = '<span class="btn-icon">✓</span><span class="btn-text">Approve</span>';
  approveBtn.onclick = () => handleHumanInput("approve", orderId, returnRequestId);
  
  const rejectBtn = document.createElement("button");
  rejectBtn.className = "review-btn reject";
  rejectBtn.innerHTML = '<span class="btn-icon">✗</span><span class="btn-text">Reject</span>';
  rejectBtn.onclick = () => handleHumanInput("reject", orderId, returnRequestId);
  
  actions.appendChild(approveBtn);
  actions.appendChild(rejectBtn);
  container.appendChild(actions);

  if (isRefund) {
    const modalDetails = {
      message,
      orderId,
      amount,
      reason,
      returnRequestId
    };
    queueMicrotask(() => showReviewModal(modalDetails));
  }
  
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
  if (!message) return;
  
  // Allow sending approve/reject messages even when waiting for human input
  const isApprovalMessage = /^(approve|reject|yes|no|y|n|cancel)$/i.test(message);
  if (isWaitingForHumanInput) {
    if (isApprovalMessage) {
      hideReviewModal();
    } else {
      if (currentReviewContext) {
        showReviewModal(currentReviewContext);
      }
      // Show hint to user
      const hint = document.createElement("div");
      hint.className = "approval-hint";
      hint.textContent = "Please use the Approve/Reject buttons above, or type 'approve' or 'reject'";
      hint.style.cssText = "color: var(--warning); padding: 8px; margin: 8px 0; font-size: 12px; background: rgba(245, 158, 11, 0.1); border-radius: 4px;";
      chat.appendChild(hint);
      setTimeout(() => hint.remove(), 3000);
      return;
    }
  }

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
    if (data.redirectUrl) {
      setTimeout(() => {
        window.location.href = data.redirectUrl;
      }, 600);
    }
    
    hideTyping();

    // Handle response rendering
    let responseDisplayed = false;
    
    // Check for refund approval request in response
    const responseText = data.response || "";
    const isRefundApprovalRequest = (
      data.needsHumanReview || 
      responseText.toLowerCase().includes("refund request pending approval") ||
      responseText.toLowerCase().includes("pending approval") ||
      responseText.toLowerCase().includes("please approve or reject")
    );
    
    if (isRefundApprovalRequest || (data.needsHumanReview && data.reviewMessage)) {
      isWaitingForHumanInput = true;
      
      // Extract refund details from response or tool result
      const toolResult = data.toolResult || {};
      const refundData = {
        message: data.reviewMessage || responseText,
        orderId: data.entities?.orderId || toolResult.orderId || toolResult.order_id,
        amount: toolResult.amount,
        reason: toolResult.reason,
        returnRequestId: toolResult.returnRequestId || toolResult.refundId || toolResult.return_request_id
      };
      
      // Try to extract from response text if not in tool result
      if (!refundData.orderId) {
        const orderMatch = responseText.match(/Order ID[:\s]+(\d+)/i);
        if (orderMatch) refundData.orderId = orderMatch[1];
      }
      
      if (!refundData.amount && responseText) {
        const amountMatch = responseText.match(/\$([\d,]+\.?\d*)/);
        if (amountMatch) refundData.amount = parseFloat(amountMatch[1].replace(/,/g, ''));
      }
      
      if (!refundData.reason && responseText) {
        const reasonMatch = responseText.match(/Reason[:\s]+(.+?)(?:\n|$)/i);
        if (reasonMatch) refundData.reason = reasonMatch[1].trim();
      }
      
      addMessage("assistant", refundData, "review");
    showReviewModal(refundData);
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
    // Only re-enable input if not waiting for human input
    if (!isWaitingForHumanInput) {
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    } else {
      // Show visual indicator that we're waiting for approval
      input.placeholder = "Waiting for approval... Type 'approve' or 'reject'";
      input.style.borderColor = "var(--warning)";
    }
  }
}

// ============================================================================
// Human Review Handling
// ============================================================================

async function handleHumanInput(decision, orderId, returnRequestId) {
  if (!isWaitingForHumanInput) return;
  
  hideReviewModal();
  isWaitingForHumanInput = false;
  
  // Reset input styling
  input.placeholder = "Ask about orders or get order information...";
  input.style.borderColor = "";
  
  // Normalize decision
  const normalizedDecision = decision.toLowerCase();
  const isApprove = normalizedDecision === "yes" || 
                    normalizedDecision === "approve" || 
                    normalizedDecision === "approved" ||
                    normalizedDecision === "y" ||
                    normalizedDecision === "confirm";
  
  const isReject = normalizedDecision === "no" || 
                   normalizedDecision === "reject" || 
                   normalizedDecision === "rejected" ||
                   normalizedDecision === "n" ||
                   normalizedDecision === "cancel";
  
  // Show user's decision
  addMessage("user", isApprove ? "✓ Approve" : isReject ? "✗ Reject" : decision);

  try {
    showTyping();
    input.disabled = true;
    sendBtn.disabled = true;

    // Send appropriate message based on decision
    const messageText = isApprove ? "approve" : isReject ? "reject" : decision;
    
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: messageText,
        channel: channelSel.value,
        conversationId: "demo",
        humanInput: messageText
      })
    });

    if (!res.ok) {
      const errorData = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
      throw new Error(errorData.detail || `Server error: ${res.status}`);
    }

    const data = await res.json();
    hideTyping();

    if (data.response) {
      const type = channelSel.value === "email" ? "email" : "text";
      addMessage("assistant", data.response, type);
    } else {
      // Fallback message
      const fallbackMessage = isApprove 
        ? `✅ Refund request for order ${orderId || 'the order'} has been approved and is being processed.`
        : `❌ Refund request for order ${orderId || 'the order'} has been rejected.`;
      addMessage("assistant", fallbackMessage, "text");
    }
  } catch (e) {
    hideTyping();
    console.error("Error handling human input:", e);
    addMessage("assistant", `⚠️ Error: ${e.message}`, "error");
  } finally {
    input.disabled = false;
    sendBtn.disabled = false;
    input.focus();
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
// Order Management Panel
// ============================================================================

function toggleOrderPanel() {
  orderPanelCollapsed = !orderPanelCollapsed;
  if (orderPanel) {
    if (orderPanelCollapsed) {
      orderPanel.classList.add("collapsed");
      if (orderPanelToggle) orderPanelToggle.textContent = "☰";
    } else {
      orderPanel.classList.remove("collapsed");
      if (orderPanelToggle) orderPanelToggle.textContent = "✕";
      renderOrderListPlaceholder();
    }
  }
}

function renderOrderListPlaceholder() {
  if (!orderList) return;
  
  orderList.innerHTML = `
    <div class="order-empty-state">
      <div class="empty-icon">📭</div>
      <h4>No order selected</h4>
      <p>Ask about an order in the conversation to view its details here.</p>
    </div>
  `;
}

async function loadOrders(searchQuery = "") {
  if (!orderList) return;
  
  orderList.innerHTML = `<div class="loading-orders">Loading latest orders...</div>`;
  
  try {
    const res = await fetch("/api/orders");
    if (!res.ok) {
      throw new Error(`Failed to load orders: ${res.status}`);
    }
    
    const data = await res.json();
    const orders = data.orders || [];
    
    // Filter orders if search query provided
    let filteredOrders = orders;
    filteredOrders = orders;

    cachedOrders = filteredOrders;
    
    if (filteredOrders.length === 0) {
      renderOrderListPlaceholder();
      return;
    }
    
    orderList.innerHTML = "";
    filteredOrders.forEach(order => {
      const orderItem = document.createElement("div");
      orderItem.className = "order-item";
      orderItem.innerHTML = `
        <div class="order-item-header">
          <span class="order-id">Order #${order.orderId}</span>
          <span class="order-status status-${order.status?.toLowerCase() || 'unknown'}">${order.status || 'Unknown'}</span>
        </div>
        <div class="order-item-details">
          <div class="order-detail-row">
            <span class="detail-label">Customer:</span>
            <span class="detail-value">${order.customerName || 'N/A'}</span>
          </div>
          <div class="order-detail-row">
            <span class="detail-label">Amount:</span>
            <span class="detail-value">$${order.totalAmount?.toFixed(2) || '0.00'}</span>
          </div>
          ${order.orderDate ? `<div class="order-detail-row">
            <span class="detail-label">Date:</span>
            <span class="detail-value">${new Date(order.orderDate).toLocaleDateString()}</span>
          </div>` : ''}
        </div>
      `;
      orderItem.addEventListener("click", () => selectOrder(order.orderId));
      orderList.appendChild(orderItem);
    });
  } catch (e) {
    console.error("Error loading orders:", e);
    const errorMsg = e.message || "Unknown error";
    orderList.innerHTML = `
      <div class="error-orders">
        <div style="margin-bottom: 8px;">Error loading orders: ${errorMsg}</div>
        <div style="font-size: 11px; color: var(--text-muted); margin-top: 8px;">
          Make sure Neo4j is running and order data has been loaded.
        </div>
      </div>
    `;
  }
}

async function selectOrder(orderId) {
  selectedOrder = orderId;
  
  try {
    let order = cachedOrders.find(o => o.orderId === orderId);
    
    if (!order) {
      // Fallback: fetch the latest list to locate the order without rendering all orders
      const resOrders = await fetch("/api/orders");
      const data = await resOrders.json();
      order = (data.orders || []).find(o => o.orderId === orderId);
    }

    if (!order) {
      throw new Error("Order not found");
    }

    // Fetch full order details
    const res = await fetch(`/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: `Get full details for order ${orderId}`,
        channel: "chat",
        conversationId: "order-details"
      })
    });
    
    if (!res.ok) {
      throw new Error(`Failed to get order details: ${res.status}`);
    }
    
    const data = await res.json();

    // Display order details
    displayOrderDetails(order, data);
    
  } catch (e) {
    console.error("Error selecting order:", e);
    alert(`Error loading order details: ${e.message}`);
  }
}

function displayOrderDetails(order, chatData) {
  if (!orderDetailsContent || !orderDetailsSection) return;
  
  const toolResult = chatData.toolResult || {};
  const items = toolResult.items || [];
  
  orderDetailsContent.innerHTML = `
    <div class="order-detail-card">
      <div class="detail-section">
        <h5>Order Information</h5>
        <div class="detail-grid">
          <div class="detail-item">
            <span class="detail-label">Order ID:</span>
            <span class="detail-value">${order.orderId}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Status:</span>
            <span class="detail-value status-badge status-${order.status?.toLowerCase() || 'unknown'}">${order.status || 'Unknown'}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Tracking Number:</span>
            <span class="detail-value">${order.tracking || 'N/A'}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Price:</span>
            <span class="detail-value price">$${order.totalAmount?.toFixed(2) || '0.00'}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Order Date:</span>
            <span class="detail-value">${order.orderDate ? new Date(order.orderDate).toLocaleDateString() : 'N/A'}</span>
          </div>
          <div class="detail-item">
            <span class="detail-label">Expected Delivery:</span>
            <span class="detail-value">${order.expectedDelivery ? new Date(order.expectedDelivery).toLocaleDateString() : 'N/A'}</span>
          </div>
        </div>
      </div>
      
      ${items.length > 0 ? `
      <div class="detail-section">
        <h5>Order Items</h5>
        <div class="items-list">
          ${items.map(item => `
            <div class="item-row">
              <span class="item-name">${item.name || 'N/A'}</span>
              <span class="item-quantity">Qty: ${item.quantity || 0}</span>
              <span class="item-price">$${item.price?.toFixed(2) || '0.00'}</span>
            </div>
          `).join('')}
        </div>
      </div>
      ` : ''}
      
      <div class="detail-actions">
        <button class="action-btn return-btn" id="returnOrderBtn" onclick="initiateReturn('${order.orderId}')">
          <span class="btn-icon">↩️</span>
          <span class="btn-label">Return Order</span>
        </button>
        <button class="action-btn chat-btn" onclick="askAboutOrder('${order.orderId}')">
          <span class="btn-icon">💬</span>
          <span class="btn-label">Ask Chat Assistant</span>
        </button>
      </div>
    </div>
  `;
  
  orderDetailsSection.style.display = "block";
}

async function initiateReturn(orderId) {
  if (!orderId) return;
  
  // Use the chat API to initiate return (which will trigger human-in-the-loop)
  const message = `I want to return order ${orderId}`;
  input.value = message;
  send();
  
  // Close order details panel
  if (orderDetailsSection) {
    orderDetailsSection.style.display = "none";
  }
}

function askAboutOrder(orderId) {
  if (!orderId) return;
  
  // Focus on chat input and pre-fill with order query
  input.value = `Tell me about order ${orderId}`;
  input.focus();
  
  // Close order details panel
  if (orderDetailsSection) {
    orderDetailsSection.style.display = "none";
  }
}

// Make functions globally available
window.initiateReturn = initiateReturn;
window.askAboutOrder = askAboutOrder;

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

