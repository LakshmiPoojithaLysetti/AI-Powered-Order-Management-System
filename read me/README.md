# 🔧 Copilot - AI-Powered Order Management System

An intelligent workflow orchestration system built with LangGraph, FastAPI, and Neo4j that provides AI-powered order management with human-in-the-loop refund approvals and real-time order tracking.

## ✨ Features

### Order Management
- **Order Status & Tracking**: Check order status with carrier information and real-time location updates
- **Order Pricing**: Get detailed price breakdowns with item-level details
- **Refund Processing**: Handle refund requests with human-in-the-loop approval workflow
  - Automated eligibility checks (300-day return window)
  - Status validation (only delivered orders can be returned)
  - Interactive approval modal for user confirmation
  - Automatic redirect to return page for eligible orders

### AI-Powered Chat Interface
- Natural language order queries
- Intent classification with entity extraction
- Markdown-formatted responses
- Persistent conversation history with Neo4j

### Policy Assistant
- Answer questions about warranty, shipping, and return policies
- Document retrieval from Neo4j knowledge base

## 🏗️ Architecture

```
┌─────────────────────┐
│   Client (React)    │ HTML/CSS/JS + Modal UI
└──────────┬──────────┘
           │
┌──────────▼──────────┐
│   FastAPI Server    │ REST API + Static Files
└──────────┬──────────┘
           │
┌──────────▼───────────────────────┐
│   LangGraph Workflow Engine      │
│   (Orchestration with Cycles)    │
└──────────┬───────────────────────┘
           │
┌──────────▼─────────┐    ┌──────────────┐
│   Neo4j Database   │    │   OpenAI     │
│   (data.cypher)    │    │   GPT-4o     │
└────────────────────┘    └──────────────┘
```

## 🔄 Workflow Engine (workflow.json)

The conversation flow is orchestrated by `workflow.json` (Microsoft Copilot format), which maps to LangGraph nodes in `graph.py`. The workflow supports **cyclic connections** with proper termination conditions to handle complex multi-step interactions.

| Activity (workflow.json) | Node Function (`graph.py`) | Purpose |
| ------------------------ | -------------------------- | ------- |
| `Start`                  | `start_node`               | Receives incoming REST/chat request and initializes state |
| `UserTask1`              | `user_task_node`           | Performs intake, entity extraction, and schema validation |
| `RetrievalTask1`         | `retrieval_task_node`      | Retrieves policy documents and catalog info from Neo4j |
| `LLMTask1`               | `llm_task_node`            | Normalizes user intent using ChatOpenAI, refining entities and intent labels |
| `ToolTask1`              | `tool_task_node`           | Executes deterministic tools (status lookup, pricing, tracking, refund eligibility) |
| `RouterTask1`            | `router_task_node`         | Routes to render, agent, or human review based on state conditions |
| `RenderTask1`            | `render_task_node`         | Formats final AI response with markdown support |
| `AgentTask1`             | `agent_task_node`          | Handles complex multi-step operations (future: fastener search, inventory) |
| `UserTask2`              | `user_task2_node`          | **Human-in-the-loop approval** for refunds with conditional cycle termination |

### Execution Flow

1. **Start → Intake**: HTTP/chat request enters via `Start`, then `UserTask1` validates schema and extracts entities (e.g., order IDs)

2. **Retrieval & Intent Normalization**: 
   - `RetrievalTask1` fetches policy context when needed
   - `LLMTask1` uses LLM to classify intent and refine entities

3. **Tool Execution**: `ToolTask1` invokes Neo4j-backed functions from `tools/order_tools.py`:
   - Order status/tracking from `data.cypher`
   - Price calculation with item breakdown
   - Refund eligibility check (300-day window, delivered status)

4. **Routing**: `RouterTask1` checks state and routes to:
   - `UserTask2` if refund requires human approval
   - `AgentTask1` for complex operations
   - `RenderTask1` for standard responses

5. **Human-in-the-Loop (HITL)**: `UserTask2` handles refund approvals:
   - Shows approval request modal in UI
   - Pauses workflow until user approves/rejects
   - Uses conditional edge to terminate cycle (prevents infinite loops)
   - Redirects to `/return` page for eligible delivered orders

6. **Render**: `RenderTask1` formats markdown response with order details

### Cycle Breaking Logic

The workflow includes a **cyclic connection** `UserTask2 → LLMTask1` (defined in `workflow.json`), which is controlled by conditional routing:

```python
# In graph.py build_from_copilot_json()
def user_task2_route(state):
    if state.get("needs_human_review"):
        return "__end__"  # Pause for user input
    else:
        return "__end__"  # Workflow complete
```

