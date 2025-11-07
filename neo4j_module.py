# neo4j_module.py
import os
import re
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List
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
            'body: "Returns accepted within 300 days if item is unused. Contact support to get an RMA."})'
        )
    
    await async_with_session(_work)

DATA_CYPHER_PATH = Path("data.cypher")

def load_cypher_file(file_path: Path | str = DATA_CYPHER_PATH) -> str:
    """Read the raw contents of data.cypher (or supplied file)."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Cypher file not found: {path}")
    return path.read_text(encoding="utf-8")

# ============================================================================
# Data Access Functions (parsed from data.cypher)
# ============================================================================

def get_embedded_order_data() -> dict[str, Any]:
    """
    Parse and return structured data extracted directly from data.cypher.
    Mirrors the previous embedded-data behaviour but reads from disk.
    """
    import re
    from datetime import datetime, date

    cypher_content = load_cypher_file(DATA_CYPHER_PATH)

    data = {
        "carriers": [],
        "customers": [],
        "orders": [],
        "items": [],
        "tracking_events": [],
        "refunds": []
    }

    # Parse carriers
    carrier_pattern = r'MERGE\s+\((\w+):Carrier\s+\{name:\s+"([^"]+)"\}\)'
    carrier_set_pattern = r'SET\s+(\w+)\.(\w+)\s*=\s*["\']?([^"\']+)["\']?'

    carriers = {}
    for match in re.finditer(carrier_pattern, cypher_content):
        var_name = match.group(1)
        name = match.group(2)
        carriers[var_name] = {"name": name}

    # Extract carrier properties
    for match in re.finditer(carrier_set_pattern, cypher_content):
        var_name = match.group(1)
        prop = match.group(2)
        value = match.group(3)
        if var_name in carriers:
            carriers[var_name][prop] = value

    data["carriers"] = list(carriers.values())

    # Parse customers
    customer_pattern = r'MERGE\s+\((\w+):Customer\s+\{id:\s+"([^"]+)"\}\)'
    customer_set_pattern = r'SET\s+(\w+)\.(\w+)\s*=\s*["\']?([^"\']+)["\']?'

    customers = {}
    for match in re.finditer(customer_pattern, cypher_content):
        var_name = match.group(1)
        customer_id = match.group(2)
        customers[var_name] = {"id": customer_id}

    # Extract customer properties
    for match in re.finditer(customer_set_pattern, cypher_content):
        var_name = match.group(1)
        prop = match.group(2)
        value = match.group(3)
        if var_name in customers:
            customers[var_name][prop] = value

    data["customers"] = list(customers.values())

    # Parse orders
    order_pattern = r'MERGE\s+\((\w+):Order\s+\{id:\s+"([^"]+)"\}\)'
    order_set_pattern = r'SET\s+(\w+)\.(\w+)\s*=\s*([^"\n]+)'

    orders = {}
    for match in re.finditer(order_pattern, cypher_content):
        var_name = match.group(1)
        order_id = match.group(2)
        orders[var_name] = {"id": order_id}

    # Extract order properties
    for match in re.finditer(order_set_pattern, cypher_content):
        var_name = match.group(1)
        prop = match.group(2)
        value = match.group(3).strip().strip('"').strip("'")
        if var_name in orders:
            if value.startswith('date(') or value.startswith('datetime('):
                date_match = re.search(r'["\']([^"\']+)["\']', value)
                if date_match:
                    value = date_match.group(1)
            elif value.replace('.', '').replace('-', '').isdigit():
                try:
                    value = float(value) if '.' in value else int(value)
                except Exception:
                    pass
            orders[var_name][prop] = value

    # Parse relationships to get customer and carrier for each order
    order_customer_pattern = r'MERGE\s+\((\w+)\)-\[:PLACED_BY\]->\((\w+)\)'
    order_carrier_pattern = r'MERGE\s+\((\w+)\)-\[:SHIPPED_BY\]->\((\w+)\)'

    for match in re.finditer(order_customer_pattern, cypher_content):
        order_var = match.group(1)
        customer_var = match.group(2)
        if order_var in orders and customer_var in customers:
            orders[order_var]["customerId"] = customers[customer_var]["id"]

    for match in re.finditer(order_carrier_pattern, cypher_content):
        order_var = match.group(1)
        carrier_var = match.group(2)
        if order_var in orders and carrier_var in carriers:
            orders[order_var]["carrierName"] = carriers[carrier_var]["name"]

    data["orders"] = list(orders.values())

    # Parse order items
    item_pattern = r'MERGE\s+\((\w+):OrderItem\s+\{id:\s+"([^"]+)",\s*orderId:\s+"([^"]+)"\}\)'
    item_set_pattern = r'SET\s+(\w+)\.(\w+)\s*=\s*([^"\n]+)'

    items = {}
    for match in re.finditer(item_pattern, cypher_content):
        var_name = match.group(1)
        item_id = match.group(2)
        order_id = match.group(3)
        items[var_name] = {"id": item_id, "orderId": order_id}

    for match in re.finditer(item_set_pattern, cypher_content):
        var_name = match.group(1)
        prop = match.group(2)
        value = match.group(3).strip().strip('"').strip("'")
        if var_name in items:
            if value.replace('.', '').isdigit():
                try:
                    value = float(value) if '.' in value else int(value)
                except Exception:
                    pass
            items[var_name][prop] = value

    data["items"] = list(items.values())

    # Parse tracking events
    track_pattern = r'MERGE\s+\((\w+):TrackingEvent\s+\{orderId:\s+"([^"]+)",\s*date:\s*datetime\("([^"]+)"\)\}\)'
    track_set_pattern = r'SET\s+(\w+)\.(\w+)\s*=\s*["\']?([^"\']+)["\']?'

    tracking = {}
    for match in re.finditer(track_pattern, cypher_content):
        var_name = match.group(1)
        order_id = match.group(2)
        date_str = match.group(3)
        tracking[var_name] = {"orderId": order_id, "date": date_str}

    for match in re.finditer(track_set_pattern, cypher_content):
        var_name = match.group(1)
        prop = match.group(2)
        value = match.group(3)
        if var_name in tracking:
            tracking[var_name][prop] = value

    data["tracking_events"] = list(tracking.values())

    # Parse refunds
    refund_pattern = r'MERGE\s+\((\w+):Refund\s+\{id:\s+"([^"]+)"\}\)'
    refund_set_pattern = r'SET\s+(\w+)\.(\w+)\s*=\s*([^"\n]+)'

    refunds = {}
    for match in re.finditer(refund_pattern, cypher_content):
        var_name = match.group(1)
        refund_id = match.group(2)
        refunds[var_name] = {"id": refund_id}

    for match in re.finditer(refund_set_pattern, cypher_content):
        var_name = match.group(1)
        prop = match.group(2)
        value = match.group(3).strip().strip('"').strip("'")
        if var_name in refunds:
            if value.startswith('datetime('):
                date_match = re.search(r'["\']([^"\']+)["\']', value)
                if date_match:
                    value = date_match.group(1)
            elif value.replace('.', '').isdigit():
                try:
                    value = float(value) if '.' in value else int(value)
                except Exception:
                    pass
            refunds[var_name][prop] = value

    data["refunds"] = list(refunds.values())

    return data


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
    
    target_path = Path(file_path) if file_path else DATA_CYPHER_PATH
    statements = parse_cypher_file(target_path)
    source = str(target_path)
    
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
    
    target_path = Path(file_path) if file_path else DATA_CYPHER_PATH
    statements = parse_cypher_file(target_path)
    source = str(target_path)
    
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


# ============================================================================
# Order Query Functions
# ============================================================================

async def get_order_status(order_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the status of an order from Neo4j.
    
    Args:
        order_id: Order ID to query
    
    Returns:
        Dictionary with order status and basic info, or None if not found
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    def _work(session):
        result = session.run(
            """
            MATCH (o:Order {id: $order_id})
            RETURN o.status AS status, o.id AS orderId, o.orderDate AS orderDate
            LIMIT 1
            """,
            {"order_id": order_id}
        )
        
        record = result.single()
        if not record:
            return None
        
        status = record["status"]
        order_date = record["orderDate"]
        order_id_result = record["orderId"]
        
        # Convert date if needed
        if order_date:
            if hasattr(order_date, 'iso_format'):
                order_date = order_date.iso_format()
            elif hasattr(order_date, 'to_native'):
                order_date = order_date.to_native().isoformat() if hasattr(order_date.to_native(), 'isoformat') else str(order_date)
            elif hasattr(order_date, 'isoformat'):
                order_date = order_date.isoformat()
            else:
                order_date = str(order_date)
        
        return {
            "orderId": order_id_result,
            "status": status,
            "orderDate": order_date
        }
    
    return await async_with_session(_work)


async def get_order_purchase_date(order_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the purchase date (orderDate) of an order from Neo4j.
    
    Args:
        order_id: Order ID to query
    
    Returns:
        Dictionary with order date and order ID, or None if not found
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    def _work(session):
        result = session.run(
            """
            MATCH (o:Order {id: $order_id})
            RETURN o.id AS orderId, o.orderDate AS orderDate, o.createdAt AS createdAt
            LIMIT 1
            """,
            {"order_id": order_id}
        )
        
        record = result.single()
        if not record:
            return None
        
        order_date = record["orderDate"]
        created_at = record["createdAt"]
        order_id_result = record["orderId"]
        
        # Convert dates if needed
        def _convert_date(date_val):
            if not date_val:
                return None
            if hasattr(date_val, 'iso_format'):
                return date_val.iso_format()
            elif hasattr(date_val, 'to_native'):
                native = date_val.to_native()
                if hasattr(native, 'isoformat'):
                    return native.isoformat()
                return str(native)
            elif hasattr(date_val, 'isoformat'):
                return date_val.isoformat()
            return str(date_val)
        
        return {
            "orderId": order_id_result,
            "orderDate": _convert_date(order_date),
            "createdAt": _convert_date(created_at)
        }
    
    return await async_with_session(_work)


async def get_order_expected_delivery(order_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the expected delivery date of an order from Neo4j.
    
    Args:
        order_id: Order ID to query
    
    Returns:
        Dictionary with expected delivery date and order info, or None if not found
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    def _work(session):
        result = session.run(
            """
            MATCH (o:Order {id: $order_id})
            RETURN o.id AS orderId, 
                   o.expectedDelivery AS expectedDelivery,
                   o.orderDate AS orderDate,
                   o.status AS status
            LIMIT 1
            """,
            {"order_id": order_id}
        )
        
        record = result.single()
        if not record:
            return None
        
        expected_delivery = record["expectedDelivery"]
        order_date = record["orderDate"]
        status = record["status"]
        order_id_result = record["orderId"]
        
        # Convert dates if needed
        def _convert_date(date_val):
            if not date_val:
                return None
            if hasattr(date_val, 'iso_format'):
                return date_val.iso_format()
            elif hasattr(date_val, 'to_native'):
                native = date_val.to_native()
                if hasattr(native, 'isoformat'):
                    return native.isoformat()
                return str(native)
            elif hasattr(date_val, 'isoformat'):
                return date_val.isoformat()
            return str(date_val)
        
        return {
            "orderId": order_id_result,
            "expectedDelivery": _convert_date(expected_delivery),
            "orderDate": _convert_date(order_date),
            "status": status
        }
    
    return await async_with_session(_work)


async def get_order_price(order_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the price (totalAmount) of an order from Neo4j, including item breakdown.
    
    Args:
        order_id: Order ID to query
    
    Returns:
        Dictionary with order price, items, and totals, or None if not found
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    def _work(session):
        result = session.run(
            """
            MATCH (o:Order {id: $order_id})
            OPTIONAL MATCH (o)-[:HAS_ITEM]->(item:OrderItem)
            RETURN o.id AS orderId,
                   o.totalAmount AS totalAmount,
                   collect(DISTINCT {
                       id: item.id,
                       name: item.name,
                       quantity: item.quantity,
                       price: item.price
                   }) AS items
            LIMIT 1
            """,
            {"order_id": order_id}
        )
        
        record = result.single()
        if not record:
            return None
        
        order_id_result = record["orderId"]
        total_amount = record["totalAmount"]
        items = record["items"] or []
        
        # Filter out None items
        items = [item for item in items if item.get("id")]
        
        return {
            "orderId": order_id_result,
            "totalAmount": float(total_amount) if total_amount else 0.0,
            "items": items,
            "itemCount": len(items)
        }
    
    return await async_with_session(_work)


async def check_return_eligibility(order_id: str) -> Dict[str, Any]:
    """
    Check if an order is eligible for return based on return policy (30 days from purchase).
    
    Args:
        order_id: Order ID to check
    
    Returns:
        Dictionary with eligibility status, days since purchase, and return policy info
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    from datetime import datetime, date, timedelta
    
    def _work(session):
        result = session.run(
            """
            MATCH (o:Order {id: $order_id})
            RETURN o.id AS orderId,
                   o.orderDate AS orderDate,
                   o.status AS status,
                   o.totalAmount AS totalAmount
            LIMIT 1
            """,
            {"order_id": order_id}
        )
        
        record = result.single()
        if not record:
            return {
                "orderId": order_id,
                "eligible": False,
                "reason": "Order not found",
                "daysSincePurchase": None,
                "returnPolicyDays": 300
            }
        
        order_date = record["orderDate"]
        status = record["status"]
        total_amount = record["totalAmount"]
        
        # Convert Neo4j date to Python date
        if hasattr(order_date, 'to_native'):
            order_date_py = order_date.to_native()
        elif hasattr(order_date, 'year'):
            # Already a date-like object
            order_date_py = date(order_date.year, order_date.month, order_date.day)
        else:
            # Try to parse string
            try:
                if isinstance(order_date, str):
                    order_date_py = datetime.fromisoformat(order_date.split('T')[0]).date()
                else:
                    order_date_py = date.today()
            except:
                order_date_py = date.today()
        
        # Calculate days since purchase
        today = date.today()
        days_since_purchase = (today - order_date_py).days
        
        # Check eligibility
        return_policy_days = 300
        eligible = days_since_purchase <= return_policy_days
        
        # Additional checks
        reasons = []
        if not eligible:
            reasons.append(f"Order is {days_since_purchase} days old, exceeds {return_policy_days} day return policy")
        
        if status == "Delivered":
            pass
        elif status in ["Cancelled", "Refunded"]:
            eligible = False
            reasons.append(f"Order status is {status}, cannot return")
        else:
            eligible = False
            reasons.append(f"Order status is {status}, order must be delivered before it can be returned")
        
        return {
            "orderId": order_id,
            "eligible": eligible,
            "daysSincePurchase": days_since_purchase,
            "returnPolicyDays": return_policy_days,
            "orderDate": order_date_py.isoformat() if isinstance(order_date_py, date) else str(order_date_py),
            "status": status,
            "totalAmount": float(total_amount) if total_amount else 0.0,
            "reason": "; ".join(reasons) if reasons else "Order is eligible for return",
            "daysRemaining": max(0, return_policy_days - days_since_purchase) if eligible else 0
        }
    
    return await async_with_session(_work)


