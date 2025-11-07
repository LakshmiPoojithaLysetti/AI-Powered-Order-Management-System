# Conditional Branches in AI-Powered Order Management System

This document catalogs all conditional branches (decision points) used throughout the project, showing where and how the workflow makes routing decisions.

## Table of Contents

- [Overview](#overview)
- [LangGraph Conditional Edges](#langgraph-conditional-edges)
- [Intent-Based Branching](#intent-based-branching)
- [State-Based Branching](#state-based-branching)
- [Tool Execution Branching](#tool-execution-branching)
- [Response Formatting Branching](#response-formatting-branching)
- [Human-in-the-Loop Branching](#human-in-the-loop-branching)
- [Workflow.json Routing Conditions](#workflowjson-routing-conditions)

---

## Overview

The system uses conditional branching at multiple levels to route requests, execute appropriate tools, and format responses based on user intent and workflow state.

### Branching Types:

1. **LangGraph Conditional Edges**: Workflow routing at the graph level
2. **Intent Classification**: Determining user's goal from natural language
3. **State Checks**: Routing based on workflow state flags
4. **Tool Selection**: Choosing which tool to execute
5. **Response Formatting**: Formatting output based on intent and data
6. **HITL Control**: Pausing/resuming workflow for human approval

---

## LangGraph Conditional Edges

### Location: `graph.py` lines 615-662

### 1. RouterTask1 Conditional Edge

**File:** `graph.py:619-635`

```python
def route_condition(state: GraphState) -> Literal["RenderTask1", "AgentTask1", "UserTask2"]:
    next_activity = state.get("current_activity", "RenderTask1")
    if next_activity == "AgentTask1":
        return "AgentTask1"
    if next_activity == "UserTask2":
        return "UserTask2"
    return "RenderTask1"

workflow_graph.add_conditional_edges(
    "RouterTask1",
    route_condition,
    {
        "RenderTask1": "RenderTask1",
        "AgentTask1": "AgentTask1",
        "UserTask2": "UserTask2",
    },
)
```

**Purpose:** Routes to one of three destinations based on `current_activity` state

**Decision Logic:**
- `current_activity == "AgentTask1"` → Route to AgentTask1 (complex operations)
- `current_activity == "UserTask2"` → Route to UserTask2 (HITL approval)
- Default → Route to RenderTask1 (normal response)

**Used By:**
- `router_task_node()` sets `current_activity` based on `needs_human_review` and `intent`

---

### 2. UserTask2 Conditional Edge (Cycle Breaker)

**File:** `graph.py:642-661`

```python
def user_task2_route(state: GraphState) -> Literal["LLMTask1", "__end__"]:
    needs_review = state.get("needs_human_review", False)
    if needs_review:
        # Still waiting for input, end the workflow (pause for HITL)
        return "__end__"
    else:
        # Review complete, can loop back for follow-up if needed
        # But for now, terminate to avoid infinite loops
        return "__end__"

workflow_graph.add_conditional_edges(
    "UserTask2",
    user_task2_route,
    {
        "LLMTask1": target_node,
        "__end__": END,
    },
)
```

**Purpose:** Controls the cyclic connection from UserTask2 back to LLMTask1

**Decision Logic:**
- `needs_human_review == True` → Pause workflow (`__end__`)
- `needs_human_review == False` → Terminate workflow (`__end__`)
- **Note:** Currently always terminates to prevent infinite loops

**Potential Cycle Usage (from WORKFLOW2.md):**
```python
def user_task2_route(state: GraphState) -> Literal["LLMTask1", "__end__"]:
    needs_review = state.get("needs_human_review", False)
    workflow_complete = state.get("workflow_complete", False)
    follow_up_needed = state.get("follow_up_needed", False)
    
    if needs_review:
        return "__end__"  # Pause for HITL
    elif follow_up_needed:
        return "LLMTask1"  # Loop back for follow-up
    elif workflow_complete:
        return "__end__"  # Done
    else:
        return "__end__"  # Default
```

---

## Intent-Based Branching

### Location: `graph.py` lines 78-121

### Intent Classification Function

**File:** `graph.py:78-121`

```python
def classify_intent(text: str, entities: Dict[str, Any]) -> str:
    """Classify user intent from input text."""
    text_lower = text.lower()
    order_id = entities.get("orderId")
    
    # Status queries (includes carrier questions)
    if re.search(r'\b(status|check|what.*status|how.*order|carrier|shipper|shipping company)\b', 
                 text_lower) and order_id:
        return "order_status"
    
    # Price queries
    if re.search(r'\b(price|cost|how much|total|amount)\b', text_lower) and order_id:
        return "order_price"
    
    # Tracking queries
    if re.search(r'\b(track|where|location|shipped|delivery)\b', text_lower) and order_id:
        return "track_order"
    
    # Refund/return queries
    if re.search(r'\b(return|refund|cancel|money back)\b', text_lower):
        return "refund"
    
    # Policy questions
    if re.search(r'\b(policy|policies|warranty|guarantee|shipping|return policy)\b', text_lower):
        return "policy_question"
    
    # Fastener search
    if re.search(r'\b(fastener|screw|bolt|nut|washer|hardware)\b', text_lower):
        return "fastener_search"
    
    # Default to chit chat
    return "chit_chat"
```

**Purpose:** Convert natural language to structured intent

**Intents Supported:**
1. `order_status` - Check order status and carrier info
2. `order_price` - Get order pricing details
3. `track_order` - Track order shipment
4. `refund` - Process refund/return requests
5. `policy_question` - Answer policy questions
6. `fastener_search` - Search for hardware parts
7. `chit_chat` - General conversation

**Regex Patterns Used:**
| Intent | Keywords | Requires Order ID |
|--------|----------|-------------------|
| order_status | status, check, carrier, shipper | ✅ Yes |
| order_price | price, cost, how much, total | ✅ Yes |
| track_order | track, where, location, shipped | ✅ Yes |
| refund | return, refund, cancel, money back | ❌ No |
| policy_question | policy, warranty, guarantee | ❌ No |
| fastener_search | fastener, screw, bolt, nut | ❌ No |

---

## State-Based Branching

### Location: `graph.py:279-297`

### Router Task Node

**File:** `graph.py:286-296`

```python
def router_task_node(state: GraphState) -> GraphState:
    """Router task node - routes to next activity based on conditions."""
    intent = state.get("intent", "")
    needs_review = state.get("needs_human_review", False)
    tool_result = state.get("tool_result")
    
    # Routing logic
    if needs_review:
        state["current_activity"] = "UserTask2"  # Route to human review
    elif intent in ["order_status", "order_price", "track_order", "policy_question", "chit_chat"]:
        state["current_activity"] = "RenderTask1"  # Route to render
    elif intent == "fastener_search":
        state["current_activity"] = "AgentTask1"  # Route to agent
    else:
        state["current_activity"] = "RenderTask1"  # Default to render
    
    return state
```

**Purpose:** Set `current_activity` to control RouterTask1 conditional edge

**Routing Table:**

| Condition | Route To | Purpose |
|-----------|----------|---------|
| `needs_human_review == True` | UserTask2 | HITL approval for refunds |
| `intent == "order_status"` | RenderTask1 | Format status response |
| `intent == "order_price"` | RenderTask1 | Format price response |
| `intent == "track_order"` | RenderTask1 | Format tracking response |
| `intent == "policy_question"` | RenderTask1 | Format policy response |
| `intent == "chit_chat"` | RenderTask1 | Format chat response |
| `intent == "fastener_search"` | AgentTask1 | Complex agent processing |
| Default | RenderTask1 | Fallback |

**Priority:** `needs_human_review` check happens first (highest priority)

---

## Tool Execution Branching

### Location: `graph.py:222-276`

### Tool Task Node

**File:** `graph.py:235-268`

```python
def tool_task_node(state: GraphState) -> GraphState:
    """Tool task node - executes tools based on intent."""
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    order_id = entities.get("orderId")
    input_text = state.get("input", "")
    
    tool_result = None
    
    try:
        if intent == "order_status" and order_id:
            import asyncio
            tool_result = asyncio.run(lookup_order_status(order_id))
        
        elif intent == "order_price" and order_id:
            import asyncio
            from tools.order_tools import get_order_price
            tool_result = asyncio.run(get_order_price(order_id))
        
        elif intent == "track_order" and order_id:
            import asyncio
            tool_result = asyncio.run(track_order(order_id))
        
        elif intent == "refund" and order_id:
            import asyncio
            reason = None
            if "reason" in input_text.lower() or "because" in input_text.lower():
                reason_match = re.search(r'(?:reason|because)[:\s]+(.+?)(?:\.|$)', 
                                        input_text, re.IGNORECASE)
                if reason_match:
                    reason = reason_match.group(1).strip()

            tool_result = asyncio.run(process_refund(order_id, reason=reason))

            # Set HITL flags if refund requires approval
            if tool_result and tool_result.get("needsHumanReview", False):
                state["needs_human_review"] = True
                state["review_message"] = tool_result.get("message", "...")
                is_delivered = (
                    tool_result.get("eligibility", {}).get("status") == "Delivered"
                    if tool_result.get("eligibility") else False
                )
                if tool_result.get("success") and tool_result.get("requiresApproval") and is_delivered:
                    state["redirect_url"] = f"/return?orderId={order_id}"
                else:
                    state.pop("redirect_url", None)
            else:
                state.pop("redirect_url", None)
        
        if tool_result:
            state["tool_result"] = tool_result
    
    except Exception as e:
        print(f"[ToolTask] Error executing tool: {e}")
        state["tool_result"] = {"error": str(e)}

    return state
```

**Purpose:** Execute the appropriate tool based on intent

**Tool Execution Matrix:**

| Intent | Tool Function | Parameters | HITL? |
|--------|---------------|------------|-------|
| `order_status` | `lookup_order_status()` | order_id | ❌ No |
| `order_price` | `get_order_price()` | order_id | ❌ No |
| `track_order` | `track_order()` | order_id | ❌ No |
| `refund` | `process_refund()` | order_id, reason | ✅ **Yes** (if eligible) |

**Refund Special Logic:**

1. Extract refund reason from input text (optional)
2. Call `process_refund()` to check eligibility
3. If eligible and delivered:
   - Set `needs_human_review = True`
   - Set `redirect_url = "/return?orderId={id}"`
   - Set `review_message`
4. If not eligible: Clear redirect URL

---

## Response Formatting Branching

### Location: `graph.py:300-376`

### Render Task Node

**File:** `graph.py:317-372`

```python
def render_task_node(state: GraphState) -> GraphState:
    """Render task node - formats and returns response."""
    intent = state.get("intent", "")
    tool_result = state.get("tool_result")
    needs_review = state.get("needs_human_review", False)
    
    # If human review is needed, don't render here
    if needs_review:
        print(f"[RenderTask] Skipping render - human review required")
        return state
        
    response = ""
    
    if intent == "order_status" and tool_result:
        status = tool_result.get("status", "Unknown")
        order_id = tool_result.get("id") or tool_result.get("orderId", "unknown")
        items = tool_result.get("items", [])
        total = tool_result.get("totalAmount", 0)
        carrier = tool_result.get("carrier")
        
        response = f"Order {order_id} is currently **{status}**."
        if carrier:
            response += f" It is being handled by **{carrier}**."
        if items:
            response += f" Order contains {len(items)} item(s)."
        if total:
            response += f" Total amount: ${float(total):,.2f}"
    
    elif intent == "order_price" and tool_result:
        order_id = tool_result.get("orderId") or tool_result.get("id", "unknown")
        total = tool_result.get("totalAmount", 0)
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
        else:
            response = f"Price information not available for order {order_id}."
    
    elif intent == "track_order" and tool_result:
        order_id = tool_result.get("id") or tool_result.get("orderId", "unknown")
        tracking = tool_result.get("trackingNumber") or "N/A"
        status = tool_result.get("status", "Unknown")
        carrier = tool_result.get("carrier", "Unknown")
        location = tool_result.get("currentLocation", "Unknown")
        
        response = f"**Tracking Information for Order {order_id}**\n\n"
        response += f"Status: {status}\nCarrier: {carrier}\nTracking: {tracking}\nLocation: {location}\n"
        
        history = tool_result.get("trackingHistory", [])
        if history:
            response += "\n**Tracking History:**\n"
            for event in history[:5]:  # Show last 5 events
                date = event.get("date", "Unknown")
                location = event.get("location", "Unknown")
                event_status = event.get("status", "Unknown")
                response += f"- {date}: {location} - {event_status}\n"
    
    elif intent == "policy_question":
        response = "Our return policy allows returns within 30 days of purchase. Shipping is free for orders over $50."
    
    elif intent == "chit_chat":
        response = "Please provide the order details so I can assist you more effectively!"
    
    else:
        response = build_default_response(intent or "", state, tool_result)
    
    state["response"] = response
    return state
```

**Purpose:** Format response based on intent and tool result

**Response Templates:**

| Intent | Template |
|--------|----------|
| `order_status` | "Order {id} is currently **{status}**. Carrier: **{carrier}**. Items: {count}. Total: ${amount}" |
| `order_price` | "Total price for order {id} is **${amount}**.\n\n**Item Breakdown:**\n- {item}: {qty} × ${price}" |
| `track_order` | "**Tracking Info for Order {id}**\n\nStatus: {status}\nCarrier: {carrier}\nTracking: {tracking}\nLocation: {location}\n\n**Tracking History:**\n- {events}" |
| `policy_question` | "Our return policy allows returns within 30 days..." |
| `chit_chat` | "Please provide the order details..." |
| `refund` | Handled by `build_default_response()` |

**Special Cases:**

1. **needs_review = True**: Skip rendering (UserTask2 will handle)
2. **No tool_result**: Use default response
3. **Missing data**: Show "N/A" or "Unknown"

---

## Human-in-the-Loop Branching

### Location: `graph.py:425-527`

### UserTask2 Node

**File:** `graph.py:449-523`

```python
def user_task2_node(state: GraphState) -> GraphState:
    """User task 2 node - human review/approval for refund requests."""
    human_input = state.get("human_input")
    tool_result = state.get("tool_result")
    user_response = human_input or state.get("input", "")
    
    is_refund = tool_result and (
        tool_result.get("returnRequestId") or 
        tool_result.get("refundId") or
        "refund" in str(tool_result).lower()
    )
    
    if is_refund and tool_result:
        return_request_id = tool_result.get("returnRequestId")
        order_id = tool_result.get("orderId")
        amount = tool_result.get("amount", 0.0)
        
        # Branch 1: User approves
        if user_response and user_response.lower().strip() in ["yes", "y", "approve", "confirm", "approved"]:
            import asyncio
            from tools.order_tools import approve_return

            approval_result = asyncio.run(approve_return(return_request_id, approved=True))

            if approval_result and approval_result.get("success", False):
                state["needs_human_review"] = False
                state["workflow_complete"] = True
                state["response"] = (
                    f"✅ **Refund Approved**\n\n"
                    f"Your refund request for order {order_id} (${amount:,.2f}) has been approved..."
                )
            else:
                state["needs_human_review"] = False
                state["workflow_complete"] = True
                state["response"] = "❌ Error approving refund request."

        # Branch 2: User rejects
        elif user_response and user_response.lower().strip() in ["no", "n", "reject", "cancel", "rejected"]:
            import asyncio
            from tools.order_tools import approve_return

            rejection_result = asyncio.run(approve_return(return_request_id, approved=False))

            state["needs_human_review"] = False
            state["workflow_complete"] = True
            state["response"] = f"❌ **Refund Rejected**\n\nYour refund request for order {order_id} has been rejected..."

        # Branch 3: Still waiting for input
        else:
            state["needs_human_review"] = True
            reason = tool_result.get('reason', 'Customer request')
            state["response"] = (
                "⏳ **Refund Request Pending Approval**\n\n"
                f"**Order ID:** {order_id}\n"
                f"**Amount:** ${amount:,.2f}\n"
                f"**Reason:** {reason}\n\n"
                "Please **approve** or **reject** this refund request..."
            )
    
    else:
        # Non-refund review cases
        if user_response and user_response.lower() in ["yes", "y", "approve", "confirm"]:
            state["needs_human_review"] = False
            state["workflow_complete"] = True
            state["response"] = "Your request has been approved..."
        elif user_response and user_response.lower() in ["no", "n", "reject", "cancel"]:
            state["needs_human_review"] = False
            state["workflow_complete"] = True
            state["response"] = "Your request has been cancelled."
        else:
            state["needs_human_review"] = True
            state["response"] = "Please approve or reject this request."
    
    return state
```

**Purpose:** Handle human approval/rejection for refund requests

**Decision Tree:**

```
UserTask2
├─ Is Refund Request?
│  ├─ Yes → Check User Response
│  │  ├─ "approve" / "yes" → Approve refund → Set workflow_complete=True → Response: "✅ Refund Approved"
│  │  ├─ "reject" / "no" → Reject refund → Set workflow_complete=True → Response: "❌ Refund Rejected"
│  │  └─ Other / None → Keep needs_human_review=True → Response: "⏳ Pending Approval"
│  │
│  └─ No → Generic Review
│     ├─ "approve" / "yes" → Set workflow_complete=True → Response: "Approved"
│     ├─ "reject" / "no" → Set workflow_complete=True → Response: "Cancelled"
│     └─ Other / None → Keep needs_human_review=True → Response: "Please approve or reject"
```

**Approval Keywords:**
- ✅ **Approve**: "yes", "y", "approve", "confirm", "approved"
- ❌ **Reject**: "no", "n", "reject", "cancel", "rejected"

**State Updates:**

| User Response | needs_human_review | workflow_complete | Action |
|---------------|-------------------|-------------------|--------|
| "approve" | False | True | Call `approve_return(approved=True)` |
| "reject" | False | True | Call `approve_return(approved=False)` |
| Other / None | True | False | Show approval prompt, pause workflow |

---

## Workflow.json Routing Conditions

### Location: `workflow.json:673-709`

### RouterTask1 Routing Conditions

**File:** `workflow.json:673-709`

```json
{
  "Name": "routingConditions",
  "Value": [
    {
      "Variable": "needs_human_review",
      "Type": "Boolean",
      "Operator": "equals",
      "Value": true,
      "Node": "UserTask2",
      "Description": "Route to HITL approval when refund requires human review"
    },
    {
      "Variable": "intent",
      "Type": "String",
      "Operator": "equals",
      "Value": "fastener_search",
      "Node": "AgentTask1",
      "Description": "Route to agent for complex fastener search operations"
    },
    {
      "Variable": "intent",
      "Type": "String",
      "Operator": "in",
      "Value": ["order_status", "order_price", "track_order", "policy_question", "chit_chat"],
      "Node": "RenderTask1",
      "Description": "Route to render for standard responses"
    },
    {
      "Variable": "default",
      "Type": "fallback",
      "Operator": "default",
      "Value": null,
      "Node": "RenderTask1",
      "Description": "Default route to RenderTask1"
    }
  ]
}
```

**Purpose:** Document routing conditions for RouterTask1 in workflow definition

**Routing Priority (top to bottom):**

1. **needs_human_review = true** → UserTask2 (highest priority)
2. **intent = "fastener_search"** → AgentTask1
3. **intent in ["order_status", "order_price", "track_order", "policy_question", "chit_chat"]** → RenderTask1
4. **default** → RenderTask1 (fallback)

---

### UserTask2 Cycle Routing

**File:** `workflow.json:1022-1028`

```json
{
  "Name": "CycleRouting",
  "Value": {
    "follow_up_needed_true": "LLMTask1",
    "workflow_complete_true": "__end__",
    "needs_review_true": "__end__"
  }
}
```

**Purpose:** Define routing conditions for UserTask2 cyclic connection

**Routing Logic:**
- `follow_up_needed = true` → LLMTask1 (cycle back for follow-up)
- `workflow_complete = true` → END (terminate)
- `needs_review = true` → END (pause for HITL)

**Note:** Currently not implemented in code (always routes to END)

---

## Summary: All Conditional Branches

### By File

| File | Branches | Purpose |
|------|----------|---------|
| `graph.py` | 7 major branches | Workflow routing, tool selection, response formatting |
| `workflow.json` | 2 routing configs | Document routing conditions for activities |
| `tools/order_tools.py` | Multiple | Order data validation, refund eligibility checks |
| `neo4j_module.py` | Multiple | Return policy validation, eligibility checks |

### By Type

| Type | Count | Examples |
|------|-------|----------|
| **LangGraph Conditional Edges** | 2 | RouterTask1, UserTask2 |
| **Intent Classification** | 7 | order_status, refund, etc. |
| **State-Based Routing** | 4 | needs_human_review, intent checks |
| **Tool Selection** | 4 | lookup_order_status, process_refund, etc. |
| **Response Formatting** | 6 | Different templates per intent |
| **HITL Approval** | 3 | approve, reject, pending |

### Decision Flow Diagram

```
User Input
    ↓
[UserTask1] Extract entities → orderId, etc.
    ↓
[RetrievalTask1] Policy query? → Fetch docs or skip
    ↓
[LLMTask1] Classify intent → 7 possible intents
    ↓
[ToolTask1] Execute tool
    ├─ order_status → lookup_order_status()
    ├─ order_price → get_order_price()
    ├─ track_order → track_order()
    └─ refund → process_refund()
        ├─ Eligible & Delivered? → Set needs_human_review=True
        └─ Not eligible → Set needs_human_review=False
    ↓
[RouterTask1] Route based on state
    ├─ needs_human_review=True → UserTask2 (HITL)
    ├─ intent=fastener_search → AgentTask1
    └─ Default → RenderTask1
    ↓
[UserTask2] If routed here
    ├─ User says "approve" → Approve refund → END
    ├─ User says "reject" → Reject refund → END
    └─ No input yet → Show prompt → END (pause)
    ↓
[RenderTask1] If routed here
    ├─ Format response based on intent
    └─ END
```

---

## Key Takeaways

1. **Two-Level Routing**: 
   - High-level: LangGraph conditional edges
   - Low-level: Intent and state checks within nodes

2. **Priority Order**: 
   - `needs_human_review` (highest priority)
   - `intent` classification
   - Default fallbacks

3. **Cycle Prevention**: 
   - UserTask2 conditional edge always returns `__end__`
   - Can be modified to support follow-up flows

4. **HITL Control**: 
   - `needs_human_review` flag pauses workflow
   - User approval/rejection resumes and completes workflow

5. **Extensibility**: 
   - Easy to add new intents
   - Easy to add new routing conditions
   - Easy to add new tools

---

**For more details, see:**
- `graph.py` - Implementation of all conditional logic
- `workflow.json` - Declarative routing conditions
- `WORKFLOW.md` - Order 11111 example with HITL branching
- `WORKFLOW1.md` - Order 12345 example with non-HITL branching
- `WORKFLOW2.md` - Cyclic flow example with follow-up branching