This prevents recursion errors while allowing the topology to support future follow-up flows.

## 📋 Prerequisites

- **Python 3.10+**
- **Neo4j Database** (version 5.x recommended)
- **OpenAI API Key** (GPT-4o or GPT-4o-mini)

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd copilot-workflow
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Up Environment Variables

Create a `.env` file in the root directory:

```env
# OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key_here

# Neo4j Configuration (REQUIRED)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASS=your_neo4j_password_here
```

### 4. Start Neo4j Database

Make sure Neo4j is running and accessible:

```bash
# Using Docker
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:5.20.0

# Or use your existing Neo4j installation
```

### 5. Seed Order Data

The server automatically seeds `data.cypher` on first launch. To manually reseed:

```bash
python -c "import asyncio; from neo4j_module import seed_order_data_async; \
asyncio.run(seed_order_data_async(clear_existing=True, use_file=False))"
```

## 🎯 Usage

### Start the Server

```bash
python server.py
```

Output:
```
[neo4j] Successfully connected to Neo4j at bolt://localhost:7687
[startup] Found 6 orders in database
INFO:     Uvicorn running on http://0.0.0.0:4000 (Press CTRL+C to quit)
```

### Access the Web Interface

Open your browser:
```
http://localhost:4000
```

### Example Interactions

**Order Status:**
```
User: "check order 12345"
AI: Order 12345 is currently **Shipped**. It is being handled by **UPS**. 
    Order contains 1 item(s). Total amount: $199.99
```

**Order Price:**
```
User: "price of order 67890"
AI: The total price for order 67890 is **$349.99**.

**Item Breakdown:**
- Product B: 1 × $249.99
- Product C: 1 × $99.99
```

**Refund Request:**
```
User: "return order 11111"
AI: [Redirects to /return?orderId=11111 page showing eligibility and order details]
```

## 📡 API Endpoints

### Chat Endpoint

**POST** `/api/chat`

```json
{
  "message": "check order 12345",
  "channel": "chat",
  "conversationId": "default"
}
```

**Response:**
```json
{
  "conversationId": "default",
  "response": "Order 12345 is currently **Shipped**...",
  "intent": "order_status",
  "entities": {"orderId": "12345"},
  "redirectUrl": null
}
```

### Return Page

**GET** `/return?orderId=11111`

Renders a styled HTML page showing:
- Order details (status, date, expected delivery, price)
- Eligibility status (based on 300-day policy and delivered status)
- Quick actions (back to chat, contact support)

### Neo4j Status

**GET** `/api/neo4j/status`

```json
{
  "connected": true,
  "message": "Neo4j is connected and ready"
}
```

### Load Data

**POST** `/api/neo4j/load-data`

```json
{
  "clearExisting": true
}
```

## 📁 Project Structure

```
copilot-workflow/
├── graph.py                 # LangGraph workflow with cycle-breaking logic
├── neo4j_module.py         # Neo4j operations + data.cypher loader
├── server.py               # FastAPI server with HITL support
├── workflow.json           # Workflow topology (Microsoft Copilot format)
├── data.cypher             # Order/customer/policy seed data
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (create this)
├── tools/
│   └── order_tools.py      # Order operations (status, tracking, refunds)
└── public/
    ├── index.html          # Chat UI with refund approval modal
    ├── app.js              # Frontend logic (HITL modal handling)
    └── style.css           # Styling with modal overlay
```

## 🔧 Configuration

### Workflow Configuration

Edit `workflow.json` to modify the workflow topology. Changes are automatically reflected in `graph.py` via `build_from_copilot_json()`.

**Key Features:**
- Supports cyclic connections (e.g., `UserTask2 → LLMTask1`)
- Conditional edges for `RouterTask1` and `UserTask2`
- Automatic terminal node detection (nodes without outgoing edges → `END`)

### Return Policy

Edit `neo4j_module.py` and `data.cypher` to adjust the return window:

```python
# neo4j_module.py line 948
return_policy_days = 300  # Change to desired days
```

```cypher
// data.cypher line 234
SET policy.returnWindowDays = 300
```

### Recursion Limit

Adjust in `server.py` line 135:

```python
config = {
    "configurable": {"thread_id": conversation_id},
    "recursion_limit": 50  # Increase if needed
}
```

## 🎨 Features in Detail

### Human-in-the-Loop (HITL) Refund Approval

1. **Eligibility Check**: System validates:
   - Order must be in "Delivered" status
   - Within 300 days of purchase date
   - Order exists in Neo4j

2. **Modal UI**: Interactive approval overlay shows:
   - Order ID, amount, and reason
   - Approve/Reject buttons
   - Backdrop click to keep modal open

