# graph.py
"""
LangGraph workflow orchestration for Microsoft Copilot workflow.json format.
"""
import json
import re
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, TypedDict
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI  # type: ignore[import]
from langgraph.graph import StateGraph, END  # type: ignore[import]
from langgraph.graph.message import add_messages  # type: ignore[import]
from langgraph.prebuilt import ToolNode  # type: ignore[import]
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage  # type: ignore[import]

# Import order tools
import sys
sys.path.insert(0, str(Path(__file__).parent))
from tools.order_tools import lookup_order_status, track_order, process_refund

load_dotenv()

# ============================================================================
# State Definition
# ============================================================================

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


# ============================================================================
# Helper Functions
# ============================================================================

def get_property_value(activity: Dict, prop_name: str, default: Any = None) -> Any:
    """Extract property value from activity Properties array."""
    props = activity.get("Properties", [])
    for prop in props:
        if prop.get("Name") == prop_name:
            return prop.get("Value", default)
    return default


def extract_entities(text: str) -> Dict[str, Any]:
    """Extract entities from user input using simple pattern matching."""
    entities = {}
    
    # Extract order IDs (5-digit numbers)
    order_match = re.search(r'\b(\d{5})\b', text)
    if order_match:
        entities["orderId"] = order_match.group(1)
    
    # Extract email addresses
    email_match = re.search(r'\b[\w\.-]+@[\w\.-]+\.\w+\b', text)
    if email_match:
        entities["email"] = email_match.group(0)
    
    return entities


def classify_intent(text: str, entities: Dict[str, Any]) -> str:
    """Classify user intent from input text."""
    text_lower = text.lower()
    order_id = entities.get("orderId")
    
    # Price-related queries
    if re.search(r'\b(price|cost|amount|total|how much|what.*price|what.*cost)\b', text_lower) and order_id:
        return "order_price"
    
    # Tracking queries
    if re.search(r'\b(track|tracking|where is|location|shipment)\b', text_lower) and order_id:
        return "track_order"
    
    # Status-related queries (includes carrier questions)
    if re.search(r'\b(status|check|what.*status|how.*order|carrier|shipper|shipping company)\b', text_lower) and order_id:
        return "order_status"
    
    # Refund queries
    if re.search(r'\b(refund|return|cancel.*order)\b', text_lower) and order_id:
        return "refund"
    
    # Fastener search
    if re.search(r'\b(fastener|screw|bolt|nut|hardware|part)\b', text_lower):
        return "fastener_search"
    
    # Policy questions
    if re.search(r'\b(policy|warranty|return.*policy|shipping.*policy)\b', text_lower):
        return "policy_question"
    
    # Default to chit_chat
    return "chit_chat"


# ============================================================================
# LLM Setup
# ============================================================================

llm = ChatOpenAI(
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # type: ignore[call-arg]
)


# ============================================================================
# Workflow Node Functions
# ============================================================================

def start_node(state: GraphState) -> GraphState:
    """Start node - entry point of the workflow."""
    print(f"[Start] Workflow started with input: {state.get('input', '')}")
    return state


def user_task_node(state: GraphState) -> GraphState:
    """User task node - handles user input."""
    input_text = state.get("input", "")
    print(f"[UserTask] Processing user input: {input_text}")
    
    # Extract entities and classify intent
    entities = extract_entities(input_text)
    intent = classify_intent(input_text, entities)
    
    state["entities"] = entities
    state["intent"] = intent
    
    return state


def retrieval_task_node(state: GraphState) -> GraphState:
    """Retrieval task node - retrieves relevant documents/data."""
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    
    print(f"[RetrievalTask] Retrieving data for intent: {intent}")
    
    # For policy questions, retrieve policy documents
    if intent == "policy_question":
        # In a real implementation, this would query Neo4j for policy documents
        retrieved = [
            {"type": "policy", "content": "Return policy: 30 days from purchase date."}
        ]
        state["retrieved"] = retrieved
    
    return state


