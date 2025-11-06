# neo4j_module.py
import os
import re
from pathlib import Path
from typing import Optional, Callable, Any
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

# Neo4j is REQUIRED for this application
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASS = os.getenv("NEO4J_PASS")

# Check if all required environment variables are set
if not NEO4J_URI or not NEO4J_USER or not NEO4J_PASS:
    missing = []
    if not NEO4J_URI:
        missing.append("NEO4J_URI")
    if not NEO4J_USER:
        missing.append("NEO4J_USER")
    if not NEO4J_PASS:
        missing.append("NEO4J_PASS")
    
    raise ValueError(
        f"Neo4j is REQUIRED but configuration is incomplete. "
        f"Missing environment variables: {', '.join(missing)}. "
        f"Please set NEO4J_URI, NEO4J_USER, and NEO4J_PASS in your .env file."
    )

# Initialize Neo4j driver
try:
    driver = GraphDatabase.driver(
        NEO4J_URI,
        auth=(NEO4J_USER, NEO4J_PASS)
    )
    # Verify connection by testing it
    driver.verify_connectivity()
    print(f"[neo4j] Successfully connected to Neo4j at {NEO4J_URI}")
except Exception as e:
    error_msg = getattr(e, 'message', str(e))
    raise RuntimeError(
        f"Failed to connect to Neo4j. Please ensure Neo4j is running and accessible at {NEO4J_URI}. "
        f"Error: {error_msg}"
    ) from e


def with_session(work: Callable):
    """Execute work function with a Neo4j session (synchronous)"""
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    session = driver.session()
    try:
        return work(session)
    finally:
        session.close()


async def async_with_session(work: Callable):
    """Execute work function with a Neo4j session (async wrapper)"""
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    import asyncio
    
    def _run_with_session():
        assert driver is not None  # Type narrowing: driver is checked above
        session = driver.session()
        try:
            return work(session)
        finally:
            session.close()
    
    # Run the synchronous Neo4j operations in a thread pool
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_with_session)


async def save_message(conversation_id: str, role: str, text: str):
    """Save a message to Neo4j"""
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    def _work(session):
        from datetime import datetime
        ts = datetime.utcnow().isoformat()
        import uuid
        message_id = str(uuid.uuid4())
        session.run(
            """
            MERGE (c:Conversation {id: $conversation_id})
            CREATE (m:Message {id: $message_id, role: $role, text: $text, ts: $ts})
            MERGE (c)-[:HAS_MESSAGE]->(m)
            RETURN m
            """,
            {
                "conversation_id": conversation_id,
                "message_id": message_id,
                "role": role,
                "text": text,
                "ts": ts
            }
        )
    
    await async_with_session(_work)


# Super-simple keyword retriever over documents loaded into Neo4j.
# Expect nodes (:Doc {id, title, body}).
async def retrieve_docs(query: str, limit: int = 3) -> list:
    """Retrieve documents from Neo4j matching the query"""
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    def _work(session):
        result = session.run(
            """
            MATCH (d:Doc)
            WHERE toLower(d.title) CONTAINS toLower($q)
               OR toLower(d.body)  CONTAINS toLower($q)
            RETURN d.id AS id, d.title AS title, d.body AS body
            LIMIT $limit
            """,
            {"q": query or "", "limit": limit}
        )
        return [
            {
                "id": record["id"],
                "title": record["title"],
                "body": record["body"]
            }
            for record in result
        ]
    
    result = await async_with_session(_work)
    return result or []


async def ensure_demo_docs():
    """Seed a few docs on boot (only if none exist)"""
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    def _work(session):
        result = session.run("MATCH (d:Doc) RETURN count(d) AS c")
        count = result.single()["c"]
        if count > 0:
            return

        session.run(
            'CREATE (:Doc {id: "doc1", title: "Warranty Policy", '
            'body: "Our products have a 1-year limited warranty covering manufacturing defects."})'
        )
        session.run(
            'CREATE (:Doc {id: "doc2", title: "Shipping Policy", '
            'body: "Standard shipping takes 3-5 business days. Tracking provided on dispatch."})'
        )
        session.run(
            'CREATE (:Doc {id: "doc3", title: "Returns", '
            'body: "Returns accepted within 30 days if item is unused. Contact support to get an RMA."})'
        )
    
    await async_with_session(_work)


