# graph.py
import os
import re
import json
from pathlib import Path
from typing import TypedDict, Literal, Callable, Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END  # type: ignore[import]
from neo4j_module import retrieve_docs
from tools.order_tools import lookup_order_status, track_order, process_refund

load_dotenv(override=True)

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY is not set in environment variables")

model = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)  # type: ignore[call-arg]


class GraphState(TypedDict):
    """State structure passed between workflow nodes."""
    input: str
    user_input: str
    channel: str
    intent: str | None
    entities: dict
    query: dict | None
    parsed_query: str | None
    isFastenerSearch: bool
    tool_result: dict | None
    agent_result: dict | None
    retrieved: list
    response: str | None
    needs_human_review: bool
    human_input: str | None
    review_message: str | None


# ============================================================================
# Helper Functions
# ============================================================================

def extract_content(res: Any) -> str:
    """Extract text content from LangChain response object."""
    if isinstance(res.content, str):
        return res.content
    elif isinstance(res.content, list) and len(res.content) > 0:
        first_item = res.content[0]
        if isinstance(first_item, str):
            return first_item
        return getattr(first_item, 'text', str(first_item))
    return str(res.content) if res.content else ""


def parse_json_safe(text: str, default: Any = None) -> Any:
    """Safely parse JSON, return default on error."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from text
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        return default


def update_state(state: GraphState, **updates: Any) -> GraphState:
    """Update state with new values."""
    return {**state, **updates}  # type: ignore


# ============================================================================
# Classification Helpers
# ============================================================================

class IntentClassifier:
    """Handles intent classification using heuristics."""
    
    FASTENER_KEYWORDS = [
        "fastener", "screw", "bolt", "nut", "washer", "rivet", "pin",
        "thread", "threaded", "hardware", "part", "parts", "component",
        "pem", "standoff", "spacer", "helical", "helicoil", "clinch"
    ]
    
    @staticmethod
    def extract_order_id(text: str) -> str | None:
        """Extract order ID from text."""
        match = re.search(r"order\s*#?\s*(\d+)", text, re.IGNORECASE)
        if match:
            return match.group(1)
        num_match = re.search(r"\b(\d{4,})\b", text)
        return num_match.group(1) if num_match else None
    
    @staticmethod
    def classify_intent(state: GraphState, input_lower: str) -> tuple[str, dict]:
        """Classify intent using keyword patterns."""
        intent = "chit_chat"
        entities = {}
        order_id = IntentClassifier.extract_order_id(state.get("input", ""))
        
        if re.search(r"\b(price|cost|amount|total|how much|what.*price|what.*cost)\b", input_lower) and order_id:
            intent = "order_price"
            entities["orderId"] = order_id
        elif re.search(r"\b(track|tracking|where is|shipment|delivery status)\b", input_lower):
            intent = "track_order"
            if order_id:
                entities["orderId"] = order_id
        elif re.search(r"\b(refund|return money|get money back|cancel order)\b", input_lower):
            intent = "refund"
            if order_id:
                entities["orderId"] = order_id
            reason_match = re.search(r"reason[:\s]+(.+?)(?:\.|$|because)", input_lower)
            if reason_match:
                entities["reason"] = reason_match.group(1).strip()
        elif re.search(r"\b(check|status|order status)\b", input_lower) and order_id:
            intent = "order_status"
            entities["orderId"] = order_id
        elif order_id:
            intent = "order_status"
            entities["orderId"] = order_id
        elif re.search(r"warranty|shipping|return policy|policy", input_lower):
            intent = "policy_question"
        
        return intent, entities
    
    @staticmethod
    def is_fastener_search(input_lower: str) -> bool:
        """Check if input contains fastener-related keywords."""
        return any(keyword in input_lower for keyword in IntentClassifier.FASTENER_KEYWORDS)


# ============================================================================
# Prompt Builders
# ============================================================================

class PromptBuilder:
    """Builds prompts for LLM tasks."""
    
    @staticmethod
    def build_intent_prompt(input_text: str) -> list:
        """Build prompt for intent classification."""
        return [
            {
                "role": "system",
                "content": (
                    "You are an intent classifier + entity extractor. "
                    "Possible intents: order_status, order_price, track_order, refund, policy_question, chit_chat, fastener_search.\n"
                    "- order_status: Check order status (ONLY when user asks about status, not price)\n"
                    "- order_price: Get price/cost/amount/total/how much/what price for an order (USE THIS when user asks about price, cost, amount, total, or how much)\n"
                    "- track_order: Track shipping/delivery status\n"
                    "- refund: Request refund for an order\n"
                    "- policy_question: Questions about policies (warranty, shipping, returns)\n"
                    "- chit_chat: General conversation\n"
                    "- fastener_search: User is searching for fasteners, screws, bolts, nuts, or hardware parts\n"
                    "IMPORTANT: If user asks about 'price', 'cost', 'amount', 'total', 'how much', or 'what price' for an order, you MUST use 'order_price' intent, NOT 'order_status'.\n"
                    "If user mentions an order, try to extract an orderId (numbers).\n"
                    "For refund requests, also extract reason if mentioned.\n"
                    "Also determine if the user is searching for fasteners (isFastenerSearch: true/false).\n"
                    "Return strict JSON: {intent: string, entities: object, isFastenerSearch: boolean}"
                )
            },
            {"role": "user", "content": input_text}
        ]
    
    @staticmethod
    def build_fastener_intent_prompt(input_text: str) -> list:
        """Build prompt for fastener intent classification."""
        return [
            {
                "role": "system",
                "content": (
                    "Classify whether this user query is related to fastener search and give the output as a Boolean "
                    "with true value if the user wants to search fasteners and false in any other case.\n"
                    "Return strict JSON: {isFastenerSearch: boolean}"
                )
            },
            {"role": "user", "content": f"User query: {input_text}"}
        ]
    
    @staticmethod
    def build_fastener_search_prompt(user_input: str) -> list:
        """Build prompt for fastener search query generation."""
        return [
            {
                "role": "system",
                "content": (
                    "You are a fastener search query generator. Generate a JSON query for searching fastener parts.\n"
                    "Return ONLY valid JSON in format: {\"generated_query\": {...query...}}\n"
                    "The query should filter parts by name property using 'like' operator.\n"
                    "Always set itemType to \"part\".\n"
                    "Normalize user input to match allowed values. Return only valid JSON, no commentary."
                )
            },
            {"role": "user", "content": user_input}
        ]
    
    @staticmethod
    def build_chat_render_prompt(input_text: str, context: str) -> list:
        """Build prompt for chat response generation."""
        return [
            {
                "role": "system",
                "content": "You are a helpful assistant. Combine tool results and the brief doc snippets to answer clearly in 3-5 sentences."
            },
            {"role": "user", "content": f"User asked: {input_text}\n\n{context}"}
        ]
    
    @staticmethod
    def build_email_render_prompt(input_text: str, tool_result: dict | None, retrieved: list) -> list:
        """Build prompt for email response generation."""
        return [
            {
                "role": "system",
                "content": "You are an assistant writing concise, polite emails with subject and body. Output JSON: {subject, body}"
            },
            {
                "role": "user",
                "content": (
                    f"User wants an email-ready response to: \"{input_text}\". "
                    f"Tool: {json.dumps(tool_result)}. "
                    f"Top docs: {json.dumps(retrieved[:2])}"
                )
            }
        ]


# ============================================================================
# Response Formatters
# ============================================================================

class ResponseFormatter:
    """Formats tool results and responses."""
    
    @staticmethod
    def format_order_status(tool_result: dict) -> str:
        """Format order status result."""
        order_id = tool_result.get("id") or tool_result.get("orderId") or tool_result.get("order_id", "unknown")
        status = tool_result.get("status", "Unknown")
        text = f"Your order {order_id} is currently **{status}**."
        
        if tool_result.get("carrier"):
            text += f" It's being shipped via {tool_result['carrier']}."
        tracking = tool_result.get("tracking") or tool_result.get("trackingNumber")
        if tracking:
            text += f" Tracking number: {tracking}."
        expected_delivery = tool_result.get("expectedDelivery") or tool_result.get("estimatedDelivery")
        if expected_delivery:
            # Format date nicely
            if isinstance(expected_delivery, str):
                text += f" Expected delivery date: {expected_delivery}."
            else:
                text += f" Expected delivery date: {str(expected_delivery)}."
        
        # Add order date if available
        order_date = tool_result.get("orderDate")
        if order_date:
            text += f" Order placed on: {order_date}."
        
        # Add total amount/price if available
        total_amount = tool_result.get("totalAmount")
        if total_amount is not None:
            try:
                amount = float(total_amount)
                text += f" Total amount: **${amount:,.2f}**."
            except (ValueError, TypeError):
                text += f" Total amount: **${total_amount}**."
        
        # Add items if available
        items = tool_result.get("items", [])
        if items and len(items) > 0:
            text += f" Order contains {len(items)} item(s)."
        
        return text
    
    @staticmethod
    def format_track_order(tool_result: dict) -> str:
        """Format track order result."""
        order_id = tool_result.get("orderId") or tool_result.get("id") or tool_result.get("order_id", "unknown")
        status = tool_result.get("status", "in transit")
        text = f"Order {order_id} is currently **{status}**."
        
        tracking = tool_result.get("trackingNumber") or tool_result.get("tracking")
        if tracking:
            text += f" Tracking number: {tracking}."
        
        if tool_result.get("carrier"):
            text += f" Carrier: {tool_result['carrier']}."
        
        if tool_result.get("currentLocation"):
            text += f" Current location: {tool_result['currentLocation']}."
        
        estimated = tool_result.get("estimatedDelivery") or tool_result.get("expectedDelivery")
        if estimated:
            if isinstance(estimated, str):
                text += f" Estimated delivery: {estimated}."
            else:
                text += f" Estimated delivery: {str(estimated)}."
        
        # Add tracking history if available
        tracking_history = tool_result.get("trackingHistory", [])
        if tracking_history and len(tracking_history) > 0:
            text += f"\n\nTracking history:"
            for i, event in enumerate(tracking_history[:5], 1):  # Show last 5 events
                location = event.get("location", "Unknown")
                event_status = event.get("status", "Unknown")
                date = event.get("date", "")
                date_str = str(date).split('T')[0] if date else ""
                text += f"\n{i}. {event_status} - {location}"
                if date_str:
                    text += f" ({date_str})"
        
        return text
    
    @staticmethod
    def format_refund(tool_result: dict) -> str:
        """Format refund result."""
        order_id = tool_result.get("orderId") or tool_result.get("id") or tool_result.get("order_id", "unknown")
        refund_id = tool_result.get("refundId") or tool_result.get("refund_id", "")
        status = tool_result.get("status", "processing")
        text = f"Your refund request for order {order_id} has been received and is {status.lower()}."
        
        if refund_id:
            text += f" Refund ID: {refund_id}."
        if tool_result.get("amount"):
            text += f" Amount: ${tool_result['amount']}."
        if tool_result.get("estimatedProcessingTime"):
            text += f" Estimated processing time: {tool_result['estimatedProcessingTime']}."
        if tool_result.get("message"):
            text += f" {tool_result['message']}"
        
        return text
    
    @staticmethod
    def format_order_price(tool_result: dict) -> str:
        """Format order price result."""
        order_id = tool_result.get("id") or tool_result.get("orderId") or tool_result.get("order_id", "unknown")
        total_amount = tool_result.get("totalAmount")
        
        if total_amount is not None:
            try:
                amount = float(total_amount)
                text = f"The total price for order {order_id} is **${amount:,.2f}**."
            except (ValueError, TypeError):
                text = f"The total price for order {order_id} is **${total_amount}**."
        else:
            text = f"I couldn't find the price for order {order_id}."
        
        # Add item details if available
        items = tool_result.get("items", [])
        if items and len(items) > 0:
            text += f"\n\nOrder contains {len(items)} item(s):"
            for item in items:
                item_name = item.get("name", "Unknown item")
                item_qty = item.get("quantity", 1)
                item_price = item.get("price", 0)
                try:
                    item_total = float(item_price) * float(item_qty)
                    text += f"\n- {item_name} (Qty: {item_qty}) × ${float(item_price):,.2f} = ${item_total:,.2f}"
                except (ValueError, TypeError):
                    text += f"\n- {item_name} (Qty: {item_qty}) × ${item_price}"
        
        return text
    
    @staticmethod
    def format_tool_response(intent: str, tool_result: dict) -> str:
        """Format tool result based on intent."""
        formatters = {
            "order_status": ResponseFormatter.format_order_status,
            "order_price": ResponseFormatter.format_order_price,
            "track_order": ResponseFormatter.format_track_order,
            "refund": ResponseFormatter.format_refund
        }
        
        formatter = formatters.get(intent)
        if formatter:
            result = formatter(tool_result)
            print(f"[format_tool_response] Intent: {intent}, Formatter result length: {len(result) if result else 0}")
            return result
        else:
            return f"I found: {json.dumps(tool_result, indent=2)}"
    
    @staticmethod
    def build_context(tool_result: dict | None, retrieved: list | None) -> str:
        """Build context string from tool results and documents."""
        parts = []
        
        if tool_result:
            parts.append(f"TOOL_RESULT: {json.dumps(tool_result)}")
        
        if retrieved:
            doc_text = "\n".join([
                f"- {d.get('title', 'Unknown')}: {d.get('body', '')[:180]}…"
                for d in retrieved if isinstance(d, dict)
            ])
            if doc_text:
                parts.append(f"DOCS: {doc_text}")
        
        return "\n".join(parts) if parts else "No additional context available."


# ============================================================================
# LLM Task Handler
# ============================================================================

class LLMTaskHandler:
    """Handles LLM invocations with fallback."""
    
    def __init__(self, model: ChatOpenAI):
        self.model = model
        self.call_count = 0
        self.error_count = 0
    
    async def invoke_with_fallback(self, prompt: list, fallback: Callable[[], Any], task_name: str = "unknown") -> str:
        """Invoke LLM with fallback function on error."""
        self.call_count += 1
        print(f"\n[LLM] [{task_name}] Attempting LLM call #{self.call_count}")
        print(f"[LLM] [{task_name}] Prompt length: {len(str(prompt))} chars")
        
        try:
            print(f"[LLM] [{task_name}] Calling model.ainvoke...")
            res = await self.model.ainvoke(prompt)
            print(f"[LLM] [{task_name}] Model call successful")
            print(f"[LLM] [{task_name}] Response type: {type(res)}")
            
            content = extract_content(res)
            print(f"[LLM] [{task_name}] Extracted content length: {len(content) if content else 0} chars")
            print(f"[LLM] [{task_name}] Content preview: {content[:100] if content else 'None'}...")
            
            if not content or content.strip() == "":
                print(f"[LLM] [{task_name}] WARNING: Empty response from LLM, using fallback")
                return await fallback()
            
            return content
        except Exception as e:
            self.error_count += 1
            print(f"\n[LLM] [{task_name}] ERROR #{self.error_count}: {type(e).__name__}: {str(e)}")
            import traceback
            print(f"[LLM] [{task_name}] Traceback:")
            traceback.print_exc()
            print(f"[LLM] [{task_name}] Using fallback function\n")
            return await fallback()


# ============================================================================
# Workflow Tasks
# ============================================================================

class WorkflowTasks:
    """Handles all workflow task nodes."""
    
    def __init__(self, model: ChatOpenAI):
        self.llm = LLMTaskHandler(model)
    
    async def llm_task(self, state: GraphState) -> GraphState:
        """Intent classification and entity extraction."""
        input_text = state.get("input", "") or state.get("user_input", "")
        input_lower = input_text.lower()
        defaults = {"intent": "chit_chat", "entities": {}, "isFastenerSearch": False}
        
        # Extract order ID first (before LLM call)
        order_id = IntentClassifier.extract_order_id(input_text)
        print(f"[llm_task] Input: {input_text}, Extracted order ID: {order_id}")
        
        async def fallback():
            intent, entities = IntentClassifier.classify_intent(state, input_lower)
            is_fastener = IntentClassifier.is_fastener_search(input_lower)
            
            # Add order ID to entities if found
            if order_id and not entities.get("orderId"):
                entities["orderId"] = order_id
            
            return json.dumps({"intent": intent, "entities": entities, "isFastenerSearch": is_fastener})
        
        prompt = PromptBuilder.build_intent_prompt(input_text)
        text = await self.llm.invoke_with_fallback(prompt, fallback, "llm_task")
        
        parsed = parse_json_safe(text, defaults)
        
        # Ensure orderId is always extracted if present
        if order_id:
            parsed.setdefault("entities", {})["orderId"] = order_id
        
        # Post-process: Override intent if price keywords are detected (priority check)
        if order_id and re.search(r"\b(price|cost|amount|total|how much|what.*price|what.*cost)\b", input_lower):
            parsed["intent"] = "order_price"
            parsed.setdefault("entities", {})["orderId"] = order_id
            print(f"[llm_task] Overriding intent to 'order_price' based on price keywords")
        
        print(f"[llm_task] Parsed intent: {parsed.get('intent')}, entities: {parsed.get('entities')}")
        
        return update_state(
            state,
            intent=parsed.get("intent", defaults["intent"]),
            entities=parsed.get("entities", defaults["entities"]),
            isFastenerSearch=parsed.get("isFastenerSearch", defaults["isFastenerSearch"])
        )
    
    async def tool_task(self, state: GraphState) -> GraphState:
        """Execute external tools based on intent."""
        intent = state.get("intent")
        order_id = state.get("entities", {}).get("orderId") or IntentClassifier.extract_order_id(state.get("input", ""))
        
        print(f"[tool_task] Intent: {intent}, Order ID: {order_id}")
        
        tool_map = {
            "order_status": lookup_order_status,
            "order_price": lookup_order_status,  # Price uses same tool as order_status
            "track_order": track_order,
            "refund": lambda oid, reason=None: process_refund(oid, reason)
        }
        
        if intent not in tool_map:
            print(f"[tool_task] Intent '{intent}' not in tool_map, skipping tool execution")
            return state
        
        tool_func = tool_map[intent]
        print(f"[tool_task] Executing tool for intent: {intent}")
        
        try:
            if intent == "refund":
                reason = state.get("entities", {}).get("reason")
                tool_result = await tool_func(order_id, reason)
            else:
                tool_result = await tool_func(order_id)
            
            print(f"[tool_task] Tool result: {tool_result}")
            if tool_result is None:
                print(f"[tool_task] WARNING: Tool returned None for order_id: {order_id}")
            elif isinstance(tool_result, dict):
                print(f"[tool_task] Tool result keys: {list(tool_result.keys())}")
            
            return update_state(state, tool_result=tool_result)
        except Exception as e:
            print(f"[tool_task] ERROR executing tool: {e}")
            import traceback
            traceback.print_exc()
            return update_state(state, tool_result=None)
    
    async def agent_task(self, state: GraphState) -> GraphState:
        """Determine if document retrieval is needed."""
        intent = state.get("intent") or ""
        need_docs = intent in ["policy_question", "order_status", "track_order", "refund"]
        
        doc_queries = {
            "refund": "refund return policy",
            "track_order": "shipping delivery policy",
            "order_status": "shipping return policy"
        }
        
        doc_query = doc_queries.get(intent, state.get("input", "")) if intent else state.get("input", "")
        return update_state(state, agent_result={"needDocs": need_docs, "docQuery": doc_query})
    
    async def retriever_task(self, state: GraphState) -> GraphState:
        """Query Neo4j for relevant documents."""
        agent_result = state.get("agent_result")
        if not agent_result or not agent_result.get("needDocs"):
            return state
        
        doc_query = agent_result.get("docQuery", state.get("input", ""))
        docs = await retrieve_docs(doc_query, 3)
        return update_state(state, retrieved=docs)
    
    async def user_task1(self, state: GraphState) -> GraphState:
        """Initial user input collection task."""
        # UserTask1 is the entry point - it already has user_input in state
        # Just ensure user_input is set from input if not already set
        user_input = state.get("user_input") or state.get("input", "")
        return update_state(state, user_input=user_input)
    
    async def user_task2(self, state: GraphState) -> GraphState:
        """Human-in-the-loop node for review/feedback, loops back to LLMTask."""
        # Check if human input is provided
        human_input = state.get("human_input")
        needs_review = state.get("needs_human_review", False)
        
        if needs_review and not human_input:
            # Request human review - set review message
            review_message = state.get("review_message") or "Please review and provide feedback"
            return update_state(
                state,
                review_message=review_message,
                needs_human_review=True
            )
        
        # If human input is provided, update user_input and continue
        if human_input:
            # Update user_input with human feedback for reprocessing
            updated_input = f"{state.get('user_input', '')} [Review feedback: {human_input}]"
            return update_state(
                state,
                user_input=updated_input,
                input=updated_input,
                needs_human_review=False,
                review_message=None
            )
        
        # No review needed, continue
        return update_state(state, needs_human_review=False)
    
    async def human_review_task(self, state: GraphState) -> GraphState:
        """Handle human approval for refunds."""
        if state.get("intent") != "refund":
            return update_state(state, needs_human_review=False)
        
        order_id = state.get("entities", {}).get("orderId", "unknown")
        tool_result = state.get("tool_result") or {}
        refund_amount = tool_result.get("amount", "unknown") if isinstance(tool_result, dict) else "unknown"
        
        review_message = (
            f"⚠️ Approval Required: Refund request for order {order_id} "
            f"amounting to ${refund_amount}. Do you want to proceed? (yes/no)"
        )
        
        human_input = (state.get("human_input") or "").lower().strip()
        if human_input in ["yes", "y", "approve", "confirm"]:
            return update_state(state, needs_human_review=False, review_message=None)
        elif human_input:
            return update_state(
                state,
                needs_human_review=False,
                response="Refund request has been cancelled.",
                review_message=None
            )
        
        return update_state(
            state,
            needs_human_review=True,
            review_message=review_message,
            response=review_message
        )
    
    async def render_chat(self, state: GraphState) -> GraphState:
        """Render chat-style response."""
        # If we already have a response and need human review, return as is
        if state.get("response") and state.get("needs_human_review"):
            return state
        
        # Check if we have tool_result or parsed_query - prioritize these
        tool_result = state.get("tool_result")
        parsed_query = state.get("parsed_query")
        intent = state.get("intent")
        
        print(f"[render_chat] tool_result: {tool_result}, intent: {intent}")
        
        # If we have tool_result, format it directly (highest priority)
        # For order_price intent, ALWAYS use the formatter, don't let LLM override
        if tool_result and isinstance(tool_result, dict):
            intent_type = intent or ""
            print(f"[render_chat] Formatting tool result with intent: {intent_type}, tool_result keys: {list(tool_result.keys())}")
            print(f"[render_chat] totalAmount in tool_result: {tool_result.get('totalAmount')}")
            
            # For order_price intent, force use of formatter
            if intent_type == "order_price":
                print(f"[render_chat] order_price intent detected, calling format_order_price")
                print(f"[render_chat] tool_result totalAmount: {tool_result.get('totalAmount')}")
                print(f"[render_chat] tool_result items: {tool_result.get('items')}")
                formatted = ResponseFormatter.format_order_price(tool_result)
                print(f"[render_chat] format_order_price returned: '{formatted[:300] if formatted else 'EMPTY/NONE'}'")
                if formatted and formatted.strip():
                    print(f"[render_chat] Returning formatted order_price response immediately (length: {len(formatted)})")
                    return update_state(state, response=formatted)
                else:
                    print(f"[render_chat] ERROR: order_price formatter returned empty/None, trying fallback")
                    # Try to create a basic price response from tool_result
                    total_amount = tool_result.get("totalAmount")
                    order_id = tool_result.get("id") or tool_result.get("orderId", "unknown")
                    if total_amount is not None:
                        try:
                            amount = float(total_amount)
                            fallback_text = f"The total price for order {order_id} is **${amount:,.2f}**."
                        except:
                            fallback_text = f"The total price for order {order_id} is **${total_amount}**."
                        print(f"[render_chat] Using fallback price response: {fallback_text}")
                        return update_state(state, response=fallback_text)
            
            # For other intents, use general formatter
            formatted = ResponseFormatter.format_tool_response(intent_type, tool_result)
            if formatted and formatted.strip():
                print(f"[render_chat] Using formatted tool result response: {formatted[:200]}")
                return update_state(state, response=formatted)
            else:
                print(f"[render_chat] WARNING: Formatter returned empty string for intent: {intent_type}")
        
        # Handle None tool_result for order queries - order not found
        if tool_result is None and intent in ["order_status", "order_price", "track_order"]:
            order_id = state.get("entities", {}).get("orderId") or IntentClassifier.extract_order_id(state.get("input", ""))
            text = f"I couldn't find order {order_id} in our system. Please verify the order ID or ensure the order data has been loaded into Neo4j using the 'Load Order Data' button in the System Management panel."
            print(f"[render_chat] Order not found response: {text}")
            return update_state(state, response=text)
        
        # If we have parsed_query (fastener search), create response
        if parsed_query and parsed_query != "{}":
            try:
                query_obj = json.loads(parsed_query) if isinstance(parsed_query, str) else parsed_query
                if query_obj and query_obj != {}:
                    response = f"I found fastener search results based on your query. Here are the matching items."
                    print(f"[render_chat] Using parsed_query response")
                    return update_state(state, response=response)
            except:
                pass
        
        # For order_price intent, NEVER let LLM override - use formatter or fallback
        # This should not be reached if the formatter above worked, but as a safety check
        if intent == "order_price" and tool_result and isinstance(tool_result, dict):
            print(f"[render_chat] order_price intent detected, using fallback formatter instead of LLM")
            text = self._generate_fallback_response(state)
            # Return immediately - don't let LLM override
            return update_state(state, response=text)
        
        # Always ensure we generate a response (but NOT for order_price - it should have returned above)
        try:
            context = ResponseFormatter.build_context(state.get("tool_result"), state.get("retrieved", []))
            prompt = PromptBuilder.build_chat_render_prompt(state.get("input", ""), context)
            
            async def fallback():
                return self._generate_fallback_response(state)
            
            text = await self.llm.invoke_with_fallback(prompt, fallback, "render_chat")
            if not text or text.strip() == "":
                print(f"[render_chat] Empty response from LLM, using fallback")
                text = self._generate_fallback_response(state)
        except Exception as e:
            print(f"[render_chat] Error: {e}, using fallback")
            import traceback
            traceback.print_exc()
            text = self._generate_fallback_response(state)
        
        # Final safety check - always have a response
        if not text or text.strip() == "":
            # Last resort - check if we have any information
            if tool_result and isinstance(tool_result, dict):
                text = f"Your request has been processed. {json.dumps(tool_result, indent=2)}"
            elif tool_result is None and intent in ["order_status", "track_order"]:
                # Order not found in Neo4j
                order_id = state.get("entities", {}).get("orderId", "the order")
                text = f"I couldn't find {order_id} in our system. Please verify the order ID or ensure the data has been loaded into Neo4j using data.cypher."
            elif intent:
                text = f"I've processed your {intent} request. How can I help you further?"
            else:
                text = "I've processed your request. How can I help you further?"
        
        return update_state(state, response=text)
    
    async def render_email(self, state: GraphState) -> GraphState:
        """Render email-style response."""
        try:
            prompt = PromptBuilder.build_email_render_prompt(
                state.get("input", ""),
                state.get("tool_result"),
                state.get("retrieved", [])
            )
            
            async def fallback():
                subject = f"Regarding your {state.get('intent', 'request')}"
                tool_result = state.get("tool_result")
                body = f"Thank you for your inquiry. {json.dumps(tool_result)}" if tool_result else "Thank you for reaching out."
                return json.dumps({"subject": subject, "body": body})
            
            text = await self.llm.invoke_with_fallback(prompt, fallback, "render_email")
            parsed = parse_json_safe(text, {"subject": "Regarding your request", "body": "Thank you for reaching out."})
            
            subject = parsed.get("subject", "Regarding your request")
            body = parsed.get("body", "Thank you for reaching out.")
            compiled = f"Subject: {subject}\n\n{body}"
        except Exception as e:
            print(f"[render_email] Error: {e}, using fallback")
            import traceback
            traceback.print_exc()
            subject = f"Regarding your {state.get('intent', 'request')}"
            body = "Thank you for reaching out. I've processed your request."
            compiled = f"Subject: {subject}\n\n{body}"
        
        return update_state(state, response=compiled)
    
    async def fastener_intent_classifier(self, state: GraphState) -> GraphState:
        """Check if user is searching for fasteners."""
        input_text = state.get("input", "")
        prompt = PromptBuilder.build_fastener_intent_prompt(input_text)
        
        async def fallback():
            is_fastener = IntentClassifier.is_fastener_search(input_text.lower())
            return json.dumps({"isFastenerSearch": is_fastener})
        
        text = await self.llm.invoke_with_fallback(prompt, fallback, "fastener_intent_classifier")
        parsed = parse_json_safe(text, {"isFastenerSearch": False})
        
        return update_state(state, isFastenerSearch=parsed.get("isFastenerSearch", False))
    
    async def fastener_search(self, state: GraphState) -> GraphState:
        """Generate fastener search query."""
        prompt = PromptBuilder.build_fastener_search_prompt(state.get("input", ""))
        
        async def fallback():
            return "{}"
        
        text = await self.llm.invoke_with_fallback(prompt, fallback, "fastener_search")
        parsed = parse_json_safe(text, {})
        
        if "generated_query" in parsed:
            parsed_query = json.dumps(parsed["generated_query"])
        else:
            parsed_query = text if text.startswith("{") else "{}"
        
        return update_state(state, parsed_query=parsed_query)
    
    async def error_handler(self, state: GraphState) -> GraphState:
        """Handle non-fastener queries."""
        return update_state(state, response="I'm not trained to respond to this query")
    
    async def display_items_table(self, state: GraphState) -> GraphState:
        """Display fastener search results."""
        parsed_query = state.get("parsed_query", "{}")
        if parsed_query and parsed_query != "{}":
            response = f"I found fastener search results based on your query. Here are the matching items:\n\n{parsed_query}"
        else:
            response = "I searched for fasteners, but couldn't find matching results. Please try refining your search criteria."
        return update_state(state, response=response)
    
    def _generate_fallback_response(self, state: GraphState) -> str:
        """Generate fallback response from tool results or documents."""
        tool_result = state.get("tool_result")
        if tool_result and isinstance(tool_result, dict):
            intent = state.get("intent") or ""
            return ResponseFormatter.format_tool_response(intent, tool_result)
        
        retrieved = state.get("retrieved", [])
        if retrieved and isinstance(retrieved, list) and len(retrieved) > 0:
            first_doc = retrieved[0] if isinstance(retrieved[0], dict) else {}
            title = first_doc.get("title", "documentation") or "documentation"
            body = first_doc.get("body", "")
            if body:
                preview = body.split(". ")[0] + "." if ". " in body else body[:200]
                return f"According to our {title.lower()}, {preview}"
            return f"I found information in our {title.lower()}."
        
        return "I'm here to help! Could you please rephrase your question or provide more details?"


# ============================================================================
# Router Functions
# ============================================================================

class WorkflowRouters:
    """Handles router functions for conditional edges."""
    
    @staticmethod
    def workflow_router(state: GraphState) -> Literal["ToolTask", "FastenerIntentClassifier"]:
        """Route to main workflow or fastener search workflow."""
        return "FastenerIntentClassifier" if state.get("isFastenerSearch", False) else "ToolTask"
    
    @staticmethod
    def needs_review_router(state: GraphState) -> Literal["HumanReviewTask", "RetrieverTask"]:
        """Route to HumanReviewTask for refunds, otherwise RetrieverTask."""
        return "HumanReviewTask" if state.get("intent", "") == "refund" else "RetrieverTask"
    
    @staticmethod
    def should_render_router(state: GraphState) -> Literal["RenderTaskChat", "RenderTaskEmail"]:
        """Route to appropriate render task based on channel."""
        return "RenderTaskEmail" if state.get("channel") == "email" else "RenderTaskChat"
    
    @staticmethod
    def fastener_search_router(state: GraphState) -> Literal["FastenerSearch", "ErrorHandler"]:
        """Route to fastener search or error handler."""
        return "FastenerSearch" if state.get("isFastenerSearch", False) else "ErrorHandler"
    
    @staticmethod
    def llm_task_router(state: GraphState) -> Literal["ToolTask", "UserTask2"]:
        """Route to ToolTask if no review needed, or to UserTask2 if review needed."""
        # Note: The conditional edge routes directly to ToolTask or UserTask2
        # WorkflowRouter is reached via direct edge from LLMTask
        needs_review = state.get("needs_human_review", False)
        return "UserTask2" if needs_review else "ToolTask"
    
    @staticmethod
    def router_task1_router(state: GraphState) -> Literal["RenderTaskChat", "AgentTask"]:
        """Route to RenderTaskChat for simple intents, or AgentTask for complex intents."""
        intent = state.get("intent", "")
        simple_intents = ["order_status", "track_order", "policy_question", "chit_chat"]
        return "RenderTaskChat" if intent in simple_intents else "AgentTask"
    
    # Alias for backward compatibility
    router = should_render_router


# ============================================================================
# Graph Builder
# ============================================================================

class GraphBuilder:
    """Handles graph construction from JSON or hardcoded structure."""
    
    ROUTER_NODES = {"WorkflowRouter", "FastenerSearchRouter", "RouterTask1"}
    
    def __init__(self, tasks: WorkflowTasks, routers: WorkflowRouters):
        self.tasks = tasks
        self.routers = routers
        self.node_mapping = self._build_node_mapping()
    
    def _build_node_mapping(self) -> dict[str, Callable[..., Any] | None]:
        """Build mapping of node names to functions."""
        return {
            "UserTask1": self.tasks.user_task1,
            "UserTask2": self.tasks.user_task2,
            "LLMTask": self.tasks.llm_task,
            "ToolTask": self.tasks.tool_task,
            "AgentTask": self.tasks.agent_task,
            "RetrieverTask": self.tasks.retriever_task,
            "HumanReviewTask": self.tasks.human_review_task,
            "RenderTaskChat": self.tasks.render_chat,
            "RenderTaskEmail": self.tasks.render_email,
            "FastenerIntentClassifier": self.tasks.fastener_intent_classifier,
            "FastenerSearch": self.tasks.fastener_search,
            "ErrorHandler": self.tasks.error_handler,
            "DisplayItemsTable": self.tasks.display_items_table,
            "WorkflowRouter": None,
            "FastenerSearchRouter": None,
            "RouterTask1": None,
            "router": self.routers.router,
            "should_render_router": self.routers.should_render_router,
            "needs_review_router": self.routers.needs_review_router,
            "workflow_router": self.routers.workflow_router,
            "fastener_search_router": self.routers.fastener_search_router,
            "llm_task_router": self.routers.llm_task_router,
            "router_task1_router": self.routers.router_task1_router
        }
    
    def build_from_json(self, json_path: str | Path = "workflow.json", checkpointer: Any = None):
        """Build LangGraph workflow from JSON configuration."""
        json_path = Path(json_path)
        if not json_path.exists():
            raise FileNotFoundError(f"Workflow JSON file not found: {json_path}")
        
        with open(json_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        # Build router node mapping (router node -> actual source node)
        router_mapping = self._build_router_mapping(config)
        
        graph = StateGraph(GraphState)
        self._add_nodes(graph, config)
        self._set_entry_point(graph, config)
        self._add_edges(graph, config)
        self._add_conditional_edges(graph, config, router_mapping)
        
        return graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    
    def _build_router_mapping(self, config: dict) -> dict[str, str]:
        """Map router nodes to their actual source nodes."""
        mapping = {}
        edges = config.get("edges", [])
        
        for edge in edges:
            from_node = edge["from"]
            to_node = edge["to"]
            if to_node in self.ROUTER_NODES:
                mapping[to_node] = from_node
        
        return mapping
    
    def _add_nodes(self, graph: StateGraph, config: dict):
        """Add nodes to graph from configuration."""
        for node_config in config.get("nodes", []):
            node_name = node_config["name"]
            if node_name in self.ROUTER_NODES:
                continue
            
            if node_name not in self.node_mapping:
                raise ValueError(f"Node function '{node_name}' not found")
            if self.node_mapping[node_name] is None:
                raise ValueError(f"Node function '{node_name}' is None")
            
            graph.add_node(node_name, self.node_mapping[node_name])
    
    def _set_entry_point(self, graph: StateGraph, config: dict):
        """Set graph entry point."""
        entry_point = config.get("entry_point")
        if not entry_point:
            raise ValueError("Workflow JSON missing 'entry_point'")
        graph.set_entry_point(entry_point)
        
    def _add_edges(self, graph: StateGraph, config: dict):
        """Add direct edges to graph."""
        conditional_nodes = {edge["from"] for edge in config.get("conditional_edges", [])}
        
        for edge in config.get("edges", []):
            from_node, to_node = edge["from"], edge["to"]
            
            # Skip edges from/to router nodes (they're handled by conditional edges)
            if from_node in self.ROUTER_NODES or to_node in self.ROUTER_NODES:
                continue
            
            # Skip edges from nodes that have conditional edges (routers)
            if from_node in conditional_nodes:
                continue
            
            target = END if to_node == "END" else to_node
            graph.add_edge(from_node, target)
    
    def _add_conditional_edges(self, graph: StateGraph, config: dict, router_mapping: dict):
        """Add conditional edges to graph."""
        for cond_edge in config.get("conditional_edges", []):
            from_node = cond_edge["from"]
            
            # If from_node is a router, find the actual source node
            if from_node in router_mapping:
                from_node = router_mapping[from_node]
            
            router_func_name = cond_edge.get("router_function")
            routes = cond_edge.get("routes", {})
            
            if router_func_name not in self.node_mapping:
                raise ValueError(f"Router function '{router_func_name}' not found")
            
            router_func = self.node_mapping[router_func_name]
            if router_func is None:
                raise ValueError(f"Router function '{router_func_name}' is None")
            
            graph.add_conditional_edges(from_node, router_func, routes)
    
    def build_from_copilot_json(self, json_path: str | Path = "workflow.json", checkpointer: Any = None):
        """
        Build LangGraph workflow from Microsoft Copilot workflow.json format.
        
        This method handles the format with:
        - WorkflowActivities: List of activities with Id, Name, Type, Properties
        - WorkflowConnections: List of connections with SourceActivityId, TargetActivityId
        - StartActivityId: Entry point activity ID
        
        Args:
            json_path: Path to workflow.json file
            checkpointer: Optional checkpointer for state persistence
            
        Returns:
            Compiled LangGraph workflow
        """
        json_path = Path(json_path)
        if not json_path.exists():
            raise FileNotFoundError(f"Workflow JSON file not found: {json_path}")
        
        with open(json_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        activities = config.get("WorkflowActivities", [])
        connections = config.get("WorkflowConnections", [])
        start_activity_id = str(config.get("StartActivityId", ""))
        
        if not activities:
            raise ValueError("Workflow JSON missing 'WorkflowActivities'")
        
        # Build ID to Name mapping and Name to node function mapping
        id_to_name = {}
        name_to_node_func = {}
        
        for activity in activities:
            activity_id = str(activity.get("Id", ""))
            activity_name = activity.get("Name", "")
            activity_type = activity.get("Type", "")
            
            # Skip Start activity (it's just a marker)
            if activity_type == "Start":
                continue
            
            id_to_name[activity_id] = activity_name
            
            # Map activity name to node function
            # Handle variations like "LLMTask1" -> "LLMTask"
            node_name = self._normalize_node_name(activity_name)
            
            if node_name not in self.node_mapping:
                print(f"Warning: Node '{node_name}' (from activity '{activity_name}') not found in node_mapping")
                continue
            
            node_func = self.node_mapping[node_name]
            if node_func is None:
                # Router node - will be handled separately
                continue
            
            name_to_node_func[activity_name] = node_func
        
        # Build graph
        graph = StateGraph(GraphState)
        
        # Add nodes
        for activity_name, node_func in name_to_node_func.items():
            graph.add_node(activity_name, node_func)
        
        # Find entry point (first activity after Start)
        entry_point_name = None
        if start_activity_id:
            # Find the activity that Start connects to
            for conn in connections:
                if str(conn.get("SourceActivityId", "")) == start_activity_id:
                    target_id = str(conn.get("TargetActivityId", ""))
                    entry_point_name = id_to_name.get(target_id)
                    break
        
        # If no entry point found, use first non-Start activity
        if not entry_point_name:
            for activity in activities:
                if activity.get("Type") != "Start":
                    entry_point_name = activity.get("Name")
                    break
        
        if not entry_point_name:
            raise ValueError("Could not determine entry point from workflow")
        
        graph.set_entry_point(entry_point_name)
        
        # Build connection mapping and identify router connections
        connection_map = {}
        router_connections = {}  # Maps router node name -> [targets]
        router_sources = {}  # Maps router node name -> source node name
        
        for conn in connections:
            source_id = str(conn.get("SourceActivityId", ""))
            target_id = str(conn.get("TargetActivityId", ""))
            
            # Skip Start activity connections (already handled)
            if source_id == start_activity_id:
                continue
            
            source_name = id_to_name.get(source_id)
            target_name = id_to_name.get(target_id)
            
            if not source_name or not target_name:
                continue
            
            # Check if source is a router node
            normalized_source = self._normalize_node_name(source_name)
            normalized_target = self._normalize_node_name(target_name)
            
            if normalized_source in self.ROUTER_NODES:
                # This connection goes FROM a router node
                if source_name not in router_connections:
                    router_connections[source_name] = []
                router_connections[source_name].append(target_name)
            elif normalized_target in self.ROUTER_NODES:
                # This connection goes TO a router node - store the source
                router_sources[target_name] = source_name
            else:
                # Regular connection
                if source_name not in connection_map:
                    connection_map[source_name] = []
                connection_map[source_name].append(target_name)
        
        # Handle router nodes: add conditional edges from the source node that connects to the router
        for router_name, target_names in router_connections.items():
            source_node = router_sources.get(router_name)
            if not source_node:
                print(f"Warning: Router node {router_name} has no source node, skipping")
                continue
            
            normalized_router = self._normalize_node_name(router_name)
            
            if normalized_router == "RouterTask1":
                # RouterTask1 uses router_task1_router
                router_func = self.node_mapping.get("router_task1_router")
                if router_func:
                    # Build routes mapping
                    routes = {}
                    for target_name in target_names:
                        # Map to expected route values based on router function return values
                        if "RenderTask" in target_name or "Render" in target_name:
                            routes["RenderTaskChat"] = target_name
                        elif "Agent" in target_name:
                            routes["AgentTask"] = target_name
                        else:
                            routes[target_name] = target_name
                    
                    graph.add_conditional_edges(source_node, router_func, routes)
                else:
                    # Fallback: direct edge to first target
                    if target_names:
                        graph.add_edge(source_node, target_names[0] if target_names[0] != "END" else END)
            else:
                # Other router types - use default routing
                if target_names:
                    graph.add_edge(source_node, target_names[0] if target_names[0] != "END" else END)
        
        # Add regular edges
        for source_name, target_names in connection_map.items():
            if len(target_names) == 1:
                # Simple edge
                target = target_names[0]
                graph.add_edge(source_name, END if target == "END" else target)
            else:
                # Multiple targets - need to determine routing logic
                # For now, route to first target (could be enhanced with conditions)
                print(f"Warning: Multiple targets for {source_name}, routing to first: {target_names[0]}")
                graph.add_edge(source_name, target_names[0] if target_names[0] != "END" else END)
        
        # Add END edges for nodes that don't have outgoing connections
        all_sources = set(connection_map.keys())
        all_targets = set()
        for targets in connection_map.values():
            all_targets.update(targets)
        
        # Also include targets from router connections
        for targets in router_connections.values():
            all_targets.update(targets)
        
        # Nodes that are targets but not sources should end
        terminal_nodes = all_targets - all_sources
        for node_name in terminal_nodes:
            if node_name in name_to_node_func:
                graph.add_edge(node_name, END)
        
        return graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()
    
    def _normalize_node_name(self, activity_name: str) -> str:
        """
        Normalize activity name to match node_mapping keys.
        
        Examples:
        - "LLMTask1" -> "LLMTask"
        - "ToolTask1" -> "ToolTask"
        - "RenderTask1" -> "RenderTaskChat" (default)
        - "RouterTask1" -> "RouterTask1"
        """
        # Remove trailing numbers
        normalized = re.sub(r'\d+$', '', activity_name)
        
        # Special mappings
        if normalized == "LLMTask":
            return "LLMTask"
        elif normalized == "ToolTask":
            return "ToolTask"
        elif normalized == "AgentTask":
            return "AgentTask"
        elif normalized == "RetrievalTask" or normalized == "RetrieverTask":
            return "RetrieverTask"
        elif normalized == "RenderTask":
            # Default to RenderTaskChat, but could be determined by Properties
            return "RenderTaskChat"
        elif normalized == "RouterTask":
            return "RouterTask1"
        elif activity_name.startswith("UserTask"):
            return activity_name  # Keep as is (UserTask1, UserTask2)
        else:
            # Try to match directly or return normalized
            return normalized if normalized in self.node_mapping else activity_name
    
    def build_hardcoded(self, checkpointer: Any = None):
        """Build graph using hardcoded structure (fallback)."""
        graph = StateGraph(GraphState)
        
        nodes = [
            "LLMTask", "ToolTask", "AgentTask", "RetrieverTask",
            "RenderTaskChat", "RenderTaskEmail"
        ]
        for node in nodes:
            graph.add_node(node, self.node_mapping[node])
        
        graph.set_entry_point("LLMTask")
        graph.add_edge("LLMTask", "ToolTask")
        graph.add_edge("ToolTask", "AgentTask")
        graph.add_edge("AgentTask", "RetrieverTask")
        
        graph.add_conditional_edges(
            "RetrieverTask",
            self.routers.router,
            {"RenderTaskChat": "RenderTaskChat", "RenderTaskEmail": "RenderTaskEmail"}
        )
        
        graph.add_edge("RenderTaskChat", END)
        graph.add_edge("RenderTaskEmail", END)
        
        return graph.compile(checkpointer=checkpointer) if checkpointer else graph.compile()


# ============================================================================
# Initialization & Public API
# ============================================================================

_tasks = WorkflowTasks(model)
_routers = WorkflowRouters()
_builder = GraphBuilder(_tasks, _routers)


def initial_state(input_text: str, channel: str = "chat") -> GraphState:
    """Create initial state for the workflow graph."""
    return {
        "input": input_text,
        "user_input": input_text,
        "channel": channel or "chat",
        "intent": None,
        "entities": {},
        "query": None,
        "parsed_query": None,
        "isFastenerSearch": False,
        "tool_result": None,
        "agent_result": None,
        "retrieved": [],
        "response": None,
        "needs_human_review": False,
        "human_input": None,
        "review_message": None
    }


def build_graph_from_json(json_path: str | Path = "workflow.json", checkpointer: Any = None):
    """Build graph from JSON workflow definition."""
    return _builder.build_from_json(json_path, checkpointer)


def build_graph(checkpointer: Any = None):
    """Build workflow graph from JSON if available, otherwise use hardcoded structure."""
    try:
        # Check if workflow.json exists and detect format
        workflow_path = Path("workflow.json")
        if workflow_path.exists():
            with open(workflow_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            
            # Check if it's Copilot format (has WorkflowActivities) or standard format (has entry_point)
            if "WorkflowActivities" in config and "StartActivityId" in config:
                # Use Copilot format parser
                return _builder.build_from_copilot_json(workflow_path, checkpointer)
            elif "entry_point" in config and "nodes" in config:
                # Use standard format parser
                return _builder.build_from_json(workflow_path, checkpointer)
            else:
                # Try standard format first, fall back to Copilot if it fails
                try:
                    return _builder.build_from_json(workflow_path, checkpointer)
                except (ValueError, KeyError):
                    return _builder.build_from_copilot_json(workflow_path, checkpointer)
        else:
            # No workflow.json, try standard build
            return _builder.build_from_json(checkpointer=checkpointer)
    except FileNotFoundError:
        return _builder.build_hardcoded(checkpointer=checkpointer)
    except Exception as e:
        print(f"[build_graph] Error building from JSON: {e}")
        print(f"[build_graph] Falling back to hardcoded structure")
        return _builder.build_hardcoded(checkpointer=checkpointer)


# ============================================================================
# Workflow Orchestration Functions
# ============================================================================

def orchestrate_workflow(
    input_text: str,
    channel: str = "chat",
    conversation_id: str = "default",
    workflow_json_path: str | Path = "workflow.json",
    checkpointer: Any = None,
    human_input: str | None = None
) -> dict[str, Any]:
    """
    Orchestrate a complete workflow execution from workflow.json.
    
    This function:
    1. Loads the workflow configuration from JSON
    2. Builds the LangGraph workflow
    3. Creates initial state
    4. Executes the workflow
    5. Returns the final result
    
    Args:
        input_text: User's input message
        channel: Communication channel ("chat" or "email")
        conversation_id: Conversation identifier for checkpointing
        workflow_json_path: Path to workflow.json file
        checkpointer: Optional checkpointer for state persistence
        human_input: Optional human input for review steps
    
    Returns:
        Dictionary containing the final workflow state with keys:
        - response: Final response text
        - intent: Detected intent
        - entities: Extracted entities
        - isFastenerSearch: Whether this was a fastener search
        - parsed_query: Parsed query (for fastener search)
        - tool_result: Tool execution results
        - retrieved: Retrieved documents
        - needs_human_review: Whether human review is needed
        - review_message: Review message if needed
        - All other state fields
    
    Example:
        >>> result = orchestrate_workflow(
        ...     "Check order status for order 12345",
        ...     channel="chat",
        ...     conversation_id="conv-001"
        ... )
        >>> print(result["response"])
        "Your order 12345 is currently shipped..."
    """
    try:
        # Load and validate workflow JSON
        workflow_path = Path(workflow_json_path)
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow JSON file not found: {workflow_path}")
        
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_config = json.load(f)
        
        print(f"[Orchestrate] Loading workflow from: {workflow_path}")
        print(f"[Orchestrate] Workflow name: {workflow_config.get('name', 'unknown')}")
        print(f"[Orchestrate] Entry point: {workflow_config.get('entry_point', 'unknown')}")
        
        # Build the graph
        print(f"[Orchestrate] Building graph from JSON...")
        compiled_graph = _builder.build_from_json(workflow_path, checkpointer)
        print(f"[Orchestrate] Graph built successfully")
        
        # Create initial state
        state = initial_state(input_text, channel)
        
        # Add human input if provided (for review steps)
        if human_input:
            state["human_input"] = human_input
        
        # Prepare configuration for checkpointing
        config = {"configurable": {"thread_id": conversation_id}} if checkpointer else {}
        
        # Execute the workflow
        print(f"[Orchestrate] Executing workflow with input: {input_text[:50]}...")
        print(f"[Orchestrate] Channel: {channel}, Conversation ID: {conversation_id}")
        
        result = compiled_graph.invoke(state, config)
        
        print(f"[Orchestrate] Workflow execution completed")
        print(f"[Orchestrate] Final state keys: {list(result.keys())}")
        
        # Return the result
        return dict(result)
        
    except FileNotFoundError as e:
        print(f"[Orchestrate] ERROR: {e}")
        # Fallback to hardcoded workflow
        print(f"[Orchestrate] Falling back to hardcoded workflow structure")
        compiled_graph = _builder.build_hardcoded(checkpointer)
        state = initial_state(input_text, channel)
        if human_input:
            state["human_input"] = human_input
        config = {"configurable": {"thread_id": conversation_id}} if checkpointer else {}
        result = compiled_graph.invoke(state, config)
        return dict(result)
        
    except Exception as e:
        print(f"[Orchestrate] ERROR: {e}")
        import traceback
        traceback.print_exc()
        # Return error state
        return {
            "input": input_text,
            "user_input": input_text,
            "channel": channel,
            "response": f"Error executing workflow: {str(e)}",
            "intent": None,
            "entities": {},
            "error": str(e)
        }


async def orchestrate_workflow_async(
    input_text: str,
    channel: str = "chat",
    conversation_id: str = "default",
    workflow_json_path: str | Path = "workflow.json",
    checkpointer: Any = None,
    human_input: str | None = None
) -> dict[str, Any]:
    """
    Async version of orchestrate_workflow for use in async contexts.
    
    Same functionality as orchestrate_workflow but uses ainvoke for async execution.
    
    Args:
        input_text: User's input message
        channel: Communication channel ("chat" or "email")
        conversation_id: Conversation identifier for checkpointing
        workflow_json_path: Path to workflow.json file
        checkpointer: Optional checkpointer for state persistence
        human_input: Optional human input for review steps
    
    Returns:
        Dictionary containing the final workflow state
    
    Example:
        >>> result = await orchestrate_workflow_async(
        ...     "Check order status for order 12345",
        ...     channel="chat"
        ... )
        >>> print(result["response"])
    """
    try:
        # Load and validate workflow JSON
        workflow_path = Path(workflow_json_path)
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow JSON file not found: {workflow_path}")
        
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_config = json.load(f)
        
        print(f"[Orchestrate] Loading workflow from: {workflow_path}")
        print(f"[Orchestrate] Workflow name: {workflow_config.get('name', 'unknown')}")
        print(f"[Orchestrate] Entry point: {workflow_config.get('entry_point', 'unknown')}")
        
        # Build the graph
        print(f"[Orchestrate] Building graph from JSON...")
        compiled_graph = _builder.build_from_json(workflow_path, checkpointer)
        print(f"[Orchestrate] Graph built successfully")
        
        # Create initial state
        state = initial_state(input_text, channel)
        
        # Add human input if provided (for review steps)
        if human_input:
            state["human_input"] = human_input
        
        # Prepare configuration for checkpointing
        config = {"configurable": {"thread_id": conversation_id}} if checkpointer else {}
        
        # Execute the workflow asynchronously
        print(f"[Orchestrate] Executing workflow (async) with input: {input_text[:50]}...")
        print(f"[Orchestrate] Channel: {channel}, Conversation ID: {conversation_id}")
        
        result = await compiled_graph.ainvoke(state, config)
        
        print(f"[Orchestrate] Workflow execution completed")
        print(f"[Orchestrate] Final state keys: {list(result.keys())}")
        
        # Return the result
        return dict(result)
        
    except FileNotFoundError as e:
        print(f"[Orchestrate] ERROR: {e}")
        # Fallback to hardcoded workflow
        print(f"[Orchestrate] Falling back to hardcoded workflow structure")
        compiled_graph = _builder.build_hardcoded(checkpointer)
        state = initial_state(input_text, channel)
        if human_input:
            state["human_input"] = human_input
        config = {"configurable": {"thread_id": conversation_id}} if checkpointer else {}
        result = await compiled_graph.ainvoke(state, config)
        return dict(result)
        
    except Exception as e:
        print(f"[Orchestrate] ERROR: {e}")
        import traceback
        traceback.print_exc()
        # Return error state
        return {
            "input": input_text,
            "user_input": input_text,
            "channel": channel,
            "response": f"Error executing workflow: {str(e)}",
            "intent": None,
            "entities": {},
            "error": str(e)
        }


# ============================================================================
# Workflow Configuration Helper Functions
# ============================================================================

def load_workflow_config(workflow_json_path: str | Path = "workflow.json") -> dict[str, Any]:
    """
    Load and validate workflow configuration from JSON file.
    
    Args:
        workflow_json_path: Path to workflow.json file
    
    Returns:
        Dictionary containing the workflow configuration
    
    Raises:
        FileNotFoundError: If workflow JSON file doesn't exist
        ValueError: If workflow JSON is invalid or missing required fields
    
    Example:
        >>> config = load_workflow_config("workflow.json")
        >>> print(config["entry_point"])
        "UserTask1"
    """
    workflow_path = Path(workflow_json_path)
    if not workflow_path.exists():
        raise FileNotFoundError(f"Workflow JSON file not found: {workflow_path}")
    
    with open(workflow_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # Validate required fields
    if "entry_point" not in config:
        raise ValueError("Workflow JSON missing 'entry_point' field")
    
    if "nodes" not in config:
        raise ValueError("Workflow JSON missing 'nodes' field")
    
    return config


def validate_workflow_config(config: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validate workflow configuration structure.
    
    Args:
        config: Workflow configuration dictionary
    
    Returns:
        Tuple of (is_valid, error_messages)
        - is_valid: True if configuration is valid, False otherwise
        - error_messages: List of validation error messages
    
    Example:
        >>> config = load_workflow_config()
        >>> is_valid, errors = validate_workflow_config(config)
        >>> if not is_valid:
        ...     print("Errors:", errors)
    """
    errors = []
    
    # Check required fields
    required_fields = ["entry_point", "nodes"]
    for field in required_fields:
        if field not in config:
            errors.append(f"Missing required field: {field}")
    
    # Validate entry point exists in nodes
    if "entry_point" in config and "nodes" in config:
        entry_point = config["entry_point"]
        node_names = [node.get("name") for node in config.get("nodes", [])]
        if entry_point not in node_names:
            errors.append(f"Entry point '{entry_point}' not found in nodes")
    
    # Validate nodes structure
    if "nodes" in config:
        for i, node in enumerate(config["nodes"]):
            if "name" not in node:
                errors.append(f"Node {i} missing 'name' field")
            if "type" not in node:
                errors.append(f"Node {node.get('name', i)} missing 'type' field")
    
    return (len(errors) == 0, errors)