def llm_task_node(state: GraphState) -> GraphState:
    """LLM task node - processes input with LLM for intent refinement."""
    input_text = state.get("input", "")
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    retrieved = state.get("retrieved", [])
    
    print(f"[LLMTask] Processing with LLM, intent: {intent}")
    
    # Build prompt
    prompt = f"""You are an AI assistant helping with order management.
User input: {input_text}
Detected intent: {intent}
Entities: {entities}

Refine the intent classification if needed. Possible intents:
- order_status: Check order status
- order_price: Get order price/cost
- track_order: Track order shipment
- refund: Process refund request
- fastener_search: Search for fasteners/hardware
- policy_question: Answer policy questions
- chit_chat: General conversation

Return the most appropriate intent and any additional entities you can extract.
Format: INTENT: <intent_name>, ENTITIES: <json_dict>"""

    try:
        messages = [
            SystemMessage(content="You are a helpful order management assistant."),
            HumanMessage(content=prompt)
        ]
        response = llm.invoke(messages)
        
        # Parse response
        response_text = response.content if hasattr(response, 'content') else str(response)
        if isinstance(response_text, list):
            response_text = str(response_text)
        
        # Extract intent from response
        intent_match = re.search(r'INTENT:\s*(\w+)', str(response_text), re.IGNORECASE)
        if intent_match:
            state["intent"] = intent_match.group(1).lower()
        
        # Extract entities from response
        entities_match = re.search(r'ENTITIES:\s*(\{.*\})', str(response_text), re.DOTALL)
        if entities_match:
            try:
                extracted_entities = json.loads(entities_match.group(1))
                state["entities"].update(extracted_entities)
            except:
                pass
        
        print(f"[LLMTask] Refined intent: {state.get('intent')}")
    except Exception as e:
        print(f"[LLMTask] Error: {e}")
    
    return state


def tool_task_node(state: GraphState) -> GraphState:
    """Tool task node - executes tools based on intent."""
    intent = state.get("intent", "")
    entities = state.get("entities", {})
    order_id = entities.get("orderId")
    input_text = state.get("input", "")
    
    print(f"[ToolTask] Executing tool for intent: {intent}, orderId: {order_id}")
    
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
                reason_match = re.search(r'(?:reason|because)[:\s]+(.+?)(?:\.|$)', input_text, re.IGNORECASE)
                if reason_match:
                    reason = reason_match.group(1).strip()

            tool_result = asyncio.run(process_refund(order_id, reason=reason))

            if tool_result and tool_result.get("needsHumanReview", False):
                state["needs_human_review"] = True
                state["review_message"] = tool_result.get("message", "Refund request requires approval.")
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
            print(f"[ToolTask] Tool result: {tool_result.get('status', 'N/A')}, needs_review: {state.get('needs_human_review', False)}")
    except Exception as e:
        print(f"[ToolTask] Error executing tool: {e}")
        state["tool_result"] = {"error": str(e)}

    return state
        

def router_task_node(state: GraphState) -> GraphState:
    """Router task node - routes to next activity based on conditions."""  #conditional branching logic
    intent = state.get("intent", "")
    needs_review = state.get("needs_human_review", False)
    tool_result = state.get("tool_result")
    
    print(f"[RouterTask] Routing based on intent: {intent}, needs_review: {needs_review}")
    
    # Simple routing logic
    # In a real implementation, this would use routingConditions from workflow.json
    if needs_review:
        state["current_activity"] = "UserTask2"  # Route to human review
    elif intent in ["order_status", "order_price", "track_order", "policy_question", "chit_chat"]:
        state["current_activity"] = "RenderTask1"  # Route to render
    elif intent == "fastener_search":
        state["current_activity"] = "AgentTask1"  # Route to agent
    else:
        state["current_activity"] = "RenderTask1"  # Default to render
    
    return state