# ============================================================================
# Embedded Order Data (from data.cypher)
# ============================================================================

EMBEDDED_ORDER_DATA = """// Neo4j data seed file - Order Management System
// Usage: cat data.cypher | cypher-shell -u neo4j -p password

// Create Carriers

MERGE (ups:Carrier {name: "UPS"})
SET ups.code = "UPS"
SET ups.website = 'https://www.ups.com'

MERGE (fedex:Carrier {name: "FedEx"})
SET fedex.code = "FDX"
SET fedex.website = 'https://www.fedex.com'

MERGE (usps:Carrier {name: "USPS"})
SET usps.code = "USPS"
SET usps.website = 'https://www.usps.com'

MERGE (dhl:Carrier {name: "DHL"})
SET dhl.code = "DHL"
SET dhl.website = 'https://www.dhl.com'

// Create Customers

MERGE (cust1:Customer {id: "customer-12345"})
SET cust1.name = "Demo Customer"
SET cust1.email = "demo.customer@example.com"
SET cust1.phone = "+1-555-0101"

MERGE (cust2:Customer {id: "customer-67890"})
SET cust2.name = "John Smith"
SET cust2.email = "john.smith@example.com"
SET cust2.phone = "+1-555-0102"

MERGE (cust3:Customer {id: "customer-11111"})
SET cust3.name = "Jane Doe"
SET cust3.email = "jane.doe@example.com"
SET cust3.phone = "+1-555-0103"

// Create Orders
MERGE (order1:Order {id: "12345"})
SET order1.status = "Shipped"
SET order1.tracking = "1Z999AA10123456784"
SET order1.orderDate = date("2024-01-15")
SET order1.expectedDelivery = date("2024-01-20")
SET order1.totalAmount = 199.99
SET order1.createdAt = datetime("2024-01-15T10:30:00Z")
SET order1.updatedAt = datetime("2024-01-18T14:20:00Z")

MERGE (order1)-[:PLACED_BY]->(cust1)
MERGE (order1)-[:SHIPPED_BY]->(ups)

// Order 12345 Items
MERGE (item1_1:OrderItem {id: "12345-item-1", orderId: "12345"})
SET item1_1.name = "Product A"
SET item1_1.quantity = 2
SET item1_1.price = 99.99

MERGE (order1)-[:HAS_ITEM]->(item1_1)

// Order 12345 Tracking
MERGE (track1_1:TrackingEvent {orderId: "12345", date: datetime("2024-01-15T10:30:00Z")})
SET track1_1.location = "Warehouse"
SET track1_1.status = "Order Placed"

MERGE (track1_2:TrackingEvent {orderId: "12345", date: datetime("2024-01-16T08:15:00Z")})
SET track1_2.location = "Distribution Center"
SET track1_2.status = "Shipped"

MERGE (track1_3:TrackingEvent {orderId: "12345", date: datetime("2024-01-17T12:30:00Z")})
SET track1_3.location = "Chicago, IL"
SET track1_3.status = "In Transit"

MERGE (order1)-[:HAS_TRACKING]->(track1_1)
MERGE (order1)-[:HAS_TRACKING]->(track1_2)
MERGE (order1)-[:HAS_TRACKING]->(track1_3)

// Order 67890
MERGE (order2:Order {id: "67890"})
SET order2.status = "In Transit"
SET order2.tracking = "1Z888AA10234567890"
SET order2.orderDate = date("2024-01-20")
SET order2.expectedDelivery = date("2024-01-25")
SET order2.totalAmount = 349.99
SET order2.createdAt = datetime("2024-01-20T09:15:00Z")
SET order2.updatedAt = datetime("2024-01-21T16:45:00Z")

MERGE (order2)-[:PLACED_BY]->(cust2)
MERGE (order2)-[:SHIPPED_BY]->(fedex)

MERGE (item2_1:OrderItem {id: "67890-item-1", orderId: "67890"})
SET item2_1.name = "Product B"
SET item2_1.quantity = 1
SET item2_1.price = 249.99

MERGE (item2_2:OrderItem {id: "67890-item-2", orderId: "67890"})
SET item2_2.name = "Product C"
SET item2_2.quantity = 1
SET item2_2.price = 99.99

MERGE (order2)-[:HAS_ITEM]->(item2_1)
MERGE (order2)-[:HAS_ITEM]->(item2_2)

MERGE (track2_1:TrackingEvent {orderId: "67890", date: datetime("2024-01-20T09:15:00Z")})
SET track2_1.location = "Warehouse"
SET track2_1.status = "Order Placed"

MERGE (track2_2:TrackingEvent {orderId: "67890", date: datetime("2024-01-21T10:00:00Z")})
SET track2_2.location = "Distribution Center"
SET track2_2.status = "Shipped"

MERGE (track2_3:TrackingEvent {orderId: "67890", date: datetime("2024-01-21T16:45:00Z")})
SET track2_3.location = "New York, NY"
SET track2_3.status = "In Transit"

MERGE (order2)-[:HAS_TRACKING]->(track2_1)
MERGE (order2)-[:HAS_TRACKING]->(track2_2)
MERGE (order2)-[:HAS_TRACKING]->(track2_3)

// Order 11111
MERGE (order3:Order {id: "11111"})
SET order3.status = "Delivered"
SET order3.tracking = "9400111899223197428490"
SET order3.orderDate = date("2024-01-10")
SET order3.expectedDelivery = date("2024-01-15")
SET order3.totalAmount = 89.99
SET order3.createdAt = datetime("2024-01-10T11:20:00Z")
SET order3.updatedAt = datetime("2024-01-15T14:30:00Z")

MERGE (order3)-[:PLACED_BY]->(cust3)
MERGE (order3)-[:SHIPPED_BY]->(usps)

MERGE (item3_1:OrderItem {id: "11111-item-1", orderId: "11111"})
SET item3_1.name = "Product D"
SET item3_1.quantity = 1
SET item3_1.price = 89.99

MERGE (order3)-[:HAS_ITEM]->(item3_1)

MERGE (track3_1:TrackingEvent {orderId: "11111", date: datetime("2024-01-10T11:20:00Z")})
SET track3_1.location = "Warehouse"
SET track3_1.status = "Order Placed"

MERGE (track3_2:TrackingEvent {orderId: "11111", date: datetime("2024-01-12T09:00:00Z")})
SET track3_2.location = "Distribution Center"
SET track3_2.status = "Shipped"

MERGE (track3_3:TrackingEvent {orderId: "11111", date: datetime("2024-01-14T13:15:00Z")})
SET track3_3.location = "Los Angeles, CA"
SET track3_3.status = "Out for Delivery"

MERGE (track3_4:TrackingEvent {orderId: "11111", date: datetime("2024-01-15T14:30:00Z")})
SET track3_4.location = "Los Angeles, CA"
SET track3_4.status = "Delivered"

MERGE (order3)-[:HAS_TRACKING]->(track3_1)
MERGE (order3)-[:HAS_TRACKING]->(track3_2)
MERGE (order3)-[:HAS_TRACKING]->(track3_3)
MERGE (order3)-[:HAS_TRACKING]->(track3_4)

// Order 22222
MERGE (order4:Order {id: "22222"})
SET order4.status = "Processing"
SET order4.orderDate = date("2024-01-25")
SET order4.totalAmount = 159.99
SET order4.createdAt = datetime("2024-01-25T08:00:00Z")
SET order4.updatedAt = datetime("2024-01-25T08:00:00Z")

MERGE (order4)-[:PLACED_BY]->(cust1)

MERGE (item4_1:OrderItem {id: "22222-item-1", orderId: "22222"})
SET item4_1.name = "Product E"
SET item4_1.quantity = 1
SET item4_1.price = 159.99

MERGE (order4)-[:HAS_ITEM]->(item4_1)

// Create Refunds

MERGE (refund1:Refund {id: "RFD-22222-1706256000"})
SET refund1.orderId = "22222"
SET refund1.status = "Processing"
SET refund1.amount = 159.99
SET refund1.currency = "USD"
SET refund1.reason = "Customer request"
SET refund1.estimatedProcessingTime = "5-7 business days"
SET refund1.requestedAt = datetime("2024-01-25T10:00:00Z")
SET refund1.message = "Your refund request has been received and is being processed."
SET refund1.createdAt = datetime("2024-01-25T10:00:00Z")

MERGE (order4)-[:HAS_REFUND]->(refund1)

// Additional Orders

// Order 33333
MERGE (order5:Order {id: "33333"})
SET order5.status = "Pending"
SET order5.orderDate = date("2024-01-28")
SET order5.totalAmount = 299.99
SET order5.createdAt = datetime("2024-01-28T12:00:00Z")
SET order5.updatedAt = datetime("2024-01-28T12:00:00Z")

MERGE (order5)-[:PLACED_BY]->(cust2)

MERGE (item5_1:OrderItem {id: "33333-item-1", orderId: "33333"})
SET item5_1.name = "Product F"
SET item5_1.quantity = 2
SET item5_1.price = 149.99

MERGE (order5)-[:HAS_ITEM]->(item5_1)

// Order 44444
MERGE (order6:Order {id: "44444"})
SET order6.status = "Cancelled"
SET order6.orderDate = date("2024-01-22")
SET order6.totalAmount = 79.99
SET order6.createdAt = datetime("2024-01-22T15:30:00Z")
SET order6.updatedAt = datetime("2024-01-23T09:00:00Z")

MERGE (order6)-[:PLACED_BY]->(cust3)

MERGE (item6_1:OrderItem {id: "44444-item-1", orderId: "44444"})
SET item6_1.name = "Product G"
SET item6_1.quantity = 1
SET item6_1.price = 79.99

MERGE (order6)-[:HAS_ITEM]->(item6_1)
"""


