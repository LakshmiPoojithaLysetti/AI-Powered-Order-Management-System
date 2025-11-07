# Workflow Diagram & Data Flow - Cyclic Flow Example

This document demonstrates a **cyclic workflow** where `UserTask2` routes back to `LLMTask1` for follow-up interactions. This showcases the full potential of the `workflow.json` topology with the cycle being actively used.

## Table of Contents

- [Overview](#overview)
- [The Cyclic Connection](#the-cyclic-connection)
- [Scenario: Multi-Turn Refund Conversation](#scenario-multi-turn-refund-conversation)
- [Modified Cycle Logic](#modified-cycle-logic)
- [Complete Flow Trace](#complete-flow-trace)
- [State Evolution](#state-evolution)
- [Comparison with Linear Flows](#comparison-with-linear-flows)

## Overview

In the current implementation, the cycle `UserTask2 → LLMTask1` is **prevented** by always routing to `__end__`. However, this document demonstrates how the cycle **could be used** for multi-turn conversations where the system asks follow-up questions after processing human input.

### Current vs. Proposed Cycle Handling

**Current Implementation (Cycle Prevention):**
```python
def user_task2_route(state: GraphState) -> Literal["LLMTask1", "__end__"]:
    needs_review = state.get("needs_human_review", False)
    if needs_review:
        return "__end__"  # Pause for HITL
    else:
        return "__end__"  # Always terminate
```

**Proposed Implementation (Active Cycle):**
```python
def user_task2_route(state: GraphState) -> Literal["LLMTask1", "__end__"]:
    needs_review = state.get("needs_human_review", False)
    workflow_complete = state.get("workflow_complete", False)
    follow_up_needed = state.get("follow_up_needed", False)
    
    if needs_review:
        return "__end__"  # Pause for HITL
    elif workflow_complete:
        return "__end__"  # Terminate when done
    elif follow_up_needed:
        return "LLMTask1"  # Loop back for follow-up processing
    else:
        return "__end__"  # Default terminate
```

### Workflow Topology with Active Cycle

```
┌─────────┐
│  Start  │ (1)
└────┬────┘
     │
┌────▼────────┐
│  UserTask1  │ (2)
└────┬────────┘
     │
┌────▼──────────────┐
│  RetrievalTask1   │ (3)
└────┬──────────────┘
     │
┌────▼─────────┐
│   LLMTask1   │◄──────────────────┐
└────┬─────────┘                   │
     │                              │
┌────▼─────────┐                   │
│  ToolTask1   │ (5)                │
└────┬─────────┘                   │
     │                              │
┌────▼──────────┐                  │
│  RouterTask1  │ (6)               │
└────┬──────────┘                  │
     │                              │
     ├──────────────┬──────────┐   │
     │              │          │   │
┌────▼────────┐ ┌──▼───────┐ │   │
│ RenderTask1 │ │AgentTask1│ │   │
└─────────────┘ └──────────┘ │   │
                              │   │
                         ┌────▼───▼───┐
                         │  UserTask2  │ (9)
                         └────┬────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
              follow_up_needed?        │
                    │                   │
                   YES                 NO
                    │                   │
                    └───────────────────┘
                                        │
                                       END
```

## The Cyclic Connection

### Connection in workflow.json

**Lines 519-522:**
```json
{
  "SourceActivityId": "9",  // UserTask2
  "TargetActivityId": "4"   // LLMTask1
}
```

This creates the topology: `UserTask2 → LLMTask1 → ToolTask1 → RouterTask1 → [RenderTask1/AgentTask1/UserTask2]`

### Why Use the Cycle?

**Use Cases:**
1. **Follow-up Questions**: "Would you like to know the refund status?"
2. **Cross-Sell**: "Can I help you with another order?"
3. **Confirmation**: "Should I send you an email confirmation?"
4. **Additional Actions**: "Would you like to update your shipping address?"
5. **Multi-Step Approval**: Approval → Process → Confirm → Done

---

## Scenario: Multi-Turn Refund Conversation

### User Journey

**Turn 1:** User requests refund  
**Turn 2:** System asks for approval  
**Turn 3:** User approves  
**Turn 4:** System processes refund and asks follow-up  
**Turn 5:** User responds to follow-up  
**Turn 6:** System completes final action  

### Modified Code

To enable this scenario, we need to modify the cycle routing logic and the `user_task2_node` to set `follow_up_needed`.

---

## Modified Cycle Logic

### Step 1: Update GraphState

**File: `graph.py`**

```python
class GraphState(TypedDict):
    """State schema for the workflow graph."""
    messages: List[Any]
    input: str
    channel: str
    intent: Optional[str]
    entities: Dict[str, Any]
    tool_result: Optional[Dict[str, Any]]
    retrieved: List[Dict[str, Any]]
    needs_human_review: bool
    human_input: Optional[str]
    response: Optional[str]
    current_activity: Optional[str]
    workflow_data: Optional[Dict[str, Any]]
    review_message: Optional[str]
    redirect_url: Optional[str]
    workflow_complete: Optional[bool]
    follow_up_needed: Optional[bool]  # NEW
    follow_up_question: Optional[str]  # NEW
    turn_count: Optional[int]  # NEW - track conversation turns
```

### Step 2: Modify UserTask2 to Set Follow-up

**File: `graph.py` - `user_task2_node()`**

```python
def user_task2_node(state: GraphState) -> GraphState:
    """User task 2 node - human review/approval for refund requests."""
    human_input = state.get("human_input")
    tool_result = state.get("tool_result")
    turn_count = state.get("turn_count", 0)
    
    user_response = human_input or state.get("input", "")
    
    print(f"[UserTask2] Turn {turn_count}, input: {user_response}")
    
    is_refund = tool_result and (
        tool_result.get("returnRequestId") or 
        tool_result.get("refundId")
    )
    
    if is_refund and tool_result:
        return_request_id = tool_result.get("returnRequestId")
        order_id = tool_result.get("orderId")
        amount = tool_result.get("amount", 0.0)
        
        # Check user response for approval/rejection
        if user_response and user_response.lower().strip() in ["yes", "y", "approve", "confirm", "approved"]:
            # Approval granted
            import asyncio
            from tools.order_tools import approve_return

            try:
                approval_result = asyncio.run(approve_return(return_request_id, approved=True))

                if approval_result and approval_result.get("success", False):
                    state["needs_human_review"] = False
                    state["workflow_complete"] = False  # NOT complete yet
                    state["follow_up_needed"] = True   # NEW - trigger cycle
                    state["follow_up_question"] = "ask_email_confirmation"  # NEW
                    state["turn_count"] = turn_count + 1
                    
                    state["response"] = (
                        f"✅ **Refund Approved**\n\n"
                        f"Your refund request for order {order_id} (${amount:,.2f}) has been approved. "
                        f"The refund will be credited to your original payment method within 5-7 business days.\n\n"
                        f"**Would you like to receive an email confirmation?** (yes/no)"
                    )
                else:
                    state["needs_human_review"] = False
                    state["workflow_complete"] = True
                    state["response"] = "❌ Error approving refund request. Please contact support."
            except Exception as e:
                print(f"[UserTask2] Error approving refund: {e}")
                state["needs_human_review"] = False
                state["workflow_complete"] = True
                state["response"] = f"❌ Error processing approval: {str(e)}"

        elif user_response and user_response.lower().strip() in ["no", "n", "reject", "cancel", "rejected"]:
            # Rejection
            state["needs_human_review"] = False
            state["workflow_complete"] = True
            state["follow_up_needed"] = False
            state["response"] = f"❌ Refund request for order {order_id} has been cancelled."
        
        else:
            # Still waiting for approval input
            state["needs_human_review"] = True
            state["follow_up_needed"] = False
            reason = tool_result.get('reason', 'Customer request')
            state["response"] = (
                "⏳ **Refund Request Pending Approval**\n\n"
                f"**Order ID:** {order_id}\n"
                f"**Amount:** ${amount:,.2f}\n"
                f"**Reason:** {reason}\n\n"
                "Please **approve** or **reject** this refund request:\n"
                "- Type 'approve' or 'yes' to approve\n"
                "- Type 'reject' or 'no' to reject"
            )
    
    return state
```

### Step 3: Modify Cycle Routing

**File: `graph.py` - `build_from_copilot_json()`**

```python
elif source_node == "UserTask2":
    # Add conditional edge for UserTask2 to handle cycle
    if source_node in conditional_nodes:
        continue

    def user_task2_route(state: GraphState) -> Literal["LLMTask1", "__end__"]:
        needs_review = state.get("needs_human_review", False)
        workflow_complete = state.get("workflow_complete", False)
        follow_up_needed = state.get("follow_up_needed", False)
        
        print(f"[UserTask2 Route] needs_review={needs_review}, complete={workflow_complete}, follow_up={follow_up_needed}")
        
        if needs_review:
            # Pause for human input
            return "__end__"
        elif follow_up_needed:
            # Loop back to LLMTask1 for follow-up processing
            return "LLMTask1"
        elif workflow_complete:
            # Workflow done
            return "__end__"
        else:
            # Default terminate
            return "__end__"

    workflow_graph.add_conditional_edges(
        source_node,
        user_task2_route,
        {
            "LLMTask1": target_node,
            "__end__": END,
        }
    )
    conditional_nodes.add(source_node)
```

### Step 4: Handle Follow-up in LLMTask1

**File: `graph.py` - `llm_task_node()`**

```python
def llm_task_node(state: GraphState) -> GraphState:
    """LLM task node - intent classification and entity extraction."""
    input_text = state.get("input", "")
    entities = state.get("entities", {})
    follow_up_question = state.get("follow_up_question")
    turn_count = state.get("turn_count", 0)
    
    print(f"[LLMTask] Processing input: {input_text[:100]}, Turn: {turn_count}")
    
    # Check if this is a follow-up response
    if follow_up_question:
        print(f"[LLMTask] Follow-up question: {follow_up_question}")
        
        # Handle follow-up intent based on context
        if follow_up_question == "ask_email_confirmation":
            # User responded to email confirmation question
            if input_text.lower().strip() in ["yes", "y", "sure", "ok", "please"]:
                state["intent"] = "send_email_confirmation"
            elif input_text.lower().strip() in ["no", "n", "nope", "skip"]:
                state["intent"] = "skip_email_confirmation"
            else:
                state["intent"] = "unclear_response"
        
        # Clear follow-up flag after processing
        state["follow_up_question"] = None
        state["follow_up_needed"] = False
        
        return state
    
    # Normal intent classification (existing code)
    intent = classify_intent(input_text, entities)
    state["intent"] = intent
    
    # ... rest of existing LLMTask1 logic
    
    return state
```

### Step 5: Handle Follow-up in ToolTask1

**File: `graph.py` - `tool_task_node()`**

```python
def tool_task_node(state: GraphState) -> GraphState:
    """Tool task node - executes tools based on intent."""
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    order_id = entities.get("orderId")
    
    print(f"[ToolTask] Executing tool for intent: {intent}")
    
    tool_result = None
    
    try:
        # ... existing tool executions (order_status, price, track, refund)
        
        # NEW: Handle email confirmation intent
        if intent == "send_email_confirmation":
            # Simulate sending email
            order_id = entities.get("orderId", "unknown")
            tool_result = {
                "success": True,
                "action": "email_sent",
                "orderId": order_id,
                "message": f"Email confirmation sent for order {order_id}"
            }
            state["workflow_complete"] = True  # Now we're done
        
        elif intent == "skip_email_confirmation":
            tool_result = {
                "success": True,
                "action": "email_skipped",
                "message": "No email will be sent"
            }
            state["workflow_complete"] = True  # Done
        
        elif intent == "unclear_response":
            tool_result = {
                "success": False,
                "action": "clarification_needed",
                "message": "I didn't understand that. Please respond with yes or no."
            }
            # Set follow-up again to retry
            state["follow_up_needed"] = True
            state["follow_up_question"] = "ask_email_confirmation"
        
        if tool_result:
            state["tool_result"] = tool_result
    
    except Exception as e:
        print(f"[ToolTask] Error executing tool: {e}")
        state["tool_result"] = {"error": str(e)}
    
    return state
```

---

## Complete Flow Trace

### User Journey: Order 11111 Refund with Follow-up

**Initial Context:**
- Order ID: 11111
- Status: Delivered
- Amount: $89.99
- User: Alice Johnson

---

### Turn 1: Initial Refund Request

**User Input:** `"return order 11111"`

**Flow:**
```
Start → UserTask1 (extract orderId) 
      → RetrievalTask1 (fetch policy) 
      → LLMTask1 (intent=refund) 
      → ToolTask1 (check eligibility, create return request) 
      → RouterTask1 (needs_review=True → route to UserTask2) 
      → UserTask2 (show approval prompt)
      → Route: needs_review=True → __end__ (PAUSE)
```

**State at Pause:**
```python
{
  "input": "return order 11111",
  "intent": "refund",
  "entities": {"orderId": "11111"},
  "tool_result": {
    "success": True,
    "requiresApproval": True,
    "needsHumanReview": True,
    "returnRequestId": "RET-11111-20241107-abc",
    "amount": 89.99,
    "eligibility": {"eligible": True, "status": "Delivered"}
  },
  "needs_human_review": True,
  "workflow_complete": False,
  "follow_up_needed": False,
  "turn_count": 0,
  "response": "⏳ **Refund Request Pending Approval**\n\nOrder ID: 11111..."
}
```

**Response to User:**
```
🤖 ⏳ Refund Request Pending Approval

   Order ID: 11111
   Amount: $89.99
   Reason: Customer request

   Please approve or reject this refund request:
   - Type 'approve' or 'yes' to approve
   - Type 'reject' or 'no' to reject
```

**Checkpoint:** Workflow paused, state saved in MemorySaver

---

### Turn 2: User Approves

**User Input:** `"approve"`

**Flow:**
```
Resume from checkpoint
  → UserTask2 (process approval, set follow_up_needed=True)
  → Route: follow_up_needed=True → LLMTask1 (CYCLE ACTIVATED!)
  → LLMTask1 (follow_up_question="ask_email_confirmation", skip intent classification)
  → ToolTask1 (no tool execution, pass through)
  → RouterTask1 (route to RenderTask1)
  → RenderTask1 (format response)
  → END
```

**State After Approval:**
```python
{
  "input": "approve",
  "intent": "refund",  # Unchanged from previous turn
  "entities": {"orderId": "11111"},
  "tool_result": {
    "success": True,
    "returnRequestId": "RET-11111-20241107-abc",
    "status": "approved"
  },
  "needs_human_review": False,
  "workflow_complete": False,  # NOT complete yet!
  "follow_up_needed": True,    # Triggers cycle
  "follow_up_question": "ask_email_confirmation",
  "turn_count": 1,
  "response": "✅ **Refund Approved**\n\nYour refund request for order 11111 ($89.99) has been approved...\n\n**Would you like to receive an email confirmation?** (yes/no)"
}
```

**Neo4j Changes:**
```cypher
// Return request updated
MATCH (r:ReturnRequest {id: "RET-11111-20241107-abc"})
SET r.status = "approved"
SET r.approvedAt = datetime("2024-11-07T15:45:00Z")

// Order status updated
MATCH (o:Order {id: "11111"})
SET o.status = "Returned"
SET o.returnedAt = datetime("2024-11-07T15:45:00Z")

// Refund record created
CREATE (refund:Refund {
  id: "REFUND-11111-20241107-xyz",
  orderId: "11111",
  amount: 89.99,
  status: "processing"
})
```

**Response to User:**
```
🤖 ✅ Refund Approved

   Your refund request for order 11111 ($89.99) has been approved 
   and is being processed. The refund will be credited to your 
   original payment method within 5-7 business days.

   Would you like to receive an email confirmation? (yes/no)
```

**Key Point:** Workflow **continues** instead of terminating!

---

### Turn 3: User Responds "Yes" to Email

**User Input:** `"yes"`

**Flow:**
```
Start (new message in same conversation)
  → UserTask1 (extract entities - none)
  → RetrievalTask1 (skip)
  → LLMTask1 (follow_up_question="ask_email_confirmation" → intent="send_email_confirmation")
  → ToolTask1 (send email, set workflow_complete=True)
  → RouterTask1 (route to RenderTask1)
  → RenderTask1 (format confirmation)
  → END
```

**State Evolution:**

**After LLMTask1:**
```python
{
  "input": "yes",
  "intent": "send_email_confirmation",  # NEW intent
  "entities": {"orderId": "11111"},
  "follow_up_question": None,  # Cleared
  "follow_up_needed": False,   # Cleared
  "turn_count": 2
}
```

**After ToolTask1:**
```python
{
  "tool_result": {
    "success": True,
    "action": "email_sent",
    "orderId": "11111",
    "message": "Email confirmation sent for order 11111"
  },
  "workflow_complete": True  # NOW complete
}
```

**Response to User:**
```
🤖 ✅ Email confirmation sent for order 11111.

   You should receive a confirmation email shortly at alice.johnson@example.com.

   Is there anything else I can help you with?
```

**Workflow:** Terminates normally

---

### Turn 4 (Alternative): User Responds "No" to Email

**User Input:** `"no"`

**Flow:**
```
Start → UserTask1 → RetrievalTask1 → LLMTask1 (intent="skip_email_confirmation") 
      → ToolTask1 (set workflow_complete=True) 
      → RouterTask1 → RenderTask1 → END
```

**State:**
```python
{
  "input": "no",
  "intent": "skip_email_confirmation",
  "tool_result": {
    "success": True,
    "action": "email_skipped",
    "message": "No email will be sent"
  },
  "workflow_complete": True
}
```

**Response:**
```
🤖 Understood. No email will be sent.

   Your refund for order 11111 is being processed. 
   Is there anything else I can help you with?
```

---

### Turn 5 (Alternative): User Gives Unclear Response

**User Input:** `"maybe later"`

**Flow:**
```
Start → UserTask1 → RetrievalTask1 → LLMTask1 (intent="unclear_response") 
      → ToolTask1 (set follow_up_needed=True again) 
      → RouterTask1 (route to UserTask2 because follow-up needs clarification)
      → UserTask2 (ask again)
      → Route: follow_up_needed=True → LLMTask1 (CYCLE AGAIN!)
```

**State:**
```python
{
  "input": "maybe later",
  "intent": "unclear_response",
  "tool_result": {
    "success": False,
    "action": "clarification_needed",
    "message": "I didn't understand that. Please respond with yes or no."
  },
  "follow_up_needed": True,   # Set again
  "follow_up_question": "ask_email_confirmation",
  "workflow_complete": False
}
```

**Response:**
```
🤖 I didn't understand that. Please respond with yes or no.

   Would you like to receive an email confirmation for order 11111?
```

**Cycle:** Can continue until user provides clear response

---

## State Evolution

### Tracking State Through Multiple Cycles

| Turn | Input | Intent | needs_review | follow_up_needed | workflow_complete | Next Node |
|------|-------|--------|--------------|------------------|-------------------|-----------|
| **1** | "return order 11111" | refund | True | False | False | UserTask2 → END (pause) |
| **2** | "approve" | refund | False | **True** | False | UserTask2 → **LLMTask1** (cycle!) |
| **3** | "yes" | send_email_confirmation | False | False | **True** | RenderTask1 → END |

**Alternative Path (User says "no"):**
| Turn | Input | Intent | needs_review | follow_up_needed | workflow_complete | Next Node |
|------|-------|--------|--------------|------------------|-------------------|-----------|
| **1** | "return order 11111" | refund | True | False | False | UserTask2 → END (pause) |
| **2** | "approve" | refund | False | **True** | False | UserTask2 → **LLMTask1** (cycle!) |
| **3** | "no" | skip_email_confirmation | False | False | **True** | RenderTask1 → END |

**Alternative Path (Unclear response):**
| Turn | Input | Intent | needs_review | follow_up_needed | workflow_complete | Next Node |
|------|-------|--------|--------------|------------------|-------------------|-----------|
| **1** | "return order 11111" | refund | True | False | False | UserTask2 → END (pause) |
| **2** | "approve" | refund | False | **True** | False | UserTask2 → **LLMTask1** (cycle!) |
| **3** | "maybe later" | unclear_response | False | **True** | False | UserTask2 → **LLMTask1** (cycle again!) |
| **4** | "yes" | send_email_confirmation | False | False | **True** | RenderTask1 → END |

---

## Comparison with Linear Flows

### Linear Flow (Current Implementation)

**Order 11111 Refund:**
```
User: "return order 11111"
  → System: "Pending approval. Approve or reject?"
User: "approve"
  → System: "✅ Refund approved. Done." → END
```

**Turns:** 2  
**Cycles Used:** 0  
**Follow-up:** None

---

### Cyclic Flow (Proposed Implementation)

**Order 11111 Refund with Follow-up:**
```
User: "return order 11111"
  → System: "Pending approval. Approve or reject?"
User: "approve"
  → System: "✅ Refund approved. Want email confirmation?" (CYCLE to LLMTask1)
User: "yes"
  → System: "✅ Email sent. Done." → END
```

**Turns:** 3  
**Cycles Used:** 1 (UserTask2 → LLMTask1)  
**Follow-up:** Email confirmation question

---

### Performance Comparison

| Metric | Linear Flow | Cyclic Flow (1 cycle) | Cyclic Flow (2 cycles, unclear) |
|--------|-------------|----------------------|----------------------------------|
| **User Turns** | 2 | 3 | 4 |
| **Total Latency** | ~1.12s | ~1.85s | ~2.58s |
| **LLMTask1 Calls** | 1 | 2 | 3 |
| **UserTask2 Calls** | 1 | 1 | 2 |
| **Cycles Traversed** | 0 | 1 | 2 |
| **User Engagement** | Low | Medium | High |
| **Workflow Complexity** | Simple | Moderate | Complex |

---

## Benefits of Cyclic Flow

### 1. **Enhanced User Experience**
- More conversational interactions
- Proactive follow-up questions
- Natural multi-turn dialogues

### 2. **Reduced Context Switching**
- User stays in same conversation thread
- No need to start new queries
- Seamless continuation

### 3. **Additional Data Collection**
- Can ask clarifying questions
- Collect preferences (email, SMS, etc.)
- Gather feedback

### 4. **Flexible Workflows**
- Adapt to user responses dynamically
- Branch based on user choices
- Support complex multi-step processes

### 5. **Better Error Recovery**
- Re-ask unclear questions
- Provide examples
- Guide user to valid inputs

---

## Challenges & Considerations

### 1. **Infinite Loop Risk**

**Problem:** Without proper termination, cycle could loop forever

**Solution:**
- Max turn counter: `if turn_count > 5: workflow_complete = True`
- Timeout: Checkpoint expiry after 10 minutes
- Explicit termination flags: `workflow_complete`

```python
def user_task2_route(state: GraphState) -> Literal["LLMTask1", "__end__"]:
    turn_count = state.get("turn_count", 0)
    max_turns = 5
    
    if turn_count >= max_turns:
        print(f"[UserTask2] Max turns ({max_turns}) reached, terminating")
        return "__end__"
    
    # ... rest of routing logic
```

---

### 2. **State Management Complexity**

**Problem:** More state fields to track

**Solution:**
- Clear naming conventions: `follow_up_*`, `workflow_*`
- State validation: Check required fields before routing
- Logging: Debug state at each node

---

### 3. **User Confusion**

**Problem:** User might forget context after approval

**Solution:**
- Include context in follow-up: "For your refund on order 11111, would you like..."
- Provide escape hatch: "Type 'done' to finish"
- Show progress: "Step 2 of 2: Email confirmation"

---

### 4. **Debugging Difficulty**

**Problem:** Harder to trace multi-turn flows

**Solution:**
- Add turn counter to logs: `[Turn 3] LLMTask1: intent=send_email_confirmation`
- Checkpoint inspection: View state at each turn
- Conversation history: Store all messages

---

## Implementation Checklist

To enable cyclic flows in your application:

- [ ] Update `GraphState` TypedDict with `follow_up_needed`, `follow_up_question`, `turn_count`
- [ ] Modify `user_task2_node()` to set `follow_up_needed=True` after approval
- [ ] Update `user_task2_route()` to return `"LLMTask1"` when `follow_up_needed=True`
- [ ] Add follow-up handling in `llm_task_node()` to process follow-up intents
- [ ] Add new intents in `tool_task_node()`: `send_email_confirmation`, `skip_email_confirmation`
- [ ] Update `initial_state()` to initialize new fields
- [ ] Add turn counter increment logic
- [ ] Implement max turn limit safeguard
- [ ] Test multi-turn conversations thoroughly
- [ ] Update `README.md` with cyclic flow examples

---

## Summary

### Key Takeaways

1. **Cycle is Useful**: The `UserTask2 → LLMTask1` cycle enables rich multi-turn conversations
2. **Controlled Routing**: Use `follow_up_needed` flag to control cycle traversal
3. **Termination is Critical**: Always have clear termination conditions (`workflow_complete`, `max_turns`)
4. **Enhanced UX**: Follow-up questions provide better user experience
5. **Flexible Design**: Cycle supports various follow-up patterns (confirmation, cross-sell, feedback)

### Cyclic Flow Pattern

```
Initial Request (Turn 1)
  → HITL Approval (Turn 2)
  → Follow-up Question (Turn 3) ← CYCLE from UserTask2 to LLMTask1
  → Final Response (Turn 4)
  → END
```

### Use Cases Beyond Email Confirmation

1. **Shipping Address Update**: "Your refund is approved. Want to update your address for faster processing?"
2. **Priority Processing**: "We can expedite your refund for $5. Interested?"
3. **Feedback Collection**: "Refund processed. Can you tell us why you returned this item?"
4. **Related Orders**: "Refund approved for order 11111. I see you also ordered 12345. Need help with that too?"
5. **Upsell**: "Refund complete. We have a 20% discount on similar items. Want to browse?"

---

**For comparison, see:**
- `WORKFLOW.md` - Order 11111 linear HITL flow (cycle prevented)
- `WORKFLOW1.md` - Order 12345 non-HITL flows (no cycle)
- `workflow.json` - Topology definition with cycle connection
- `graph.py` - Implementation of cycle routing logic