def render_task_node(state: GraphState) -> GraphState:
    """Render task node - formats and returns response."""
    intent = state.get("intent", "")
    tool_result = state.get("tool_result")
    input_text = state.get("input", "")
    needs_review = state.get("needs_human_review", False)
    
    print(f"[RenderTask] Formatting response for intent: {intent}, needs_review: {needs_review}")
    
    # If human review is needed, don't render here - let UserTask2 handle it
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
                    if name and name != "Unknown":
                        response += f"- {name}: {qty} × ${float(price):,.2f} = ${float(qty * price):,.2f}\n"
        else:
            response = f"Price information not available for order {order_id}."
    
    elif intent == "track_order" and tool_result:
        order_id = tool_result.get("id") or tool_result.get("orderId", "unknown")
        tracking = tool_result.get("trackingNumber") or tool_result.get("tracking") or tool_result.get("tracking_number") or "N/A"
        status = tool_result.get("status", "Unknown")
        history = tool_result.get("tracking_history", [])
        
        response = f"**Tracking for Order {order_id}**\n"
        response += f"Tracking Number: {tracking}\n"
        response += f"Status: {status}\n"
        if history:
            response += "\n**Tracking History:**\n"
            for event in history[:5]:  # Show last 5 events
                location = event.get("location", "N/A")
                event_status = event.get("status", "N/A")
                date = event.get("date", "N/A")
                response += f"- {date}: {location} - {event_status}\n"
    
    elif intent == "policy_question":
        response = "Our return policy allows returns within 30 days of purchase. Shipping is free for orders over $50."
    
    elif intent == "chit_chat":
        response = "Please provide the order details so I can assist you more effectively!"
    
    else:
        response = build_default_response(intent or "", state, tool_result)
    
    state["response"] = response
    return state


def build_default_response(intent: str, state: GraphState, tool_result: Optional[Dict[str, Any]]) -> str:
    if intent == "refund" and tool_result:
        order_id = state.get("entities", {}).get("orderId", "the order")
        if tool_result.get("success") and tool_result.get("requiresApproval"):
            if state.get("redirect_url"):
                return "You're eligible to return order {order_id}."
            return tool_result.get(
                "message",
                "This order isn't eligible for a return right now. Let me know if you need anything else."
            )
        return tool_result.get(
            "message",
            "This order isn't eligible for a return right now. Let me know if you need anything else."
        )
    return "I'm processing your request. Please wait..."


def agent_task_node(state: GraphState) -> GraphState:
    """Agent task node - complex reasoning for fastener search."""
    input_text = state.get("input", "")
    retrieved = state.get("retrieved", [])
    
    print(f"[AgentTask] Processing complex query: {input_text}")
    
    prompt = f"""You are helping a customer search for fasteners and hardware parts.
User query: {input_text}

Provide helpful information about fasteners, screws, bolts, and hardware parts.
Be specific and helpful."""
    
    try:
        messages = [
            SystemMessage(content="You are a fastener and hardware expert."),
            HumanMessage(content=prompt)
        ]
        response = llm.invoke(messages)
        response_text = response.content if hasattr(response, 'content') else str(response)
        if isinstance(response_text, list):
            response_text = str(response_text)
        state["response"] = response_text
    except Exception as e:
        print(f"[AgentTask] Error: {e}")
        state["response"] = "I apologize, but I encountered an error processing your fastener search."
    
    return state