def parse_cypher_string(cypher_content: str) -> list[str]:
    """
    Parse Cypher content from a string and extract executable statements.
    Removes comments and empty lines, handles multi-line statements.
    Combines MERGE + SET statements into single statements for proper execution.
    
    Args:
        cypher_content: String containing Cypher statements
    
    Returns:
        List of Cypher statements ready to execute
    """
    lines = cypher_content.split('\n')
    
    statements = []
    current_statement = []
    
    for line in lines:
        # Remove single-line comments (// ...)
        line = re.sub(r"//.*$", "", line)
        line = line.rstrip()  # Only strip trailing whitespace, keep leading for indentation context
        
        # Skip empty lines - but don't finalize if we're in a MERGE block (wait for next non-empty line)
        if not line.strip():
            # Only finalize if we're NOT in a MERGE block that might have SET statements coming
            if current_statement:
                current_joined = " ".join(current_statement)
                # If we have a MERGE, don't finalize yet - wait for SET or next statement
                if not re.search(r"^\s*MERGE", current_joined, re.IGNORECASE):
                    # Not a MERGE, safe to finalize
                    statement = " ".join(current_statement).strip()
                    if statement:
                        statements.append(statement)
                    current_statement = []
            # Continue to next line (empty line doesn't break MERGE+SET blocks)
            continue
        
        # Check if line ends with semicolon (statement terminator)
        if line.endswith(";"):
            # Remove semicolon and add to current statement
            line_content = line[:-1].strip()
            if line_content:
                current_statement.append(line_content)
            # Finalize the statement
            if current_statement:
                statement = " ".join(current_statement).strip()
                if statement:
                    statements.append(statement)
                current_statement = []
        else:
            # Check if this is a new statement start
            is_merge = re.match(r"^\s*MERGE", line, re.IGNORECASE)
            is_set = re.match(r"^\s*SET", line, re.IGNORECASE)
            is_other = re.match(r"^\s*(CREATE|MATCH)", line, re.IGNORECASE)
            
            # If we have a MERGE and encounter a SET, combine them (they belong together)
            if current_statement and is_set:
                # Check if current statement starts with MERGE
                current_joined = " ".join(current_statement)
                if re.search(r"^\s*MERGE", current_joined, re.IGNORECASE):
                    # Combine MERGE + SET into one statement
                    current_statement.append(line.strip())
                else:
                    # Not a MERGE, so finalize previous and start new
                    statement = " ".join(current_statement).strip()
                    if statement:
                        statements.append(statement)
                    current_statement = [line.strip()]
            elif current_statement and (is_merge or is_other):
                # New MERGE or other statement - finalize previous
                statement = " ".join(current_statement).strip()
                if statement:
                    statements.append(statement)
                current_statement = [line.strip()]
            else:
                # Add to current statement (may continue on next line)
                current_statement.append(line.strip())
    
    # Handle any remaining statement
    if current_statement:
        statement = " ".join(current_statement).strip()
        if statement:
            statements.append(statement)
    
    return statements


