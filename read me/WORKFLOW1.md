# Workflow Diagram & Data Flow - Order 12345

This document explains the complete data flow through the `workflow.json` orchestration, using **Order 12345** as a real example for tracking and status queries.

## Table of Contents

- [Overview](#overview)
- [Order 12345 Details](#order-12345-details)
- [Workflow Activities](#workflow-activities)
- [Scenario 1: Order Status Query](#scenario-1-order-status-query)
- [Scenario 2: Order Price Query](#scenario-2-order-price-query)
- [Scenario 3: Track Order Query](#scenario-3-track-order-query)
- [Scenario 4: Refund Request (Ineligible)](#scenario-4-refund-request-ineligible)
- [Activity Performance](#activity-performance)
- [Comparison with Order 11111](#comparison-with-order-11111)

## Overview

Order 12345 demonstrates **non-HITL workflows** where the system can provide immediate responses without human approval. Unlike Order 11111 (which requires HITL for refunds), Order 12345 is currently **Shipped** and not eligible for returns.

### Workflow Topology

```
┌─────────┐
│  Start  │ (1)
└────┬────┘
     │
┌────▼────────┐
│  UserTask1  │ (2) - Intake & Validation
└────┬────────┘
     │
┌────▼──────────────┐
│  RetrievalTask1   │ (3) - Fetch Context (Skip for order queries)
└────┬──────────────┘
     │
┌────▼─────────┐
│   LLMTask1   │ (4) - Intent Classification
└────┬─────────┘
     │
┌────▼─────────┐
│  ToolTask1   │ (5) - Execute Tools
└────┬─────────┘
     │
┌────▼──────────┐
│  RouterTask1  │ (6) - Route Decision
└────┬──────────┘
     │
┌────▼────────┐
│ RenderTask1 │ (7) - Format Response
└─────────────┘
     │
     ▼
    END
```

**Key Difference from Order 11111:**
- No `UserTask2` involvement (no HITL needed)
- Direct flow: Start → UserTask1 → RetrievalTask1 → LLMTask1 → ToolTask1 → RouterTask1 → RenderTask1 → END
- Faster execution (~700ms vs ~1.02s for HITL pause)

## Order 12345 Details

### Source: `data.cypher` Lines 40-75

```cypher
MERGE (order1:Order {id: "12345"})
SET order1.status = "Shipped"
SET order1.tracking = "1Z999AA10123456784"
SET order1.orderDate = date("2025-01-15")
SET order1.expectedDelivery = date("2025-01-20")
SET order1.totalAmount = 199.99
SET order1.createdAt = datetime("2025-01-15T10:30:00Z")
SET order1.updatedAt = datetime("2025-01-18T14:20:00Z")

MERGE (order1)-[:PLACED_BY]->(customer1)
MERGE (order1)-[:SHIPPED_BY]->(ups)

MERGE (item1_1:OrderItem {id: "12345-item-1", orderId: "12345"})
SET item1_1.name = "Product A"
SET item1_1.quantity = 2
SET item1_1.price = 99.99

MERGE (order1)-[:HAS_ITEM]->(item1_1)

// Tracking Events
MERGE (track1_1:TrackingEvent {orderId: "12345", date: datetime("2025-01-15T10:30:00Z")})
SET track1_1.location = "Warehouse"
SET track1_1.status = "Order Placed"

MERGE (track1_2:TrackingEvent {orderId: "12345", date: datetime("2025-01-16T08:15:00Z")})
SET track1_2.location = "Distribution Center"
SET track1_2.status = "Shipped"

MERGE (track1_3:TrackingEvent {orderId: "12345", date: datetime("2025-01-17T12:30:00Z")})
SET track1_3.location = "Chicago, IL"
SET track1_3.status = "In Transit"

MERGE (order1)-[:HAS_TRACKING]->(track1_1)
MERGE (order1)-[:HAS_TRACKING]->(track1_2)
MERGE (order1)-[:HAS_TRACKING]->(track1_3)
```

### Order Properties

| Property | Value |
|----------|-------|
| Order ID | 12345 |
| Status | Shipped |
| Carrier | UPS |
| Tracking # | 1Z999AA10123456784 |
| Order Date | 2025-01-15 |
| Expected Delivery | 2025-01-20 |
| Actual Delivery | Not yet delivered |
| Total Amount | $199.99 |
| Items | Product A (2 × $99.99) |
| Customer | Customer 1 (John Smith) |

### Tracking History

| Date | Location | Status |
|------|----------|--------|
| 2025-01-15 10:30 | Warehouse | Order Placed |
| 2025-01-16 08:15 | Distribution Center | Shipped |
| 2025-01-17 12:30 | Chicago, IL | In Transit |

### Eligibility for Return

- ❌ Status: Shipped (not Delivered)
- ❌ Cannot return until delivered
- ✅ Order Date: Within 300-day window (once delivered)

## Workflow Activities

### Activity Mapping (Same as Order 11111)

| ID | Name | Type | Handler Function | Usage for Order 12345 |
|----|------|------|------------------|-----------------------|
| 1 | Start | Start | `start_node` | ✅ Entry point |
| 2 | UserTask1 | UserTaskActivity | `user_task_node` | ✅ Extract orderId |
| 3 | RetrievalTask1 | RetrievalTaskActivity | `retrieval_task_node` | ⚠️ Skipped (no policy query) |
| 4 | LLMTask1 | LLMTaskActivity | `llm_task_node` | ✅ Classify intent |
| 5 | ToolTask1 | ToolTaskActivity | `tool_task_node` | ✅ Execute status/price/track tools |
| 6 | RouterTask1 | RouterTaskActivity | `router_task_node` | ✅ Route to RenderTask1 |
| 7 | RenderTask1 | RenderTaskActivity | `render_task_node` | ✅ Format response |
| 8 | AgentTask1 | AgentTaskActivity | `agent_task_node` | ❌ Not used |
| 9 | UserTask2 | UserTaskActivity | `user_task2_node` | ❌ Not used (no HITL) |

---

## Scenario 1: Order Status Query

### User Input: `"check order 12345"`

This is the most common query type - checking the current status of an order.

---

### Step 1: Start (Activity 1)

**Input:**
```json
{
  "message": "check order 12345",
  "channel": "chat",
  "conversationId": "user-session-456"
}
```

**Processing:**
- HTTP POST to `/api/chat`
- Initialize GraphState

**State:**
```python
{
  "messages": [HumanMessage(content="check order 12345")],
  "input": "check order 12345",
  "channel": "chat",
  "intent": None,
  "entities": {},
  "needs_human_review": False
}
```

**Output:** → UserTask1

---

### Step 2: UserTask1 (Activity 2)

**Purpose:** Entity Extraction

**Processing:**
```python
# graph.py - user_task_node()
input_text = "check order 12345"

# Extract order ID using regex
order_id_pattern = r'\b(\d{5})\b'
matches = re.findall(order_id_pattern, input_text)
# matches = ["12345"]

entities = {"orderId": "12345"}
```

**State Update:**
```python
state["entities"] = {"orderId": "12345"}
```

**Output:** → RetrievalTask1

---

### Step 3: RetrievalTask1 (Activity 3)

**Purpose:** Fetch Documents (Conditional)

**Processing:**
```python
# graph.py - retrieval_task_node()
input_text = "check order 12345"
keywords = ["policy", "return", "warranty", "shipping"]

# Check if retrieval needed
needs_retrieval = any(kw in input_text.lower() for kw in keywords)
# needs_retrieval = False (no policy keywords)

# Skip retrieval
state["retrieved"] = []
```

**State Update:**
```python
state["retrieved"] = []  # Empty, no documents fetched
```

**Output:** → LLMTask1

---

### Step 4: LLMTask1 (Activity 4)

**Purpose:** Intent Classification

**Processing:**
```python
# graph.py - llm_task_node()
# First, use keyword-based classification (faster)
from graph import classify_intent

intent = classify_intent("check order 12345", {"orderId": "12345"})
# Returns: "order_status"
```

**Intent Classification Logic:**
```python
def classify_intent(text: str, entities: Dict) -> str:
    text_lower = text.lower()
    order_id = entities.get("orderId")
    
    # Status queries
    if re.search(r'\b(status|check|what.*status|how.*order|carrier|shipper)\b', text_lower) and order_id:
        return "order_status"
    
    # Returns: "order_status"
```

**State Update:**
```python
state["intent"] = "order_status"
```

**Output:** → ToolTask1

---

### Step 5: ToolTask1 (Activity 5)

**Purpose:** Execute Order Status Tool

**Processing:**
```python
# graph.py - tool_task_node()
intent = "order_status"
order_id = "12345"

# Execute tool
import asyncio
from tools.order_tools import lookup_order_status

tool_result = asyncio.run(lookup_order_status("12345"))
```

**Inside `lookup_order_status()` (tools/order_tools.py):**

```python
async def lookup_order_status(order_id: str) -> Optional[Dict[str, Any]]:
    # Get order from Neo4j
    order = await _get_order_from_neo4j("12345")
    
    # Returns order details
    return order
```

**Neo4j Query:**
```cypher
MATCH (o:Order {id: $order_id})
OPTIONAL MATCH (o)-[:SHIPPED_BY]->(carrier:Carrier)
OPTIONAL MATCH (o)-[:HAS_ITEM]->(item:OrderItem)
RETURN 
  o.id AS id,
  o.status AS status,
  o.tracking AS tracking,
  o.expectedDelivery AS expectedDelivery,
  o.orderDate AS orderDate,
  o.totalAmount AS totalAmount,
  carrier.name AS carrier_name,
  collect({
    name: item.name,
    quantity: item.quantity,
    price: item.price
  }) AS items
```

**Query Result:**
```python
{
  "id": "12345",
  "status": "Shipped",
  "carrier": "UPS",
  "tracking": "1Z999AA10123456784",
  "expectedDelivery": "2025-01-20",
  "orderDate": "2025-01-15",
  "totalAmount": 199.99,
  "items": [
    {
      "name": "Product A",
      "quantity": 2,
      "price": 99.99
    }
  ],
  "customerId": "cust1",
  "customerName": "John Smith"
}
```

**State Update:**
```python
state["tool_result"] = {
  "id": "12345",
  "status": "Shipped",
  "carrier": "UPS",
  "tracking": "1Z999AA10123456784",
  "expectedDelivery": "2025-01-20",
  "totalAmount": 199.99,
  "items": [{"name": "Product A", "quantity": 2, "price": 99.99}]
}
```

**Output:** → RouterTask1

---

### Step 6: RouterTask1 (Activity 6)

**Purpose:** Route to Render

**Processing:**
```python
# graph.py - router_task_node()
intent = "order_status"
needs_review = False
tool_result = state["tool_result"]

# Routing logic
if needs_review:
    state["current_activity"] = "UserTask2"
elif intent in ["order_status", "order_price", "track_order", "policy_question", "chit_chat"]:
    state["current_activity"] = "RenderTask1"
else:
    state["current_activity"] = "RenderTask1"

# Route to RenderTask1
```

**State Update:**
```python
state["current_activity"] = "RenderTask1"
```

**Output:** → RenderTask1

---

### Step 7: RenderTask1 (Activity 7)

**Purpose:** Format Response

**Processing:**
```python
# graph.py - render_task_node()
intent = "order_status"
tool_result = state["tool_result"]

# Format order status response
status = tool_result.get("status", "Unknown")  # "Shipped"
order_id = tool_result.get("id")  # "12345"
items = tool_result.get("items", [])  # [{"name": "Product A", ...}]
total = tool_result.get("totalAmount", 0)  # 199.99
carrier = tool_result.get("carrier")  # "UPS"

response = f"Order {order_id} is currently **{status}**."
if carrier:
    response += f" It is being handled by **{carrier}**."
if items:
    response += f" Order contains {len(items)} item(s)."
if total:
    response += f" Total amount: ${float(total):,.2f}"

# Final response:
# "Order 12345 is currently **Shipped**. It is being handled by **UPS**. Order contains 1 item(s). Total amount: $199.99"
```

**State Update:**
```python
state["response"] = "Order 12345 is currently **Shipped**. It is being handled by **UPS**. Order contains 1 item(s). Total amount: $199.99"
```

**Output:** → END

---

### Step 8: Final Response

**API Response:**
```json
{
  "conversationId": "user-session-456",
  "response": "Order 12345 is currently **Shipped**. It is being handled by **UPS**. Order contains 1 item(s). Total amount: $199.99",
  "intent": "order_status",
  "entities": {"orderId": "12345"},
  "toolResult": {
    "id": "12345",
    "status": "Shipped",
    "carrier": "UPS",
    "tracking": "1Z999AA10123456784",
    "expectedDelivery": "2025-01-20",
    "totalAmount": 199.99,
    "items": [{"name": "Product A", "quantity": 2, "price": 99.99}]
  },
  "needsHumanReview": false,
  "redirectUrl": null
}
```

**Frontend Display:**
```
🤖 Order 12345 is currently Shipped. It is being handled by UPS. 
   Order contains 1 item(s). Total amount: $199.99
```

**Execution Time:** ~700ms (no HITL delay)

---

## Scenario 2: Order Price Query

### User Input: `"price of order 12345"` or `"how much is order 12345"`

---

### Quick Flow Summary:

1. **Start** → Initialize state
2. **UserTask1** → Extract `orderId = "12345"`
3. **RetrievalTask1** → Skip (no policy keywords)
4. **LLMTask1** → Classify `intent = "order_price"`
5. **ToolTask1** → Execute `get_order_price("12345")`
6. **RouterTask1** → Route to RenderTask1
7. **RenderTask1** → Format price breakdown
8. **END**

---

### Step 5: ToolTask1 (Price Query)

**Processing:**
```python
# graph.py - tool_task_node()
intent = "order_price"
order_id = "12345"

from tools.order_tools import get_order_price
tool_result = asyncio.run(get_order_price("12345"))
```

**Inside `get_order_price()` (tools/order_tools.py):**

```python
async def get_order_price(order_id: str) -> Optional[Dict[str, Any]]:
    # Call Neo4j function
    from neo4j_module import get_order_price as neo4j_get_order_price
    
    pricing = await neo4j_get_order_price("12345")
    return pricing
```

**Neo4j Query:**
```cypher
MATCH (o:Order {id: $order_id})
OPTIONAL MATCH (o)-[:HAS_ITEM]->(item:OrderItem)
RETURN 
  o.id AS orderId,
  o.totalAmount AS totalAmount,
  collect({
    name: item.name,
    quantity: item.quantity,
    price: item.price
  }) AS items
```

**Tool Result:**
```python
{
  "orderId": "12345",
  "totalAmount": 199.99,
  "items": [
    {
      "name": "Product A",
      "quantity": 2,
      "price": 99.99
    }
  ]
}
```

---

### Step 7: RenderTask1 (Price Response)

**Processing:**
```python
# graph.py - render_task_node()
intent = "order_price"
tool_result = state["tool_result"]

order_id = tool_result.get("orderId", "unknown")  # "12345"
total = tool_result.get("totalAmount", 0)  # 199.99
items = tool_result.get("items", [])

if total and total > 0:
    response = f"The total price for order {order_id} is **${float(total):,.2f}**.\n\n"
    if items and len(items) > 0:
        response += "**Item Breakdown:**\n"
        for item in items:
            name = item.get("name", "Unknown")
            qty = item.get("quantity", 0)
            price = item.get("price", 0)
            response += f"- {name}: {qty} × ${float(price):,.2f}\n"
```

**Final Response:**
```
The total price for order 12345 is **$199.99**.

**Item Breakdown:**
- Product A: 2 × $99.99
```

**Frontend Display:**
```
🤖 The total price for order 12345 is $199.99.

   Item Breakdown:
   • Product A: 2 × $99.99
```

**Execution Time:** ~680ms

---

## Scenario 3: Track Order Query

### User Input: `"track order 12345"` or `"where is my order 12345"`

---

### Step 5: ToolTask1 (Tracking)

**Processing:**
```python
# graph.py - tool_task_node()
intent = "track_order"
order_id = "12345"

from tools.order_tools import track_order
tool_result = asyncio.run(track_order("12345"))
```

**Inside `track_order()` (tools/order_tools.py):**

```python
async def track_order(order_id: str) -> Optional[Dict[str, Any]]:
    # Get order details
    order = await _get_order_from_neo4j("12345")
    
    # Get tracking history
    async def _get_tracking_history():
        def _work(session):
            result = session.run(
                """
                MATCH (o:Order {id: $order_id})-[:HAS_TRACKING]->(t:TrackingEvent)
                RETURN t.date AS date, t.location AS location, t.status AS status
                ORDER BY t.date DESC
                LIMIT 10
                """,
                {"order_id": order_id}
            )
            history = []
            for record in result:
                history.append({
                    "date": record.get("date").isoformat(),
                    "location": record.get("location"),
                    "status": record.get("status")
                })
            return history
        
        return await async_with_session(_work)
    
    history = await _get_tracking_history()
    
    # Get current location from most recent event
    current_location = history[0].get("location") if history else "Unknown"
    
    return {
        "orderId": "12345",
        "status": "Shipped",
        "carrier": "UPS",
        "trackingNumber": "1Z999AA10123456784",
        "currentLocation": current_location,
        "estimatedDelivery": "2025-01-20",
        "lastUpdate": datetime.now().isoformat(),
        "trackingHistory": history
    }
```

**Tool Result:**
```python
{
  "orderId": "12345",
  "status": "Shipped",
  "carrier": "UPS",
  "trackingNumber": "1Z999AA10123456784",
  "currentLocation": "Chicago, IL",
  "estimatedDelivery": "2025-01-20",
  "lastUpdate": "2024-11-07T15:30:00",
  "trackingHistory": [
    {
      "date": "2025-01-17T12:30:00Z",
      "location": "Chicago, IL",
      "status": "In Transit"
    },
    {
      "date": "2025-01-16T08:15:00Z",
      "location": "Distribution Center",
      "status": "Shipped"
    },
    {
      "date": "2025-01-15T10:30:00Z",
      "location": "Warehouse",
      "status": "Order Placed"
    }
  ]
}
```

---

### Step 7: RenderTask1 (Tracking Response)

**Processing:**
```python
# graph.py - render_task_node()
intent = "track_order"
tool_result = state["tool_result"]

order_id = tool_result.get("orderId", "unknown")
status = tool_result.get("status", "Unknown")
carrier = tool_result.get("carrier")
tracking_num = tool_result.get("trackingNumber")
current_loc = tool_result.get("currentLocation", "Unknown")
estimated_delivery = tool_result.get("estimatedDelivery")
history = tool_result.get("trackingHistory", [])

response = f"**Tracking Information for Order {order_id}**\n\n"
response += f"**Status:** {status}\n"
if carrier:
    response += f"**Carrier:** {carrier}\n"
if tracking_num:
    response += f"**Tracking Number:** {tracking_num}\n"
response += f"**Current Location:** {current_loc}\n"
if estimated_delivery:
    response += f"**Estimated Delivery:** {estimated_delivery}\n\n"

if history:
    response += "**Tracking History:**\n"
    for event in history:
        date = event.get("date", "Unknown")
        location = event.get("location", "Unknown")
        event_status = event.get("status", "Unknown")
        response += f"- {date}: {event_status} at {location}\n"
```

**Final Response:**
```
**Tracking Information for Order 12345**

**Status:** Shipped
**Carrier:** UPS
**Tracking Number:** 1Z999AA10123456784
**Current Location:** Chicago, IL
**Estimated Delivery:** 2025-01-20

**Tracking History:**
- 2025-01-17T12:30:00Z: In Transit at Chicago, IL
- 2025-01-16T08:15:00Z: Shipped at Distribution Center
- 2025-01-15T10:30:00Z: Order Placed at Warehouse
```

**Frontend Display:**
```
🤖 Tracking Information for Order 12345

   Status: Shipped
   Carrier: UPS
   Tracking Number: 1Z999AA10123456784
   Current Location: Chicago, IL
   Estimated Delivery: 2025-01-20

   Tracking History:
   • 2025-01-17 12:30: In Transit at Chicago, IL
   • 2025-01-16 08:15: Shipped at Distribution Center
   • 2025-01-15 10:30: Order Placed at Warehouse
```

**Execution Time:** ~750ms (includes tracking history query)

---

## Scenario 4: Refund Request (Ineligible)

### User Input: `"return order 12345"`

This demonstrates error handling for ineligible orders.

---

### Quick Flow:

1. **Start** → Initialize state
2. **UserTask1** → Extract `orderId = "12345"`
3. **RetrievalTask1** → Fetch return policy (keyword "return" detected)
4. **LLMTask1** → Classify `intent = "refund"`
5. **ToolTask1** → Execute `process_refund("12345")`
   - Check eligibility → **FAIL** (status not "Delivered")
6. **RouterTask1** → Route to RenderTask1 (no HITL needed)
7. **RenderTask1** → Format error message
8. **END**

---

### Step 5: ToolTask1 (Refund - Ineligible)

**Processing:**
```python
# graph.py - tool_task_node()
intent = "refund"
order_id = "12345"

from tools.order_tools import process_refund
tool_result = asyncio.run(process_refund("12345", reason=None))
```

**Inside `process_refund()` → `check_return_eligibility()`:**

```python
# neo4j_module.py - check_return_eligibility()

# Get order details
order = get_order_status("12345")
# {
#   "orderId": "12345",
#   "status": "Shipped",  # NOT "Delivered"
#   "purchaseDate": "2025-01-15",
#   "totalAmount": 199.99
# }

# Check eligibility
status = order.get("status")  # "Shipped"
days_since_purchase = 295  # Within 300 days
return_policy_days = 300

eligible = True
reasons = []

# Check if delivered
if status == "Delivered":
    pass
else:
    eligible = False
    reasons.append(f"Order status is {status}, order must be delivered before it can be returned")

# Result
{
  "eligible": False,
  "orderId": "12345",
  "status": "Shipped",
  "purchaseDate": "2025-01-15",
  "daysSincePurchase": 295,
  "returnPolicyDays": 300,
  "daysRemaining": 5,
  "reason": "Order status is Shipped, order must be delivered before it can be returned"
}
```

**Tool Result:**
```python
{
  "success": False,
  "requiresApproval": False,
  "needsHumanReview": False,
  "orderId": "12345",
  "eligibility": {
    "eligible": False,
    "status": "Shipped",
    "reason": "Order status is Shipped, order must be delivered before it can be returned"
  },
  "message": "Order 12345 is not eligible for return: Order status is Shipped, order must be delivered before it can be returned"
}
```

**State Update:**
```python
state["tool_result"] = tool_result
state["needs_human_review"] = False  # No approval needed for ineligible orders
state["redirect_url"] = None  # No redirect
```

---

### Step 6: RouterTask1 (Error Routing)

**Processing:**
```python
# graph.py - router_task_node()
intent = "refund"
needs_review = False  # Because eligibility failed
tool_result = state["tool_result"]

# Routing logic
if needs_review:
    state["current_activity"] = "UserTask2"
else:
    state["current_activity"] = "RenderTask1"

# Route to RenderTask1 (no HITL)
```

---

### Step 7: RenderTask1 (Error Response)

**Processing:**
```python
# graph.py - render_task_node()
intent = "refund"
tool_result = state["tool_result"]

# Use default response builder
response = build_default_response("refund", state, tool_result)

# build_default_response() returns:
# tool_result.get("message", "This order isn't eligible for a return right now...")
```

**Final Response:**
```
Order 12345 is not eligible for return: Order status is Shipped, order must be delivered before it can be returned
```

**API Response:**
```json
{
  "conversationId": "user-session-456",
  "response": "Order 12345 is not eligible for return: Order status is Shipped, order must be delivered before it can be returned",
  "intent": "refund",
  "entities": {"orderId": "12345"},
  "toolResult": {
    "success": false,
    "requiresApproval": false,
    "message": "Order 12345 is not eligible for return: Order status is Shipped, order must be delivered before it can be returned"
  },
  "needsHumanReview": false,
  "redirectUrl": null
}
```

**Frontend Display:**
```
🤖 Order 12345 is not eligible for return: Order status is Shipped, 
   order must be delivered before it can be returned
```

**Execution Time:** ~720ms

---

## Activity Performance

### Latency Breakdown (Order 12345)

| Scenario | Total Time | Activities Involved | Notes |
|----------|-----------|---------------------|-------|
| **Order Status** | ~700ms | Start → UserTask1 → (Skip Retrieval) → LLMTask1 → ToolTask1 → RouterTask1 → RenderTask1 → END | Fastest query type |
| **Order Price** | ~680ms | Same as Status | Only queries order + items (no tracking) |
| **Track Order** | ~750ms | Same as Status | Additional tracking history query |
| **Refund (Ineligible)** | ~720ms | Start → UserTask1 → RetrievalTask1 (fetch policy) → LLMTask1 → ToolTask1 → RouterTask1 → RenderTask1 → END | Includes eligibility check + policy retrieval |

### Per-Activity Latency

| Activity | Avg Duration | Order 12345 Notes |
|----------|--------------|-------------------|
| Start | ~5ms | State initialization |
| UserTask1 | ~10ms | Regex extraction |
| RetrievalTask1 | ~0-50ms | Skipped for status/price/track, ~50ms for refund |
| LLMTask1 | ~500ms | Keyword classification (no LLM call for status/price/track) |
| ToolTask1 | ~120-180ms | Neo4j query (120ms status, 180ms tracking with history) |
| RouterTask1 | ~2ms | Conditional logic |
| RenderTask1 | ~10ms | String formatting |
| **Total** | **~700-750ms** | Much faster than Order 11111 HITL (~1.02s to pause) |

### Neo4j Queries (Order 12345)

#### Status Query:
```cypher
MATCH (o:Order {id: "12345"})
OPTIONAL MATCH (o)-[:SHIPPED_BY]->(carrier:Carrier)
OPTIONAL MATCH (o)-[:HAS_ITEM]->(item:OrderItem)
RETURN o.id, o.status, o.tracking, o.expectedDelivery, o.orderDate, 
       o.totalAmount, carrier.name, collect(item) AS items
```
**Execution:** ~80ms

#### Price Query:
```cypher
MATCH (o:Order {id: "12345"})
OPTIONAL MATCH (o)-[:HAS_ITEM]->(item:OrderItem)
RETURN o.id AS orderId, o.totalAmount, collect(item) AS items
```
**Execution:** ~70ms

#### Tracking Query:
```cypher
// 1. Get order details (same as status query)
MATCH (o:Order {id: "12345"})...

// 2. Get tracking history
MATCH (o:Order {id: "12345"})-[:HAS_TRACKING]->(t:TrackingEvent)
RETURN t.date, t.location, t.status
ORDER BY t.date DESC
LIMIT 10
```
**Execution:** ~120ms (two queries)

#### Refund Eligibility Query:
```cypher
// 1. Get order status
MATCH (o:Order {id: "12345"})
RETURN o.id, o.status, o.orderDate, o.totalAmount

// 2. Fetch return policy (RetrievalTask1)
MATCH (d:Doc)
WHERE toLower(d.title) CONTAINS "return" OR toLower(d.body) CONTAINS "return"
RETURN d.id, d.title, d.body
LIMIT 3
```
**Execution:** ~100ms (two queries, but no return request created since ineligible)

---

## Comparison with Order 11111

### Feature Comparison

| Feature | Order 11111 | Order 12345 |
|---------|-------------|-------------|
| **Order ID** | 11111 | 12345 |
| **Status** | Delivered | Shipped |
| **Carrier** | USPS | UPS |
| **Tracking #** | 9400111899223197428490 | 1Z999AA10123456784 |
| **Order Date** | 2025-06-01 | 2025-01-15 |
| **Expected Delivery** | 2025-06-05 | 2025-01-20 |
| **Total Amount** | $89.99 | $199.99 |
| **Items** | 1 (Product D × 1) | 1 (Product A × 2) |
| **Return Eligible** | ✅ Yes (Delivered, <300 days) | ❌ No (Not delivered yet) |
| **HITL Required** | ✅ Yes (refund approval) | ❌ No (status/price/track queries) |
| **Workflow Path** | All 9 activities | 7 activities (skips UserTask2, AgentTask1) |
| **Avg Response Time** | ~1.02s (to HITL pause) | ~700ms (immediate) |
| **UserTask2 Usage** | Yes (approval modal) | No |
| **Redirect URL** | `/return?orderId=11111` | None |

### Workflow Path Comparison

**Order 11111 (Refund Request):**
```
Start → UserTask1 → RetrievalTask1 → LLMTask1 → ToolTask1 → RouterTask1 → UserTask2 (PAUSE)
                                                                                  ↓
                                                                           (User approves)
                                                                                  ↓
                                                                                 END
```

**Order 12345 (Status Query):**
```
Start → UserTask1 → (Skip Retrieval) → LLMTask1 → ToolTask1 → RouterTask1 → RenderTask1 → END
```

**Order 12345 (Refund Attempt - Ineligible):**
```
Start → UserTask1 → RetrievalTask1 → LLMTask1 → ToolTask1 (Eligibility FAIL) → RouterTask1 → RenderTask1 → END
```

### State Comparison at ToolTask1

**Order 11111 (Refund - Eligible):**
```python
state["tool_result"] = {
  "success": True,
  "requiresApproval": True,
  "needsHumanReview": True,
  "orderId": "11111",
  "returnRequestId": "RET-11111-...",
  "amount": 89.99,
  "eligibility": {"eligible": True, "status": "Delivered", ...}
}
state["needs_human_review"] = True
state["redirect_url"] = "/return?orderId=11111"
```

**Order 12345 (Status Query):**
```python
state["tool_result"] = {
  "id": "12345",
  "status": "Shipped",
  "carrier": "UPS",
  "tracking": "1Z999AA10123456784",
  "totalAmount": 199.99,
  ...
}
state["needs_human_review"] = False
state["redirect_url"] = None
```

**Order 12345 (Refund - Ineligible):**
```python
state["tool_result"] = {
  "success": False,
  "requiresApproval": False,
  "needsHumanReview": False,
  "orderId": "12345",
  "eligibility": {
    "eligible": False,
    "status": "Shipped",
    "reason": "Order status is Shipped, order must be delivered..."
  },
  "message": "Order 12345 is not eligible for return..."
}
state["needs_human_review"] = False
state["redirect_url"] = None
```

---

## Summary

### Key Characteristics of Order 12345 Workflows

1. **Non-HITL Flows**: Most queries complete without human intervention
2. **Fast Response**: ~700ms average (vs ~1.02s for HITL pause)
3. **Direct Rendering**: Router sends directly to RenderTask1
4. **No Cycle Risk**: UserTask2 never invoked, so no cycle issues
5. **Rich Tracking**: 3 tracking events provide detailed location history
6. **Clear Error Handling**: Ineligible refund requests explained clearly

### Use Cases for Order 12345

- ✅ **Order Status Checks**: Immediate response with carrier info
- ✅ **Price Inquiries**: Detailed breakdown with item quantities
- ✅ **Tracking Updates**: Real-time location and history
- ❌ **Refunds**: Not eligible until delivered (expected 2025-01-20)
- ✅ **Policy Questions**: Can retrieve general return policy info

### Workflow Efficiency

**Order 12345 demonstrates the "happy path" for most order queries:**
- No approval needed → faster response
- No checkpoint pause → lower latency
- No database writes → simpler state management
- Clear eligibility rules → predictable error messages

**When Order 12345 is delivered (status changes to "Delivered"):**
- Will become eligible for refund
- Will trigger HITL workflow like Order 11111
- Will create return request in Neo4j
- Will route to UserTask2 for approval

---

**For more details, see:**
- `WORKFLOW.md` - Order 11111 HITL example
- `workflow.json` - Activity definitions
- `graph.py` - Node implementations
- `tools/order_tools.py` - Tool functions
- `data.cypher` - Order 12345 seed data (lines 40-75)