def user_task2_node(state: GraphState) -> GraphState:
    """User task 2 node - human review/approval for refund requests."""
    human_input = state.get("human_input")
    tool_result = state.get("tool_result")
    input_text = state.get("input", "")
    
    # Use human_input if available, otherwise check input_text
    user_response = human_input or input_text
    
    print(f"[UserTask2] Human review for refund, input: {user_response}")
    
    # Check if this is a refund request
    is_refund = tool_result and (
        tool_result.get("refundId") or 
        tool_result.get("returnRequestId") or
        "refund" in str(tool_result).lower()
    )
    
    if is_refund and tool_result:
        return_request_id = tool_result.get("returnRequestId") or tool_result.get("refundId")
        order_id = tool_result.get("orderId")
        amount = tool_result.get("amount", 0.0)
        
        # Check user response for approval/rejection
        if user_response and user_response.lower().strip() in ["yes", "y", "approve", "confirm", "approved"]:
            # Approval granted - approve the return request
            import asyncio
            from tools.order_tools import approve_return

            try:
                approval_result = asyncio.run(approve_return(return_request_id, approved=True))

                if approval_result and approval_result.get("success", False):
                    state["needs_human_review"] = False
                    state["workflow_complete"] = True  # Mark workflow as complete
                    state["response"] = (
                        f"✅ **Refund Approved**\n\nYour refund request for order {order_id} (${amount:,.2f}) has been "
                        "approved and is being processed. The refund will be credited to your original payment method within "
                        "5-7 business days."
                    )
                else:
                    state["needs_human_review"] = False
                    state["workflow_complete"] = True  # Mark workflow as complete
                    state["response"] = "❌ Error approving refund request. Please contact support."
            except Exception as e:
                print(f"[UserTask2] Error approving refund: {e}")
                state["needs_human_review"] = False
                state["response"] = f"❌ Error processing approval: {str(e)}"

        elif user_response and user_response.lower().strip() in ["no", "n", "reject", "cancel", "rejected"]:
            # Rejection - reject the return request
            import asyncio
            from tools.order_tools import approve_return

            try:
                rejection_result = asyncio.run(approve_return(return_request_id, approved=False))

                if rejection_result and rejection_result.get("success", False):
                    state["needs_human_review"] = False
                    state["workflow_complete"] = True  # Mark workflow as complete
                    state["response"] = (
                        f"❌ **Refund Rejected**\n\nYour refund request for order {order_id} has been rejected. "
                        "If you have questions, please contact customer support."
                    )
                else:
                    state["needs_human_review"] = False
                    state["workflow_complete"] = True  # Mark workflow as complete
                    state["response"] = f"Your refund request for order {order_id} has been cancelled."
            except Exception as e:
                print(f"[UserTask2] Error rejecting refund: {e}")
                state["needs_human_review"] = False
                state["workflow_complete"] = True  # Mark workflow as complete
                state["response"] = f"Your refund request for order {order_id} has been cancelled."

        else:
            # Still waiting for human input - show approval request (will pause here)
            state["needs_human_review"] = True
            reason = tool_result.get('reason', 'Customer request') if tool_result else 'Customer request'
            state["response"] = (
                "⏳ **Refund Request Pending Approval**\n\n"
                f"**Order ID:** {order_id}\n"
                f"**Amount:** ${amount:,.2f}\n"
                f"**Reason:** {reason}\n\n"
                "Please **approve** or **reject** this refund request:\n"
                "- Type 'approve' or 'yes' to approve\n"
                "- Type 'reject' or 'no' to reject"
            )
    else:
        # Not a refund, handle other review cases
        if user_response and user_response.lower() in ["yes", "y", "approve", "confirm"]:
            state["needs_human_review"] = False
            state["workflow_complete"] = True
            state["response"] = "Your request has been approved and is being processed."
        elif user_response and user_response.lower() in ["no", "n", "reject", "cancel"]:
            state["needs_human_review"] = False
            state["workflow_complete"] = True
            state["response"] = "Your request has been cancelled."
        else:
            state["needs_human_review"] = True
            state["response"] = "Please approve or reject this request."
    
    return state


# ============================================================================
# Graph Builder
# ============================================================================