# For external checks or diagnostics
def is_neo4j_available() -> bool:
    """Check if Neo4j is available and connected"""
    return driver is not None


def parse_cypher_file(file_path: str | Path) -> list[str]:
    """
    Parse a Cypher file and extract executable statements.
    Removes comments and empty lines, handles multi-line statements.
    
    In data.cypher format, each line is typically a complete statement.
    This parser handles both single-line statements and statements that
    might span multiple lines.
    
    Args:
        file_path: Path to the .cypher file
    
    Returns:
        List of Cypher statements ready to execute
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Cypher file not found: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    return parse_cypher_string(content)


def load_cypher_data(file_path: str | Path | None = None, clear_existing: bool = False, use_embedded: bool = True) -> dict[str, Any]:
    """
    Load data from a Cypher file or embedded data into Neo4j.
    
    Args:
        file_path: Path to the .cypher file. If None and use_embedded=True, uses embedded data.
        clear_existing: If True, clear all existing data before loading
        use_embedded: If True and file_path is None, use embedded order data
    
    Returns:
        Dictionary with execution statistics:
        - statements_executed: Number of statements executed
        - success: Whether all statements executed successfully
        - errors: List of any errors encountered
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    # Use embedded data if no file path provided and use_embedded is True
    if file_path is None and use_embedded:
        statements = parse_cypher_string(EMBEDDED_ORDER_DATA)
        source = "embedded data"
    elif file_path is None:
        raise ValueError("Either file_path must be provided or use_embedded must be True")
    else:
        statements = parse_cypher_file(file_path)
        source = str(file_path)
    
    if not statements:
        return {
            "statements_executed": 0,
            "success": False,
            "errors": ["No valid Cypher statements found in file"]
        }
    
    def _work(session):
        errors = []
        
        # Clear existing data if requested
        if clear_existing:
            try:
                print("[neo4j] Clearing existing data...")
                session.run("MATCH (n) DETACH DELETE n")
                print("[neo4j] Existing data cleared")
            except Exception as e:
                errors.append(f"Error clearing data: {str(e)}")
        
        # Execute each statement
        executed = 0
        for i, statement in enumerate(statements, 1):
            try:
                result = session.run(statement)
                # Consume the result to ensure it executes
                list(result)
                executed += 1
                if i % 10 == 0:
                    print(f"[neo4j] Executed {i}/{len(statements)} statements...")
            except Exception as e:
                error_msg = f"Error executing statement {i}: {str(e)}"
                errors.append(error_msg)
                print(f"[neo4j] {error_msg}")
                # Continue with next statement
                continue
        
        return {
            "statements_executed": executed,
            "success": len(errors) == 0,
            "errors": errors,
            "total_statements": len(statements)
        }
    
    print(f"[neo4j] Loading data from {source}...")
    result = with_session(_work)
    print(f"[neo4j] Data loading complete: {result['statements_executed']}/{result['total_statements']} statements executed")
    
    if result["errors"]:
        print(f"[neo4j] Encountered {len(result['errors'])} errors during loading")
    
    return result


