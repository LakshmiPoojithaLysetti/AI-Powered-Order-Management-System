# server.py
import os
import json
import asyncio
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException  # type: ignore[import]
from fastapi.responses import FileResponse  # type: ignore[import]
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import]
from pydantic import BaseModel
from graph import build_graph, initial_state
from neo4j_module import ensure_demo_docs, save_message, is_neo4j_available, seed_order_data_async
from langgraph.checkpoint.memory import MemorySaver  # type: ignore[import]

load_dotenv(override=True)

# Verify Neo4j is available before starting the server
if not is_neo4j_available():
    raise RuntimeError(
        "Neo4j is REQUIRED but not available. "
        "Please ensure Neo4j is running and configured with NEO4J_URI, NEO4J_USER, and NEO4J_PASS in your .env file."
    )

# Get the directory where this file is located
BASE_DIR = Path(__file__).parent
public_dir = BASE_DIR / "public"

# Build the graph
# Create checkpoint store for human-in-the-loop functionality
checkpoint_store = MemorySaver()
compiled = build_graph(checkpointer=checkpoint_store)

# Seed demo docs on startup using lifespan
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await ensure_demo_docs()
    yield
    # Shutdown (if needed)
    pass

app = FastAPI(lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request/Response models
class ChatRequest(BaseModel):
    message: str
    channel: Optional[str] = "chat"
    conversationId: Optional[str] = "default"
    humanInput: Optional[str] = None


class ChatResponse(BaseModel):
    conversationId: str
    response: str
    intent: Optional[str] = None
    entities: Optional[dict] = {}
    toolResult: Optional[dict] = None
    retrieved: Optional[list] = []
    needsHumanReview: Optional[bool] = False
    reviewMessage: Optional[str] = None
    isFastenerSearch: Optional[bool] = False
    parsed_query: Optional[str] = None


# API routes - must be defined before static file routes
# Simple chat endpoint
@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    try:
        if not req.message:
            raise HTTPException(status_code=400, detail="message required")

        # Ensure we have non-None values for required parameters
        conversation_id = req.conversationId or "default"
        channel = req.channel or "chat"

        # Save user message
        await save_message(conversation_id, "user", req.message)

        # Run graph with checkpointing
        state = initial_state(req.message, channel)
        
        # Add human input if provided (for review steps)
        if req.humanInput:
            state["human_input"] = req.humanInput
        
        config = {"configurable": {"thread_id": conversation_id}}
        
        # Check if this is a continuation of a paused workflow
        if req.humanInput or req.message.lower().strip() in ["yes", "y", "approve", "confirm", "no", "n", "reject", "cancel"]:
            # This might be a response to a human review
            # Try to continue from checkpoint
            try:
                # Get the current state from checkpoint
                current_state = compiled.get_state(config)
                if current_state.values and current_state.values.get("needs_human_review"):
                    # Update state with human input and continue
                    human_input_value = req.humanInput or req.message
                    current_state.values["human_input"] = human_input_value
                    result = await compiled.ainvoke(current_state.values, config)
                else:
                    # No pending review, run normally
                    result = await compiled.ainvoke(state, config)
            except Exception:
                # No checkpoint found, run normally
                result = await compiled.ainvoke(state, config)
        else:
            # Normal execution
            result = await compiled.ainvoke(state, config)

        # Debug: Log the result and check for coroutines
        import inspect
        print(f"\n{'='*60}")
        print(f"[DEBUG] Graph result keys: {list(result.keys())}")
        print(f"[DEBUG] Full result: {result}")
        print(f"{'='*60}")
        
        # Check all values for coroutines
        for key, value in result.items():
            if inspect.iscoroutine(value):
                print(f"[ERROR] Found coroutine in result['{key}']: {type(value)}")
            else:
                print(f"[DEBUG] {key}: {type(value).__name__} = {str(value)[:100] if value else 'None'}")
        print()

        # Extract response and ensure it's not empty or a coroutine
        response_raw = result.get("response")
        if inspect.iscoroutine(response_raw):
            print("[ERROR] response is a coroutine, using fallback")
            response = ""
        else:
            response = str(response_raw) if response_raw else ""
        
        # Check if workflow is paused for human review
        needs_review_raw = result.get("needs_human_review", False)
        if inspect.iscoroutine(needs_review_raw):
            needs_review = False
        else:
            needs_review = bool(needs_review_raw) if needs_review_raw else False
        
        review_message_raw = result.get("review_message")
        if inspect.iscoroutine(review_message_raw):
            review_message = None
        else:
            review_message = str(review_message_raw) if review_message_raw else None
        
        # If human review is needed, the response should be the review message
        if needs_review and review_message:
            response = review_message
            print(f"[DEBUG] Using review message as response: {response[:100]}")
        
        # Generate response if still empty - prioritize tool_result and parsed_query
        if not response or response.strip() == "":
            print("[DEBUG] Response is empty, generating response from workflow state...")
            parsed_query = result.get("parsed_query")
            intent = result.get("intent")
            tool_result = result.get("tool_result")
            retrieved = result.get("retrieved", [])
            
            # Check for parsed_query (fastener search) - highest priority
            if parsed_query and not inspect.iscoroutine(parsed_query) and parsed_query != "{}":
                try:
                    query_obj = json.loads(parsed_query) if isinstance(parsed_query, str) else parsed_query
                    if query_obj and query_obj != {}:
                        response = f"I found fastener search results based on your query. Here are the matching items."
                        print(f"[DEBUG] Generated response from parsed_query")
                except:
                    pass
            
            # Check for tool_result (order status, tracking, etc.) - high priority
            if (not response or response.strip() == "") and tool_result and not inspect.iscoroutine(tool_result):
                try:
                    if isinstance(tool_result, dict):
                        # Format tool result nicely
                        if "status" in tool_result:
                            status = tool_result.get("status", "unknown")
                            order_id = tool_result.get("id") or tool_result.get("orderId") or tool_result.get("order_id", "unknown")
                            response = f"Your order {order_id} is currently {status.lower()}."
                            
                            # Add additional details if available
                            details = []
                            if tool_result.get("carrier"):
                                details.append(f"Carrier: {tool_result['carrier']}")
                            if tool_result.get("tracking") or tool_result.get("trackingNumber"):
                                tracking = tool_result.get("tracking") or tool_result.get("trackingNumber")
                                details.append(f"Tracking: {tracking}")
                            if tool_result.get("expectedDelivery") or tool_result.get("estimatedDelivery"):
                                delivery = tool_result.get("expectedDelivery") or tool_result.get("estimatedDelivery")
                                details.append(f"Expected delivery: {delivery}")
                            if details:
                                response += " " + ". ".join(details) + "."
                                
                        elif "amount" in tool_result:
                            amount = tool_result.get("amount", "unknown")
                            order_id = tool_result.get("orderId") or tool_result.get("id", "unknown")
                            refund_id = tool_result.get("refundId", "")
                            status = tool_result.get("status", "processing")
                            response = f"Your refund request for order {order_id} is {status.lower()}."
                            if refund_id:
                                response += f" Refund ID: {refund_id}."
                            if amount:
                                response += f" Amount: ${amount}."
                        elif "currentLocation" in tool_result or "trackingNumber" in tool_result:
                            # Tracking order
                            order_id = tool_result.get("orderId") or tool_result.get("id", "unknown")
                            location = tool_result.get("currentLocation", "")
                            tracking = tool_result.get("trackingNumber", "")
                            status = tool_result.get("status", "in transit")
                            response = f"Order {order_id} is {status.lower()}."
                            if location:
                                response += f" Current location: {location}."
                            if tracking:
                                response += f" Tracking number: {tracking}."
                        else:
                            # Generic tool result formatting
                            response = f"Your request has been processed successfully. {json.dumps(tool_result, indent=2)}"
                    else:
                        response = f"Your request has been processed. {str(tool_result)}"
                    print(f"[DEBUG] Generated response from tool_result: {response[:100]}")
                except Exception as e:
                    print(f"[WARNING] Error formatting tool_result: {e}")
                    import traceback
                    traceback.print_exc()
                    response = f"Your request has been processed successfully."
            
            # Check for retrieved documents
            if (not response or response.strip() == "") and retrieved and isinstance(retrieved, list) and len(retrieved) > 0:
                try:
                    first_doc = retrieved[0] if isinstance(retrieved[0], dict) else {}
                    title = first_doc.get("title", "documentation") or "documentation"
                    body = first_doc.get("body", "")
                    if body:
                        preview = body.split(". ")[0] + "." if ". " in body else body[:200]
                        response = f"According to our {title.lower()}, {preview}"
                    else:
                        response = f"I found information in our {title.lower()}."
                    print(f"[DEBUG] Generated response from retrieved documents")
                except Exception as e:
                    print(f"[WARNING] Error formatting retrieved: {e}")
            
            # Check for intent
            if (not response or response.strip() == "") and intent:
                intent_responses = {
                    "order_status": "I've checked the order status for you.",
                    "track_order": "I've tracked the order for you.",
                    "refund": "I've processed your refund request.",
                    "policy_question": "I found relevant information about our policies.",
                    "chit_chat": "I'm here to help! How can I assist you today?",
                    "fastener_search": "I found fastener search results for you."
                }
                response = intent_responses.get(intent, f"I've processed your {intent} request.")
                print(f"[DEBUG] Generated response from intent: {intent}")
            
            # Final fallback - more helpful message
            if not response or response.strip() == "":
                response = "I've processed your request. How can I help you further?"
                print(f"[DEBUG] Using final fallback response")
        
        print(f"[DEBUG] Final response: {response[:200]}")
        
        # Save assistant message
        await save_message(conversation_id, "assistant", response)

        # Extract intent and entities from result, ensuring they're properly formatted
        intent_raw = result.get("intent")
        if inspect.iscoroutine(intent_raw):
            print("[WARNING] intent is a coroutine, using None")
            intent = None
        else:
            intent = intent_raw if intent_raw else None
        
        entities_raw = result.get("entities") or {}
        
        # Ensure entities is a dict, not a coroutine
        if inspect.iscoroutine(entities_raw):
            print("[WARNING] entities is a coroutine, using empty dict")
            entities = {}
        elif isinstance(entities_raw, dict):
            entities = entities_raw
        else:
            entities = {}
        
        # Ensure response is always a string
        if not isinstance(response, str):
            response = str(response) if response else "No response generated"
        
        # Safely extract all values, ensuring they're JSON-serializable (not coroutines)
        def safe_get(key, default=None):
            """Safely get value from result, handling coroutines."""
            value = result.get(key, default)
            # Check if it's a coroutine (shouldn't happen, but just in case)
            if inspect.iscoroutine(value):
                print(f"[WARNING] Found coroutine in result['{key}'], skipping")
                return default
            # Ensure it's a basic JSON-serializable type
            if value is not None:
                if not isinstance(value, (str, int, float, bool, dict, list, type(None))):
                    # Try to convert to string if it's not a basic type
                    try:
                        value = str(value)
                    except:
                        value = default
            return value
        
        tool_result = safe_get("tool_result")
        retrieved = safe_get("retrieved", [])
        parsed_query = safe_get("parsed_query")
        is_fastener_search = safe_get("isFastenerSearch", False)
        
        # Ensure retrieved is a list
        if not isinstance(retrieved, list):
            retrieved = []
        
        # Ensure is_fastener_search is a boolean
        if not isinstance(is_fastener_search, bool):
            is_fastener_search = bool(is_fastener_search) if is_fastener_search else False
        
        # Validate all values before creating ChatResponse
        try:
            # Double-check all values are not coroutines
            all_values = {
                "conversationId": conversation_id,
                "response": response,
                "intent": intent,
                "entities": entities,
                "toolResult": tool_result,
                "retrieved": retrieved,
                "needsHumanReview": needs_review,
                "reviewMessage": review_message,
                "isFastenerSearch": is_fastener_search,
                "parsed_query": parsed_query
            }
            
            # Check each value for coroutines and ensure they're JSON-serializable
            for key, value in all_values.items():
                if inspect.iscoroutine(value):
                    print(f"[ERROR] Found coroutine in {key}: {type(value)}")
                    if key == "response":
                        all_values[key] = "Error: Coroutine found in response"
                    elif key in ["retrieved"]:
                        all_values[key] = []
                    elif key in ["entities"]:
                        all_values[key] = {}
                    else:
                        all_values[key] = None
                elif inspect.iscoroutinefunction(value):
                    print(f"[ERROR] Found coroutine function in {key}: {type(value)}")
                    if key == "response":
                        all_values[key] = "Error: Coroutine function found"
                    else:
                        all_values[key] = None
                # Ensure all values are JSON-serializable
                elif value is not None:
                    if not isinstance(value, (str, int, float, bool, dict, list, type(None))):
                        try:
                            # Try to convert to string if it's not a basic type
                            if key == "response":
                                all_values[key] = str(value)
                            else:
                                all_values[key] = None
                        except:
                            all_values[key] = None if key != "response" else "Error: Could not serialize"
            
            response_data = ChatResponse(**all_values)
            
            # Debug: Log what we're sending
            print(f"[DEBUG] Sending response: {response[:100]}...")
            print(f"[DEBUG] Response has isFastenerSearch: {response_data.isFastenerSearch}")
            print(f"[DEBUG] Response has parsed_query: {bool(response_data.parsed_query)}\n")
            
            return response_data
        except Exception as create_error:
            print(f"[ERROR] Failed to create ChatResponse: {create_error}")
            print(f"[ERROR] Error type: {type(create_error)}")
            import traceback
            traceback.print_exc()
            
            # Return a minimal error response
            return ChatResponse(
                conversationId=conversation_id,
                response=f"Error processing request: {str(create_error)}",
                intent=None,
                entities={},
                toolResult=None,
                retrieved=[],
                needsHumanReview=False,
                reviewMessage=None,
                isFastenerSearch=False,
                parsed_query=None
            )
    except Exception as e:
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e) or "internal error")