def build_from_copilot_json(json_path: str | Path = "workflow.json", checkpointer: Any = None) -> StateGraph:
    """
    Build a LangGraph workflow from the Microsoft Copilot-style workflow.json.
    The JSON describes the workflow topology; this function wires those shapes
    to the Python node implementations defined earlier in this module.
    
    Args:
        json_path: Path to workflow.json file.
        checkpointer: Optional LangGraph checkpointer.
    
    Returns:
        Compiled StateGraph ready for execution.
    """
    workflow_path = Path(json_path)
    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow file not found: {json_path}")

    with workflow_path.open("r", encoding="utf-8") as f:
        workflow = json.load(f)

    activities: List[Dict[str, Any]] = workflow.get("WorkflowActivities", [])
    connections: List[Dict[str, Any]] = workflow.get("WorkflowConnections", [])
    start_id: str = workflow.get("StartActivityId", "1")

    workflow_graph = StateGraph(GraphState)

    # Map activity names to node implementations
    activity_handlers: Dict[str, Any] = {
        "Start": start_node,
        "UserTask1": user_task_node,
        "UserTask2": user_task2_node,
        "RetrievalTask1": retrieval_task_node,
        "LLMTask1": llm_task_node,
        "ToolTask1": tool_task_node,
        "RouterTask1": router_task_node,
        "RenderTask1": render_task_node,
        "AgentTask1": agent_task_node,
    }

    # Build node map keyed by activity id → graph node name
    node_map: Dict[str, str] = {}
    for activity in activities:
        activity_id = activity["Id"]
        activity_name = activity["Name"]
        handler = activity_handlers.get(activity_name)

        if handler is None:
            raise ValueError(f"No handler defined for activity '{activity_name}'")

        if activity_name in node_map.values():
            # Ensure unique graph node names (append suffix if duplicate name encountered)
            suffix = 2
            unique_name = f"{activity_name}_{suffix}"
            while unique_name in node_map.values():
                suffix += 1
                unique_name = f"{activity_name}_{suffix}"
            node_name = unique_name
        else:
            node_name = activity_name

        workflow_graph.add_node(node_name, handler)
        node_map[activity_id] = node_name

    # Track nodes that already have conditional edges configured
    conditional_nodes: set[str] = set()

    # Record outgoing connections for determining terminal nodes
    outgoing: Dict[str, List[str]] = {}

    for connection in connections:
        source_id = connection["SourceActivityId"]
        target_id = connection["TargetActivityId"]

        source_node = node_map.get(source_id)
        target_node = node_map.get(target_id)

        if not source_node or not target_node:
            continue

        outgoing.setdefault(source_node, []).append(target_node)

        if source_node == "RouterTask1":
            if source_node in conditional_nodes:
                continue

            def route_condition(state: GraphState) -> Literal["RenderTask1", "AgentTask1", "UserTask2"]:
                next_activity = state.get("current_activity", "RenderTask1")
                if next_activity == "AgentTask1":
                    return "AgentTask1"
                if next_activity == "UserTask2":
                    return "UserTask2"
                return "RenderTask1"

            workflow_graph.add_conditional_edges(
                source_node,
                route_condition,
                {
                    "RenderTask1": "RenderTask1",
                    "AgentTask1": "AgentTask1",
                    "UserTask2": "UserTask2",
                },
            )
            conditional_nodes.add(source_node)
        elif source_node == "UserTask2":
            # Add conditional edge for UserTask2 to handle cycle breaking
            if source_node in conditional_nodes:
                continue

            def user_task2_route(state: GraphState) -> Literal["LLMTask1", "__end__"]:
                # If review is complete (user provided input and review flag is cleared), end
                # Otherwise, loop back to LLMTask1
                needs_review = state.get("needs_human_review", False)
                if needs_review:
                    # Still waiting for input, end the workflow (pause for HITL)
                    return "__end__"
                else:
                    # Review complete, can loop back for follow-up if needed
                    # But for now, terminate to avoid infinite loops
                    return "__end__"

            workflow_graph.add_conditional_edges(
                source_node,
                user_task2_route,
                {
                    "LLMTask1": target_node,
                    "__end__": END,
                },
            )
            conditional_nodes.add(source_node)
        else:
            workflow_graph.add_edge(source_node, target_node)

    # Set entry point
    start_node_name = node_map.get(start_id)
    if not start_node_name:
        raise ValueError(f"Start activity id '{start_id}' not found in workflow.")
    workflow_graph.set_entry_point(start_node_name)

    # Automatically connect terminal nodes (no outgoing edges) to END
    for node_name in node_map.values():
        if node_name not in outgoing:
            workflow_graph.add_edge(node_name, END)

    # Compile graph
    if checkpointer:
        return workflow_graph.compile(checkpointer=checkpointer)
    return workflow_graph.compile()


def build_graph(checkpointer: Any = None) -> StateGraph:
    """
    Build workflow graph from workflow.json.
    Automatically detects format (Copilot or standard LangGraph).
    
    Args:
        checkpointer: Optional checkpointer for state persistence
    
    Returns:
        Compiled StateGraph
    """
    workflow_path = Path("workflow.json")
    if not workflow_path.exists():
        raise FileNotFoundError("workflow.json not found")
    
    with open(workflow_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # Detect format
    if "WorkflowActivities" in config and "StartActivityId" in config:
        # Microsoft Copilot format
        return build_from_copilot_json(workflow_path, checkpointer)
    else:
        raise ValueError("Unsupported workflow format. Expected Microsoft Copilot format.")


def initial_state(input_text: str, channel: str = "chat") -> GraphState:
    """
    Create initial state for the workflow.
    
    Args:
        input_text: User input message
        channel: Communication channel (chat, email, etc.)
    
    Returns:
        Initial GraphState
    """
    return GraphState(
        messages=[HumanMessage(content=input_text)],
        input=input_text,
        channel=channel,
        intent=None,
        entities={},
        tool_result=None,
        retrieved=[],
        needs_human_review=False,
        human_input=None,
        response=None,
        current_activity=None,
        workflow_data=None,
        review_message=None,
        redirect_url=None,
        workflow_complete=False
    )