async def load_cypher_data_async(file_path: str | Path | None = None, clear_existing: bool = False, use_embedded: bool = True) -> dict[str, Any]:
    """
    Async version of load_cypher_data.
    
    Load data from a Cypher file or embedded data into Neo4j asynchronously.
    
    Args:
        file_path: Path to the .cypher file. If None and use_embedded=True, uses embedded data.
        clear_existing: If True, clear all existing data before loading
        use_embedded: If True and file_path is None, use embedded order data
    
    Returns:
        Dictionary with execution statistics
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    # Use embedded data if no file path provided and use_embedded is True
    if file_path is None and use_embedded:
        statements = parse_cypher_string(EMBEDDED_ORDER_DATA)
        source = "embedded data"
    elif file_path is None:
        raise ValueError("Either file_path must be provided or use_embedded must be True")
    else:
        statements = parse_cypher_file(file_path)
        source = str(file_path)
    
    if not statements:
        return {
            "statements_executed": 0,
            "success": False,
            "errors": ["No valid Cypher statements found in file"]
        }
    
    def _work(session):
        errors = []
        
        # Clear existing data if requested
        if clear_existing:
            try:
                print("[neo4j] Clearing existing data...")
                session.run("MATCH (n) DETACH DELETE n")
                print("[neo4j] Existing data cleared")
            except Exception as e:
                errors.append(f"Error clearing data: {str(e)}")
        
        # Execute each statement
        executed = 0
        for i, statement in enumerate(statements, 1):
            try:
                result = session.run(statement)
                # Consume the result to ensure it executes
                list(result)
                executed += 1
                if i % 10 == 0:
                    print(f"[neo4j] Executed {i}/{len(statements)} statements...")
            except Exception as e:
                error_msg = f"Error executing statement {i}: {str(e)}"
                errors.append(error_msg)
                print(f"[neo4j] {error_msg}")
                # Continue with next statement
                continue
        
        return {
            "statements_executed": executed,
            "success": len(errors) == 0,
            "errors": errors,
            "total_statements": len(statements)
        }
    
    print(f"[neo4j] Loading data from {source} (async)...")
    result = await async_with_session(_work)
    print(f"[neo4j] Data loading complete: {result['statements_executed']}/{result['total_statements']} statements executed")
    
    if result["errors"]:
        print(f"[neo4j] Encountered {len(result['errors'])} errors during loading")
    
    return result


def seed_order_data(clear_existing: bool = False, use_file: bool = False, file_path: str | Path | None = None) -> dict[str, Any]:
    """
    Convenience function to seed order data from embedded data or file.
    
    Args:
        clear_existing: If True, clear all existing data before loading
        use_file: If True, load from file instead of embedded data
        file_path: Path to .cypher file (default: "data.cypher" if use_file=True)
    
    Returns:
        Dictionary with execution statistics
    """
    if use_file:
        path = file_path or "data.cypher"
        return load_cypher_data(path, clear_existing=clear_existing, use_embedded=False)
    else:
        return load_cypher_data(None, clear_existing=clear_existing, use_embedded=True)


async def seed_order_data_async(clear_existing: bool = False, use_file: bool = False, file_path: str | Path | None = None) -> dict[str, Any]:
    """
    Async convenience function to seed order data from embedded data or file.
    
    Args:
        clear_existing: If True, clear all existing data before loading
        use_file: If True, load from file instead of embedded data
        file_path: Path to .cypher file (default: "data.cypher" if use_file=True)
    
    Returns:
        Dictionary with execution statistics
    """
    if use_file:
        path = file_path or "data.cypher"
        return await load_cypher_data_async(path, clear_existing=clear_existing, use_embedded=False)
    else:
        return await load_cypher_data_async(None, clear_existing=clear_existing, use_embedded=True)