async def initiate_return_request(order_id: str, reason: Optional[str] = None, requires_approval: bool = True) -> Dict[str, Any]:
    """
    Initiate a return request for an order with human-in-the-loop approval.
    
    Args:
        order_id: Order ID to return
        reason: Optional reason for return
        requires_approval: If True, requires human approval before processing
    
    Returns:
        Dictionary with return request status and approval requirement
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    # First check eligibility
    eligibility = await check_return_eligibility(order_id)
    
    if not eligibility.get("eligible", False):
        return {
            "success": False,
            "orderId": order_id,
            "requiresApproval": False,
            "message": f"Order {order_id} is not eligible for return: {eligibility.get('reason', 'Unknown reason')}",
            "eligibility": eligibility
        }
    
    # Get order details
    order_price = await get_order_price(order_id)
    total_amount = order_price.get("totalAmount", 0.0) if order_price else 0.0
    
    from datetime import datetime
    import uuid
    
    return_request_id = f"RET-{order_id}-{int(datetime.utcnow().timestamp())}"
    
    if requires_approval:
        # Create return request that needs approval
        def _work(session):
            session.run(
                """
                MATCH (o:Order {id: $order_id})
                MERGE (r:ReturnRequest {id: $return_id})
                SET r.orderId = $order_id,
                    r.status = "Pending Approval",
                    r.amount = $amount,
                    r.reason = $reason,
                    r.requestedAt = datetime(),
                    r.requiresApproval = true,
                    r.currency = "USD"
                MERGE (o)-[:HAS_RETURN_REQUEST]->(r)
                RETURN r
                """,
                {
                    "order_id": order_id,
                    "return_id": return_request_id,
                    "amount": total_amount,
                    "reason": reason or "Customer request"
                }
            )
        
        await async_with_session(_work)
        
        return {
            "success": True,
            "orderId": order_id,
            "returnRequestId": return_request_id,
            "requiresApproval": True,
            "status": "Pending Approval",
            "message": f"Return request created for order {order_id}. Awaiting human approval.",
            "amount": total_amount,
            "reason": reason or "Customer request",
            "eligibility": eligibility
        }
    else:
        # Auto-approve and process
        def _work(session):
            session.run(
                """
                MATCH (o:Order {id: $order_id})
                MERGE (r:ReturnRequest {id: $return_id})
                SET r.orderId = $order_id,
                    r.status = "Approved",
                    r.amount = $amount,
                    r.reason = $reason,
                    r.requestedAt = datetime(),
                    r.approvedAt = datetime(),
                    r.requiresApproval = false,
                    r.currency = "USD"
                MERGE (o)-[:HAS_RETURN_REQUEST]->(r)
                SET o.status = "Returned"
                RETURN r
                """,
                {
                    "order_id": order_id,
                    "return_id": return_request_id,
                    "amount": total_amount,
                    "reason": reason or "Customer request"
                }
            )
        
        await async_with_session(_work)
        
        return {
            "success": True,
            "orderId": order_id,
            "returnRequestId": return_request_id,
            "requiresApproval": False,
            "status": "Approved",
            "message": f"Return request for order {order_id} has been approved and processed.",
            "amount": total_amount,
            "reason": reason or "Customer request",
            "eligibility": eligibility
        }


async def approve_return_request(return_request_id: str, approved: bool = True) -> Dict[str, Any]:
    """
    Approve or reject a return request (human-in-the-loop).
    
    Args:
        return_request_id: Return request ID to approve/reject
        approved: True to approve, False to reject
    
    Returns:
        Dictionary with approval status
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")
    
    from datetime import datetime
    
    def _work(session):
        if approved:
            result = session.run(
                """
                MATCH (r:ReturnRequest {id: $return_id})
                MATCH (r)<-[:HAS_RETURN_REQUEST]-(o:Order)
                SET r.status = "Approved",
                    r.approvedAt = datetime(),
                    o.status = "Returned"
                RETURN r, o.id AS orderId
                """,
                {"return_id": return_request_id}
            )
        else:
            result = session.run(
                """
                MATCH (r:ReturnRequest {id: $return_id})
                SET r.status = "Rejected",
                    r.rejectedAt = datetime()
                RETURN r
                """,
                {"return_id": return_request_id}
            )
        
        record = result.single()
        if not record:
            return None
        
        return {
            "returnRequestId": return_request_id,
            "approved": approved,
            "status": "Approved" if approved else "Rejected",
            "orderId": record.get("orderId") if approved else None
        }
    
    result = await async_with_session(_work)
    
    if not result:
        return {
            "success": False,
            "returnRequestId": return_request_id,
            "message": "Return request not found"
        }
    
    return {
        "success": True,
        "message": f"Return request {return_request_id} has been {'approved' if approved else 'rejected'}.",
        **result
    }