def get_workflow_info(workflow_json_path: str | Path = "workflow.json") -> dict[str, Any]:
    """
    Get information about the workflow configuration.
    
    Args:
        workflow_json_path: Path to workflow.json file
    
    Returns:
        Dictionary containing workflow information:
        - name: Workflow name
        - entry_point: Entry point node name
        - node_count: Number of nodes
        - edge_count: Number of edges
        - conditional_edge_count: Number of conditional edges
        - node_types: List of unique node types
        - node_names: List of all node names
    
    Example:
        >>> info = get_workflow_info()
        >>> print(f"Workflow has {info['node_count']} nodes")
    """
    try:
        config = load_workflow_config(workflow_json_path)
        
        nodes = config.get("nodes", [])
        edges = config.get("edges", [])
        conditional_edges = config.get("conditional_edges", [])
        
        node_types = list(set(node.get("type", "unknown") for node in nodes))
        node_names = [node.get("name") for node in nodes if node.get("name")]
        
        return {
            "name": config.get("name", "Unknown"),
            "entry_point": config.get("entry_point", "unknown"),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "conditional_edge_count": len(conditional_edges),
            "node_types": node_types,
            "node_names": node_names,
            "has_checkpointing": "checkpointer" in config or config.get("checkpointing", False)
        }
    except Exception as e:
        return {
            "error": str(e),
            "name": "Unknown",
            "entry_point": "unknown",
            "node_count": 0,
            "edge_count": 0,
            "conditional_edge_count": 0,
            "node_types": [],
            "node_names": []
        }


