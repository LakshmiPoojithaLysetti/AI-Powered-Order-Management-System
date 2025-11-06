# 🔧 Copilot - AI-Powered Order Management System

An intelligent workflow orchestration system built with LangGraph, FastAPI, and Neo4j that provides AI-powered order management, fastener search, and policy assistance capabilities.

## ✨ Features

### Order Management
- **Order Status**: Check order status with detailed information
- **Order Tracking**: Track shipments with real-time location updates
- **Order Pricing**: Get detailed price breakdowns for orders
- **Refund Processing**: Handle refund requests with human-in-the-loop approval

### Fastener Search
- Intelligent search for screws, bolts, nuts, and hardware parts
- Natural language query processing

### Policy Assistant
- Answer questions about warranty, shipping, and return policies
- Document retrieval from Neo4j knowledge base

### System Management
- **Neo4j Integration**: Real-time database connection status
- **Data Management**: Load and manage order data from embedded Cypher scripts
- **Workflow Orchestration**: Dynamic workflow execution from JSON configuration

## 🏗️ Architecture

```
┌─────────────┐
│   Client    │ (HTML/CSS/JS)
└──────┬──────┘
       │
┌──────▼──────┐
│  FastAPI    │ (REST API)
│   Server    │
└──────┬──────┘
       │
┌──────▼──────────────────┐
│   LangGraph Workflow    │
│   Orchestration Engine   │
└──────┬───────────────────┘
       │
┌──────▼──────┐    ┌──────────────┐
│   Neo4j     │    │   OpenAI     │
│  Database   │    │     LLM      │
└─────────────┘    └──────────────┘
```

For detailed workflow diagrams, see [WORKFLOW_DIAGRAM.md](WORKFLOW_DIAGRAM.md).

## 📋 Prerequisites

- **Python 3.9+**
- **Neo4j Database** (version 5.x recommended)
- **OpenAI API Key**
- **Node.js** (for development, if needed)

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

Make sure Neo4j is running and accessible at the URI specified in your `.env` file.

```bash
# Using Docker
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  neo4j:5.20.0

# Or use your existing Neo4j installation
```

## 🎯 Usage

### Start the Server

```bash
python server.py
```

The server will start on port 4000 (or the next available port if 4000 is in use). You'll see output like:

```
Starting server on http://0.0.0.0:4000
Available endpoints:
  GET  /api/chat
  POST /api/chat
  GET  /api/neo4j/status
  POST /api/neo4j/load-data
```

### Access the Web Interface

Open your browser and navigate to:

```
http://localhost:4000
```

### Load Order Data

1. Click the **⚙️ Settings** button in the header
2. In the System Management panel, click **"Load Order Data"**
3. Wait for the confirmation message

Alternatively, load data programmatically:

```python
from neo4j_module import seed_order_data_async
import asyncio

asyncio.run(seed_order_data_async(clear_existing=False))
```

## 📡 API Endpoints

### Chat Endpoint

**POST** `/api/chat`

Send a message to the AI assistant.

```json
{
  "message": "Check order status for order 12345",
  "channel": "chat"
}
```

**Response:**
```json
{
  "response": "Your order 12345 is currently **Shipped**...",
  "intent": "order_status",
  "entities": {"orderId": "12345"}
}
```

### Neo4j Status

**GET** `/api/neo4j/status`

Check Neo4j connection status.

**Response:**
```json
{
  "connected": true,
  "message": "Neo4j is connected and ready"
}
```

### Load Data

**POST** `/api/neo4j/load-data`

Load order data into Neo4j.

```json
{
  "clearExisting": false
}
```

**Response:**
```json
{
  "success": true,
  "statements_executed": 58,
  "total_statements": 58,
  "errors": []
}
```

## 📁 Project Structure

```
copilot-workflow/
├── graph.py                 # LangGraph workflow orchestration
├── neo4j_module.py         # Neo4j database operations & embedded data
├── server.py               # FastAPI server
├── workflow.json           # Workflow configuration (Microsoft Copilot format)
├── requirements.txt        # Python dependencies
├── .env                    # Environment variables (create this)
├── tools/
│   └── order_tools.py      # Order-related operations
└── public/
    ├── index.html          # Web UI
    ├── app.js              # Frontend JavaScript
    └── style.css           # Styling
```

## 🔧 Configuration

### Workflow Configuration

The system supports two workflow formats:

1. **Microsoft Copilot Format** (`workflow.json`): Uses `WorkflowActivities` and `WorkflowConnections`
2. **Standard LangGraph Format**: Uses `entry_point` and `nodes`

The system automatically detects the format and builds the appropriate workflow.

### Order Data

Order data is embedded in `neo4j_module.py` as `EMBEDDED_ORDER_DATA`. The system can also load from external `.cypher` files if needed.

## 🎨 Features in Detail

### Intent Classification

The system recognizes the following intents:

- `order_status`: Check order status
- `order_price`: Get order price/cost
- `track_order`: Track shipment
- `refund`: Process refund request
- `policy_question`: Answer policy questions
- `fastener_search`: Search for fasteners
- `chit_chat`: General conversation

### Workflow Nodes

- **LLM Task**: Intent classification and entity extraction
- **Tool Task**: Execute external tools (order lookup, tracking, etc.)
- **Agent Task**: Determine if document retrieval is needed
- **Retrieve Task**: Fetch relevant documents from Neo4j
- **Render Task**: Format and generate final response
- **Human Review Task**: Handle refund approvals

## 🛠️ Technologies Used

- **LangGraph**: Workflow orchestration
- **LangChain**: LLM integration
- **FastAPI**: Web framework
- **Neo4j**: Graph database
- **OpenAI GPT-4o-mini**: Language model
- **Python 3.9+**: Backend language
- **HTML/CSS/JavaScript**: Frontend

## 📝 Example Queries

### Order Management

```
"Check order status for order 67890"
"price of order 12345"
"Track order 11111"
"Process refund for order 22222"
```

### Policy Questions

```
"What is your warranty policy?"
"Tell me about shipping times"
"How do I return an item?"
```

### Fastener Search

```
"Find M8 bolts"
"Search for stainless steel screws"
"What fasteners do you have in stock?"
```

## 🔍 Troubleshooting

### Neo4j Connection Issues

1. Verify Neo4j is running: `docker ps` or check Neo4j service
2. Check connection string in `.env`: `NEO4J_URI=bolt://localhost:7687`
3. Verify credentials: `NEO4J_USER` and `NEO4J_PASS`
4. Test connection: Use the "Load Order Data" button in the UI

### Port Already in Use

If port 4000 is in use, the server will automatically find the next available port. Check the console output for the actual port number.

### Order Data Not Loading

1. Ensure Neo4j is connected (green status indicator)
2. Click "Clear & Reload" to reset and reload data
3. Check server logs for error messages
4. Verify embedded data exists in `neo4j_module.py`

### Intent Classification Issues

- The system uses keyword-based classification with LLM fallback
- Price queries are automatically detected and handled
- Check server logs for intent classification details

## 📄 License

[Add your license information here]

## 🤝 Contributing

[Add contribution guidelines here]

## 📧 Support

[Add support contact information here]

---

**Built with using LangGraph, FastAPI, and Neo4j**