# Neo4j Management Endpoints
@app.get("/api/neo4j/status")
async def neo4j_status():
    """Check Neo4j connection status"""
    try:
        connected = is_neo4j_available()
        if connected:
            # Try to verify connection with a simple query
            from neo4j_module import driver
            if driver:
                try:
                    with driver.session() as session:
                        session.run("RETURN 1 as test")
                    message = "Neo4j is connected and ready"
                except Exception as e:
                    message = f"Neo4j driver exists but connection test failed: {str(e)}"
                    connected = False
            else:
                message = "Neo4j driver not initialized"
                connected = False
        else:
            message = "Neo4j is not available"
        
        return {
            "connected": connected,
            "message": message
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "connected": False,
            "message": f"Error checking status: {str(e)}"
        }


class LoadDataRequest(BaseModel):
    clearExisting: bool = False


@app.post("/api/neo4j/load-data")
async def load_neo4j_data(req: LoadDataRequest):
    """Load data from embedded order data in neo4j_module.py into Neo4j"""
    try:
        # Use embedded data by default (no file required)
        result = await seed_order_data_async(clear_existing=req.clearExisting, use_file=False)
        return {
            "success": result.get("success", False),
            "statements_executed": result.get("statements_executed", 0),
            "total_statements": result.get("total_statements", 0),
            "errors": result.get("errors", [])
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        error_detail = str(e)
        print(f"[ERROR] Failed to load Neo4j data: {error_detail}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=error_detail)


# Serve static files and frontend (must be after API routes)
if public_dir.exists():
    # Serve specific static files
    @app.get("/app.js")
    async def serve_app_js():
        return FileResponse(public_dir / "app.js", media_type="application/javascript")
    
    @app.get("/style.css")
    async def serve_style_css():
        return FileResponse(public_dir / "style.css", media_type="text/css")
    
    # Serve index.html at root
    @app.get("/")
    async def serve_index():
        return FileResponse(public_dir / "index.html")


if __name__ == "__main__":
    import uvicorn  # type: ignore[import]
    import socket
    
    def find_free_port(start_port=4000):
        """Find a free port starting from start_port"""
        port = start_port
        while port < start_port + 100:  # Try up to 100 ports
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(('0.0.0.0', port))
                sock.close()
                return port
            except OSError:
                port += 1
        raise RuntimeError(f"Could not find a free port in range {start_port}-{start_port+100}")
    
    requested_port = int(os.getenv("PORT", 4000))
    try:
        # Try the requested port first
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('0.0.0.0', requested_port))
        sock.close()
        port = requested_port
    except OSError:
        # Port is in use, find a free one
        print(f"⚠️  Port {requested_port} is already in use.")
        port = find_free_port(requested_port)
        print(f"📌 Using alternative port: {port}")
        print(f"💡 To use port {requested_port}, stop the process using it with:")
        print(f"   Windows: netstat -ano | findstr :{requested_port}")
        print(f"   Then: taskkill /PID <PID> /F\n")
    
    host = "0.0.0.0"  # Listen on all interfaces
    print(f"\n{'='*60}")
    print(f"🚀 Innovator Copilot Server Starting...")
    print(f"{'='*60}")
    print(f"📡 Server running on: http://localhost:{port}")
    print(f"🌐 Access from browser: http://localhost:{port} or http://127.0.0.1:{port}")
    print(f"⚠️  Note: Do NOT use http://0.0.0.0:{port} in browser")
    print(f"\n📋 Available API Endpoints:")
    print(f"   - GET  /api/neo4j/status")
    print(f"   - POST /api/neo4j/load-data")
    print(f"   - POST /api/chat")
    print(f"{'='*60}\n")
    uvicorn.run(app, host=host, port=port)