def list_workflow_nodes(workflow_json_path: str | Path = "workflow.json") -> list[dict[str, Any]]:
    """
    List all nodes in the workflow.
    
    Args:
        workflow_json_path: Path to workflow.json file
    
    Returns:
        List of node dictionaries with name, type, and properties
    
    Example:
        >>> nodes = list_workflow_nodes()
        >>> for node in nodes:
        ...     print(f"{node['name']}: {node['type']}")
    """
    try:
        config = load_workflow_config(workflow_json_path)
        return config.get("nodes", [])
    except Exception:
        return []


def list_workflow_edges(workflow_json_path: str | Path = "workflow.json") -> list[dict[str, Any]]:
    """
    List all edges in the workflow.
    
    Args:
        workflow_json_path: Path to workflow.json file
    
    Returns:
        List of edge dictionaries with 'from' and 'to' fields
    
    Example:
        >>> edges = list_workflow_edges()
        >>> for edge in edges:
        ...     print(f"{edge['from']} -> {edge['to']}")
    """
    try:
        config = load_workflow_config(workflow_json_path)
        return config.get("edges", [])
    except Exception:
        return []


def list_conditional_edges(workflow_json_path: str | Path = "workflow.json") -> list[dict[str, Any]]:
    """
    List all conditional edges in the workflow.
    
    Args:
        workflow_json_path: Path to workflow.json file
    
    Returns:
        List of conditional edge dictionaries
    
    Example:
        >>> cond_edges = list_conditional_edges()
        >>> for edge in cond_edges:
        ...     print(f"{edge['from']} -> {edge['router_function']}")
    """
    try:
        config = load_workflow_config(workflow_json_path)
        return config.get("conditional_edges", [])
    except Exception:
        return []