async def get_return_policy() -> Dict[str, Any]:
    """
    Get the return policy information from Neo4j.

    Returns:
        Dictionary with return policy details
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    def _work(session):
        result = session.run(
            """
            MATCH (p:ReturnPolicy)
            RETURN p.id AS id,
                   p.description AS description,
                   coalesce(p.returnWindowDays, 30) AS returnWindowDays,
                   coalesce(p.restockingFee, 0.0) AS restockingFee,
                   p.contactEmail AS contactEmail
            ORDER BY p.returnWindowDays DESC
            LIMIT 1
            """
        )
        return result.single()

    record = await async_with_session(_work)

    if not record:
        return {
            "returnPolicyDays": 300,
            "description": "Returns are accepted within 300 days of purchase date",
            "conditions": [
                "Item must be in original condition",
                "Original packaging preferred",
                "Refund will be processed to original payment method",
                "Processing time: 5-7 business days after approval"
            ],
            "eligibleStatuses": ["Delivered", "Shipped"],
            "nonEligibleStatuses": ["Cancelled", "Refunded", "Processing", "Pending"],
            "restockingFee": 0.0,
            "contactEmail": None
        }

    return {
        "id": record.get("id"),
        "returnPolicyDays": int(record.get("returnWindowDays", 300)),
        "description": record.get("description"),
        "restockingFee": float(record.get("restockingFee", 0.0)),
        "contactEmail": record.get("contactEmail"),
        "conditions": [
            "Item must be in original condition",
            "Original packaging preferred",
            "Refund will be processed to original payment method",
            "Processing time: 5-7 business days after approval"
        ],
        "eligibleStatuses": ["Delivered", "Shipped"],
        "nonEligibleStatuses": ["Cancelled", "Refunded", "Processing", "Pending"]
    }

async def get_coupon_details(coupon_code: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Retrieve coupon details from Neo4j.
    """
    if not coupon_code:
        return None

    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    code = coupon_code.upper()

    def _work(session):
        result = session.run(
            """
            MATCH (c:Coupon {code: $code})
            RETURN c.code AS code,
                   c.description AS description,
                   c.discountType AS discountType,
                   c.discountValue AS discountValue,
                   c.minimumOrderAmount AS minimumOrderAmount,
                   coalesce(c.active, false) AS active
            LIMIT 1
            """,
            {"code": code}
        )
        return result.single()

    record = await async_with_session(_work)
    if not record:
        return None

    discount_value = record.get("discountValue")
    if discount_value is not None:
        try:
            discount_value = float(discount_value)
        except (TypeError, ValueError):
            discount_value = 0.0

    minimum_amount = record.get("minimumOrderAmount")
    if minimum_amount is not None:
        try:
            minimum_amount = float(minimum_amount)
        except (TypeError, ValueError):
            minimum_amount = 0.0

    return {
        "code": record.get("code"),
        "description": record.get("description"),
        "discountType": record.get("discountType"),
        "discountValue": discount_value,
        "minimumOrderAmount": minimum_amount,
        "active": bool(record.get("active")),
    }