3. **Workflow Pause**: Graph execution stops at `UserTask2` until user provides input

4. **Resume Logic**: User response ("approve"/"reject") triggers:
   - `approve_return_request()` in Neo4j
   - State update with `workflow_complete = True`
   - Conditional routing to `__end__` (prevents infinite loops)

### Intent Classification

Recognized intents:
- `order_status`: Status + carrier info
- `order_price`: Price breakdown with items
- `track_order`: Tracking history with locations
- `refund`: Eligibility check + HITL approval
- `policy_question`: Document retrieval
- `chit_chat`: General conversation

### Data Source

All order data comes from `data.cypher` via `neo4j_module.py`:
- 6 sample orders with tracking events
- 3 carriers (UPS, FedEx, USPS)
- 4 customers
- Return policy nodes
- Product catalog with inventory

## 🛠️ Technologies

- **LangGraph**: Stateful workflow orchestration with cycles
- **LangChain**: LLM integration (ChatOpenAI)
- **FastAPI**: Async web framework
- **Neo4j**: Graph database (Cypher queries)
- **OpenAI GPT-4o-mini**: Intent classification and entity extraction
- **Python 3.10+**: Backend
- **Vanilla JS**: Frontend with modal handling

## 📝 Example Queries

### Order Management
```
"check order 12345"
"what's the status of order 67890"
"price of order 11111"
"track order 22222"
"return order 11111"
```

### Carrier Queries
```
"who is shipping order 12345"
"which carrier for order 67890"
```

### Policy Questions
```
"what is your return policy"
"how long do I have to return an item"
"tell me about shipping"
```

## 🔍 Troubleshooting

### Recursion Limit Errors

**Symptom:** `Error: Recursion limit of 50 reached`

**Solution:** The workflow now includes cycle-breaking logic in `UserTask2`. If the error persists:
1. Check `state["workflow_complete"]` is set to `True` when review finishes
2. Verify `user_task2_route()` conditional edge returns `"__end__"`
3. Increase recursion limit in `server.py` config

### Order Not Eligible for Return

**Symptom:** "Order status is Returned/Shipped, order must be delivered"

**Solution:** 
1. Check order status in `data.cypher` (should be `"Delivered"`)
2. Reseed database:
   ```bash
   python -c "import asyncio; from neo4j_module import seed_order_data_async; \
   asyncio.run(seed_order_data_async(clear_existing=True, use_file=False))"
   ```
3. Verify order date is within 300 days

### Neo4j Connection Issues

1. Verify Neo4j is running: `docker ps` or check service
2. Test connection: `NEO4J_URI=bolt://localhost:7687`
3. Check credentials in `.env`
4. Green "Neo4j" indicator in UI means connected

### Port Already in Use

Server auto-selects next available port if 4000 is taken. Check console output.

## 📊 Data Management

### Reseed Database

```bash
python -c "import asyncio; from neo4j_module import seed_order_data_async; \
asyncio.run(seed_order_data_async(clear_existing=True, use_file=False))"
```

### View Embedded Data

```python
from neo4j_module import get_embedded_order_data
data = get_embedded_order_data()
print(f"Orders: {len(data['orders'])}")
print(f"Carriers: {len(data['carriers'])}")
```

### Add New Orders

Edit `data.cypher` and add Cypher statements:

```cypher
MERGE (order:Order {id: "99999"})
SET order.status = "Delivered"
SET order.orderDate = date("2025-06-15")
SET order.expectedDelivery = date("2025-06-20")
SET order.totalAmount = 299.99
```

Then reseed the database.

## 🚀 Deployment

### Production Checklist

- [ ] Set strong Neo4j password
- [ ] Use production OpenAI API key
- [ ] Enable HTTPS for FastAPI
- [ ] Configure CORS appropriately
- [ ] Set up Neo4j backup strategy
- [ ] Monitor recursion limit metrics
- [ ] Add authentication for `/api/chat`

### Environment Variables

```env
# Production
OPENAI_API_KEY=sk-prod-...
NEO4J_URI=bolt://production-host:7687
NEO4J_USER=neo4j
NEO4J_PASS=strong_password_here
```

## 📄 License

[Add your license information here]

## 🤝 Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Test with `python -m pytest` (if tests exist)
4. Submit a pull request

## 📧 Support

For issues or questions:
- Open a GitHub issue
- Check troubleshooting section above
- Review LangGraph docs: https://python.langchain.com/docs/langgraph

---

**Built with ❤️ using LangGraph, FastAPI, and Neo4j**

*Demonstrating human-in-the-loop workflows with cyclic graph topologies*