def orchestrate_workflow_from_json(
    input_text: str,
    channel: str = "chat",
    conversation_id: str = "default",
    workflow_json_path: str | Path = "workflow.json",
    checkpointer: Any = None,
    human_input: str | None = None
) -> dict[str, Any]:
    """
    Orchestrate a workflow execution from Microsoft Copilot workflow.json format using LangGraph.
    
    This function:
    1. Loads the workflow configuration from Copilot JSON format (WorkflowActivities/WorkflowConnections)
    2. Builds the LangGraph workflow from the activities and connections
    3. Creates initial state
    4. Executes the workflow
    5. Returns the final result
    
    Args:
        input_text: User's input message
        channel: Communication channel ("chat" or "email")
        conversation_id: Conversation identifier for checkpointing
        workflow_json_path: Path to workflow.json file
        checkpointer: Optional checkpointer for state persistence
        human_input: Optional human input for review steps
    
    Returns:
        Dictionary containing the final workflow state with keys:
        - response: Final response text
        - intent: Detected intent
        - entities: Extracted entities
        - isFastenerSearch: Whether this was a fastener search
        - parsed_query: Parsed query (for fastener search)
        - tool_result: Tool execution results
        - retrieved: Retrieved documents
        - needs_human_review: Whether human review is needed
        - review_message: Review message if needed
        - All other state fields
    
    Example:
        >>> result = orchestrate_workflow_from_json(
        ...     "Check order status for order 12345",
        ...     channel="chat",
        ...     conversation_id="conv-001"
        ... )
        >>> print(result["response"])
        "Your order 12345 is currently shipped..."
    """
    try:
        # Load and validate workflow JSON
        workflow_path = Path(workflow_json_path)
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow JSON file not found: {workflow_path}")
        
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_config = json.load(f)
        
        print(f"[Orchestrate] Loading Copilot workflow from: {workflow_path}")
        print(f"[Orchestrate] Workflow title: {workflow_config.get('title', 'unknown')}")
        print(f"[Orchestrate] StartActivityId: {workflow_config.get('StartActivityId', 'unknown')}")
        print(f"[Orchestrate] Activities count: {len(workflow_config.get('WorkflowActivities', []))}")
        
        # Build the graph from Copilot format
        print(f"[Orchestrate] Building graph from Copilot JSON format...")
        compiled_graph = _builder.build_from_copilot_json(workflow_path, checkpointer)
        print(f"[Orchestrate] Graph built successfully")
        
        # Create initial state
        state = initial_state(input_text, channel)
        
        # Add human input if provided (for review steps)
        if human_input:
            state["human_input"] = human_input
        
        # Prepare configuration for checkpointing
        config = {"configurable": {"thread_id": conversation_id}} if checkpointer else {}
        
        # Execute the workflow
        print(f"[Orchestrate] Executing workflow with input: {input_text[:50]}...")
        print(f"[Orchestrate] Channel: {channel}, Conversation ID: {conversation_id}")
        
        result = compiled_graph.invoke(state, config)
        
        print(f"[Orchestrate] Workflow execution completed")
        print(f"[Orchestrate] Final state keys: {list(result.keys())}")
        
        # Return the result
        return dict(result)
        
    except FileNotFoundError as e:
        print(f"[Orchestrate] ERROR: {e}")
        # Return error state
        return {
            "input": input_text,
            "user_input": input_text,
            "channel": channel,
            "response": f"Error: Workflow file not found: {str(e)}",
            "intent": None,
            "entities": {},
            "error": str(e)
        }
        
    except Exception as e:
        print(f"[Orchestrate] ERROR: {e}")
        import traceback
        traceback.print_exc()
        # Return error state
        return {
            "input": input_text,
            "user_input": input_text,
            "channel": channel,
            "response": f"Error executing workflow: {str(e)}",
            "intent": None,
            "entities": {},
            "error": str(e)
        }