async def get_shipping_method(method_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Retrieve shipping method details from Neo4j.
    """
    if not method_id:
        return None

    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    def _work(session):
        result = session.run(
            """
            MATCH (s:ShippingMethod {id: $id})
            RETURN s.id AS id,
                   s.name AS name,
                   s.baseRate AS baseRate,
                   s.deliveryEstimate AS deliveryEstimate
            LIMIT 1
            """,
            {"id": method_id}
        )
        return result.single()

    record = await async_with_session(_work)
    if not record:
        return None

    base_rate = record.get("baseRate")
    if base_rate is not None:
        try:
            base_rate = float(base_rate)
        except (TypeError, ValueError):
            base_rate = 0.0

    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "baseRate": base_rate,
        "deliveryEstimate": record.get("deliveryEstimate"),
    }


async def get_tax_rate(region: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Retrieve tax rate information from Neo4j.
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    candidates: List[str] = []
    if region:
        candidates.append(region.upper())
    candidates.append("DEFAULT")

    def _work(session):
        result = session.run(
            """
            MATCH (t:TaxRate)
            WHERE t.region IN $regions
            RETURN t.region AS region,
                   t.rate AS rate,
                   t.description AS description
            ORDER BY CASE WHEN t.region = "DEFAULT" THEN 1 ELSE 0 END
            LIMIT 1
            """,
            {"regions": candidates}
        )
        return result.single()

    record = await async_with_session(_work)
    if not record:
        return None

    rate = record.get("rate")
    if rate is not None:
        try:
            rate = float(rate)
        except (TypeError, ValueError):
            rate = 0.0

    return {
        "region": record.get("region"),
        "rate": rate,
        "description": record.get("description"),
    }


async def get_fraud_rules() -> List[Dict[str, Any]]:
    """
    Retrieve fraud rules from Neo4j.
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    def _work(session):
        result = session.run(
            """
            MATCH (r:FraudRule)
            RETURN r.id AS id,
                   r.description AS description,
                   r.thresholdAmount AS thresholdAmount,
                   coalesce(r.requiresManualReview, false) AS requiresManualReview
            """
        )
        return list(result)

    records = await async_with_session(_work) or []
    rules: List[Dict[str, Any]] = []

    for record in records:
        threshold = record.get("thresholdAmount")
        if threshold is not None:
            try:
                threshold = float(threshold)
            except (TypeError, ValueError):
                threshold = 0.0

        rules.append(
            {
                "id": record.get("id"),
                "description": record.get("description"),
                "thresholdAmount": threshold,
                "requiresManualReview": bool(record.get("requiresManualReview")),
            }
        )

    return rules


async def get_payment_gateway(gateway_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieve payment gateway configuration from Neo4j.
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    gateway_id = gateway_id or "stripe-main"

    def _work(session):
        result = session.run(
            """
            MATCH (g:PaymentGateway {id: $id})
            RETURN g.id AS id,
                   g.provider AS provider,
                   g.merchantId AS merchantId,
                   coalesce(g.supports3DS, false) AS supports3DS
            LIMIT 1
            """,
            {"id": gateway_id}
        )
        return result.single()

    record = await async_with_session(_work)
    if not record:
        return None

    return {
        "id": record.get("id"),
        "provider": record.get("provider"),
        "merchantId": record.get("merchantId"),
        "supports3DS": bool(record.get("supports3DS")),
    }


async def get_shipping_account(account_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Retrieve shipping carrier account information from Neo4j.
    """
    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    account_id = account_id or "ups-account"

    def _work(session):
        result = session.run(
            """
            MATCH (a:ShippingAccount {id: $id})
            RETURN a.id AS id,
                   a.carrier AS carrier,
                   a.accountNumber AS accountNumber,
                   a.pickupWindow AS pickupWindow
            LIMIT 1
            """,
            {"id": account_id}
        )
        return result.single()

    record = await async_with_session(_work)
    if not record:
        return None

    return {
        "id": record.get("id"),
        "carrier": record.get("carrier"),
        "accountNumber": record.get("accountNumber"),
        "pickupWindow": record.get("pickupWindow"),
    }


async def get_product_by_name(product_name: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Retrieve a product by name.
    """
    if not product_name:
        return None

    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    def _work(session):
        result = session.run(
            """
            MATCH (p:Product)
            WHERE toLower(p.name) = toLower($name)
            RETURN p.sku AS sku,
                   p.name AS name,
                   p.category AS category,
                   p.price AS price,
                   p.currency AS currency
            LIMIT 1
            """,
            {"name": product_name}
        )
        return result.single()

    record = await async_with_session(_work)
    if not record:
        return None

    price = record.get("price")
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = 0.0

    return {
        "sku": record.get("sku"),
        "name": record.get("name"),
        "category": record.get("category"),
        "price": price,
        "currency": record.get("currency"),
    }


async def get_inventory_for_product(product_identifier: Optional[str]) -> List[Dict[str, Any]]:
    """
    Retrieve inventory records for a product by name or SKU.
    """
    if not product_identifier:
        return []

    if not driver:
        raise RuntimeError("Neo4j driver is not initialized. Neo4j is required for this application.")

    def _work(session):
        result = session.run(
            """
            MATCH (p:Product)
            WHERE toLower(p.name) = toLower($identifier) OR toLower(p.sku) = toLower($identifier)
            MATCH (p)-[:HAS_INVENTORY]->(inv:Inventory)
            RETURN inv.location AS location,
                   inv.quantity AS quantity,
                   inv.reserved AS reserved
            """,
            {"identifier": product_identifier}
        )
        return list(result)

    records = await async_with_session(_work) or []
    inventory: List[Dict[str, Any]] = []

    for record in records:
        quantity = record.get("quantity")
        reserved = record.get("reserved")

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            quantity = 0

        try:
            reserved = int(reserved)
        except (TypeError, ValueError):
            reserved = 0

        inventory.append(
            {
                "location": record.get("location"),
                "quantity": quantity,
                "reserved": reserved,
                "available": max(quantity - reserved, 0),
            }
        )

    return inventory