async def orchestrate_workflow_from_json_async(
    input_text: str,
    channel: str = "chat",
    conversation_id: str = "default",
    workflow_json_path: str | Path = "workflow.json",
    checkpointer: Any = None,
    human_input: str | None = None
) -> dict[str, Any]:
    """
    Async version of orchestrate_workflow_from_json for use in async contexts.
    
    Same functionality as orchestrate_workflow_from_json but uses ainvoke for async execution.
    
    Args:
        input_text: User's input message
        channel: Communication channel ("chat" or "email")
        conversation_id: Conversation identifier for checkpointing
        workflow_json_path: Path to workflow.json file
        checkpointer: Optional checkpointer for state persistence
        human_input: Optional human input for review steps
    
    Returns:
        Dictionary containing the final workflow state
    
    Example:
        >>> result = await orchestrate_workflow_from_json_async(
        ...     "Check order status for order 12345",
        ...     channel="chat"
        ... )
        >>> print(result["response"])
    """
    try:
        # Load and validate workflow JSON
        workflow_path = Path(workflow_json_path)
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow JSON file not found: {workflow_path}")
        
        with open(workflow_path, "r", encoding="utf-8") as f:
            workflow_config = json.load(f)
        
        print(f"[Orchestrate] Loading Copilot workflow from: {workflow_path}")
        print(f"[Orchestrate] Workflow title: {workflow_config.get('title', 'unknown')}")
        print(f"[Orchestrate] StartActivityId: {workflow_config.get('StartActivityId', 'unknown')}")
        print(f"[Orchestrate] Activities count: {len(workflow_config.get('WorkflowActivities', []))}")
        
        # Build the graph from Copilot format
        print(f"[Orchestrate] Building graph from Copilot JSON format...")
        compiled_graph = _builder.build_from_copilot_json(workflow_path, checkpointer)
        print(f"[Orchestrate] Graph built successfully")
        
        # Create initial state
        state = initial_state(input_text, channel)
        
        # Add human input if provided (for review steps)
        if human_input:
            state["human_input"] = human_input
        
        # Prepare configuration for checkpointing
        config = {"configurable": {"thread_id": conversation_id}} if checkpointer else {}
        
        # Execute the workflow asynchronously
        print(f"[Orchestrate] Executing workflow (async) with input: {input_text[:50]}...")
        print(f"[Orchestrate] Channel: {channel}, Conversation ID: {conversation_id}")
        
        result = await compiled_graph.ainvoke(state, config)
        
        print(f"[Orchestrate] Workflow execution completed")
        print(f"[Orchestrate] Final state keys: {list(result.keys())}")
        
        # Return the result
        return dict(result)
        
    except FileNotFoundError as e:
        print(f"[Orchestrate] ERROR: {e}")
        # Return error state
        return {
            "input": input_text,
            "user_input": input_text,
            "channel": channel,
            "response": f"Error: Workflow file not found: {str(e)}",
            "intent": None,
            "entities": {},
            "error": str(e)
        }
        
    except Exception as e:
        print(f"[Orchestrate] ERROR: {e}")
        import traceback
        traceback.print_exc()
        # Return error state
        return {
            "input": input_text,
            "user_input": input_text,
            "channel": channel,
            "response": f"Error executing workflow: {str(e)}",
            "intent": None,
            "entities": {},
            "error": str(e)
        }

