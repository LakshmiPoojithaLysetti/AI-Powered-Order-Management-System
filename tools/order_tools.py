# tools/order_tools.py
# Order-related operations with Neo4j integration.
# Uses embedded order data from neo4j_module.py (EMBEDDED_ORDER_DATA).
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import sys
from pathlib import Path

# Add parent directory to path to import neo4j_module
sys.path.insert(0, str(Path(__file__).parent.parent))
from neo4j_module import async_with_session, is_neo4j_available


async def _get_order_from_neo4j(order_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve order details from Neo4j."""
    if not is_neo4j_available():
        raise RuntimeError("Neo4j is required but not available. Please ensure Neo4j is running and configured.")
    
    def _convert_value(value):
        """Convert Neo4j date/datetime objects to strings."""
        if value is None:
            return None
        # Handle Neo4j date objects - convert to native Python date first
        try:
            # Try to convert Neo4j temporal types to native Python types
            if hasattr(value, 'to_native'):
                native = value.to_native()
                if hasattr(native, 'isoformat'):
                    return native.isoformat()
                if hasattr(native, 'strftime'):
                    return native.strftime('%Y-%m-%d')
                return str(native)
            # Handle Neo4j date objects with iso_format method (different versions)
            if hasattr(value, 'iso_format'):
                result = value.iso_format()
                # Extract just the date part if it's a datetime string
                if isinstance(result, str) and 'T' in result:
                    return result.split('T')[0]
                return result
            # Handle Python date/datetime objects
            if hasattr(value, 'isoformat'):
                result = value.isoformat()
                # Extract just the date part if it's a datetime string
                if isinstance(result, str) and 'T' in result:
                    return result.split('T')[0]
                return result
            if hasattr(value, 'strftime'):
                return value.strftime('%Y-%m-%d')
            # If it's already a string, return as is
            if isinstance(value, str):
                # Extract date part if it's a datetime string
                if 'T' in value:
                    return value.split('T')[0]
                return value
            return str(value)
        except Exception as e:
            print(f"[_convert_value] Error converting value {type(value)}: {e}")
            return str(value)
    
    def _work(session):
        try:
            result = session.run(
                """
                MATCH (o:Order {id: $order_id})
                OPTIONAL MATCH (o)-[:HAS_ITEM]->(item:OrderItem)
                OPTIONAL MATCH (o)-[:SHIPPED_BY]->(carrier:Carrier)
                OPTIONAL MATCH (o)-[:PLACED_BY]->(customer:Customer)
                RETURN o,
                       o.status AS status,
                       o.tracking AS tracking,
                       collect(DISTINCT {
                           id: item.id,
                           name: item.name,
                           quantity: item.quantity,
                           price: item.price
                       }) AS items,
                       carrier.name AS carrier_name,
                       customer.id AS customer_id,
                       customer.name AS customer_name,
                       o.expectedDelivery AS expectedDelivery,
                       o.orderDate AS orderDate,
                       o.totalAmount AS totalAmount
                LIMIT 1
                """,
                {"order_id": order_id}
            )
            
            record = result.single()
            if not record:
                return None
            
            order = record["o"]
            
            # Convert Neo4j node to dict for easier property access
            # Neo4j nodes can be converted to dict using dict() constructor
            try:
                order_dict = dict(order)  # type: ignore
            except (TypeError, ValueError):
                # Fallback: try to access properties directly
                order_dict = {}
                for key in ['id', 'status', 'tracking', 'carrier', 'expectedDelivery', 'orderDate', 'totalAmount']:
                    try:
                        if hasattr(order, key):
                            order_dict[key] = getattr(order, key)
                        elif hasattr(order, '__getitem__'):
                            order_dict[key] = order[key]  # type: ignore
                    except:
                        pass
            
            # Convert dates properly - prefer RETURN values, fallback to node properties
            expected_delivery_raw = record.get("expectedDelivery") or order_dict.get("expectedDelivery")
            expected_delivery = _convert_value(expected_delivery_raw)
            
            order_date_raw = record.get("orderDate") or order_dict.get("orderDate")
            order_date = _convert_value(order_date_raw)
            
            # Get totalAmount from RETURN or node
            total_amount_raw = record.get("totalAmount") or order_dict.get("totalAmount")
            try:
                total_amount = float(total_amount_raw) if total_amount_raw is not None else 0.0
            except (ValueError, TypeError):
                total_amount = 0.0
            
            # Get status from RETURN clause first, then fallback to node properties
            # Try multiple ways to get status
            status = None
            if record.get("status"):
                status = record["status"]
            elif "status" in order_dict:
                status = order_dict["status"]
            else:
                # Try to get from node directly
                try:
                    if hasattr(order, "get"):
                        status = order.get("status")  # type: ignore
                    elif hasattr(order, "__getitem__"):
                        status = order["status"]  # type: ignore
                except:
                    pass
            
            # Get tracking from RETURN clause first, then fallback to node properties
            tracking = record.get("tracking") or order_dict.get("tracking")
            
            return {
                "id": order_dict.get("id") or str(order_id),
                "status": status if status else "Unknown",
                "carrier": record.get("carrier_name") or order_dict.get("carrier"),
                "tracking": tracking,
                "expectedDelivery": expected_delivery,
                "orderDate": order_date,
                "totalAmount": total_amount,
                "items": record.get("items") or [],
                "customerId": record.get("customer_id"),
                "customerName": record.get("customer_name")
            }
        except Exception as e:
            print(f"[neo4j] Error retrieving order: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    return await async_with_session(_work)


async def _save_order_to_neo4j(order_data: Dict[str, Any]) -> bool:
    """Save or update order details in Neo4j."""
    if not is_neo4j_available():
        raise RuntimeError("Neo4j is required but not available. Please ensure Neo4j is running and configured.")
    
    def _work(session):
        try:
            order_id = order_data.get("id") or order_data.get("orderId")
            if not order_id:
                return False
            
            # Create or update Order node
            session.run(
                """
                MERGE (o:Order {id: $order_id})
                SET o.status = $status,
                    o.carrier = $carrier,
                    o.tracking = $tracking,
                    o.expectedDelivery = $expectedDelivery,
                    o.orderDate = $orderDate,
                    o.totalAmount = $totalAmount,
                    o.updatedAt = datetime()
                WITH o
                FOREACH (x IN CASE WHEN $carrier IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (c:Carrier {name: $carrier})
                    MERGE (o)-[:SHIPPED_BY]->(c)
                )
                FOREACH (x IN CASE WHEN $customerId IS NOT NULL THEN [1] ELSE [] END |
                    MERGE (cust:Customer {id: $customerId})
                    SET cust.name = $customerName
                    MERGE (o)-[:PLACED_BY]->(cust)
                )
                RETURN o
                """,
                {
                    "order_id": order_id,
                    "status": order_data.get("status"),
                    "carrier": order_data.get("carrier"),
                    "tracking": order_data.get("tracking"),
                    "expectedDelivery": order_data.get("expectedDelivery"),
                    "orderDate": order_data.get("orderDate"),
                    "totalAmount": order_data.get("totalAmount"),
                    "customerId": order_data.get("customerId"),
                    "customerName": order_data.get("customerName")
                }
            )
            
            # Create OrderItem nodes if items are provided
            items = order_data.get("items", [])
            if items:
                for item in items:
                    session.run(
                        """
                        MATCH (o:Order {id: $order_id})
                        MERGE (item:OrderItem {id: $item_id, orderId: $order_id})
                        SET item.name = $name,
                            item.quantity = $quantity,
                            item.price = $price
                        MERGE (o)-[:HAS_ITEM]->(item)
                        """,
                        {
                            "order_id": order_id,
                            "item_id": item.get("id", f"{order_id}-item-{items.index(item)}"),
                            "name": item.get("name"),
                            "quantity": item.get("quantity"),
                            "price": item.get("price")
                        }
                    )
            
            return True
        except Exception as e:
            print(f"[neo4j] Error saving order: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    result = await async_with_session(_work)
    return bool(result) if result is not None else False


async def lookup_order_status(order_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Look up order status from Neo4j (seeded from embedded order data in neo4j_module).
    If not found in Neo4j, return None instead of creating demo data.
    """
    if not order_id:
        return None

    # Query Neo4j for order from embedded order data
    order = await _get_order_from_neo4j(order_id)
    
    if order:
        print(f"[order_tools] Found order {order_id} in Neo4j: {order.get('status')}")
        return order
    
    # Order not found in Neo4j - return None
    print(f"[order_tools] Order {order_id} not found in Neo4j. Please ensure order data has been loaded using seed_order_data() or seed_order_data_async().")
    return None


async def track_order(order_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Track an order by order ID. Retrieves from Neo4j (seeded from embedded order data in neo4j_module).
    If not found in Neo4j, returns None.
    """
    if not order_id:
        return None
    
    # Try to get from Neo4j first
    order = await _get_order_from_neo4j(order_id)
    
    if order:
        # Try to get tracking history from Neo4j
        def _convert_value(value):
            """Convert Neo4j date/datetime objects to strings."""
            if value is None:
                return None
            if hasattr(value, 'iso_format'):
                return value.iso_format()
            if hasattr(value, 'to_native'):
                native = value.to_native()
                if hasattr(native, 'isoformat'):
                    return native.isoformat()
                return str(native)
            if hasattr(value, 'isoformat'):
                return value.isoformat()
            return value
        
        def _work(session):
            try:
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
                    date_val = _convert_value(record.get("date"))
                    history.append({
                        "date": date_val,
                        "location": record.get("location"),
                        "status": record.get("status")
                    })
                return history
            except Exception as e:
                print(f"[neo4j] Error retrieving tracking history: {e}")
                return []
        
        history = await async_with_session(_work)
        
        # Get current location from most recent tracking event
        current_location = "Unknown"
        if history and len(history) > 0:
            current_location = history[0].get("location", "Unknown")
        
        # Create tracking response from order data
        tracking = {
            "orderId": order.get("id"),
            "status": order.get("status", "Unknown"),
            "carrier": order.get("carrier"),
            "trackingNumber": order.get("tracking"),
            "currentLocation": current_location,
            "estimatedDelivery": order.get("expectedDelivery"),
            "lastUpdate": datetime.now().isoformat(),
            "trackingHistory": history if history else []
        }
        
        return tracking
    
    # Order not found in Neo4j - return None
    print(f"[order_tools] Order {order_id} not found in Neo4j for tracking. Please ensure order data has been loaded using seed_order_data() or seed_order_data_async().")
    return None


async def process_refund(order_id: Optional[str], reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Process a refund request for an order. Saves refund to Neo4j.
    """
    if not order_id:
        return None
    
    # Get order details first
    order = await _get_order_from_neo4j(order_id)
    refund_amount = order.get("totalAmount", "99.99") if order else "99.99"
    
    # Create refund record
    refund_id = f"RFD-{order_id}-{int(datetime.now().timestamp())}"
    refund_data = {
        "orderId": str(order_id),
        "refundId": refund_id,
        "status": "Processing",
        "amount": refund_amount,
        "currency": "USD",
        "reason": reason or "Customer request",
        "estimatedProcessingTime": "5-7 business days",
        "requestedAt": datetime.now().isoformat(),
        "message": "Your refund request has been received and is being processed."
    }
    
    # Save refund to Neo4j
    def _work(session):
        try:
            session.run(
                """
                MATCH (o:Order {id: $order_id})
                MERGE (r:Refund {id: $refund_id})
                SET r.orderId = $order_id,
                    r.status = $status,
                    r.amount = $amount,
                    r.currency = $currency,
                    r.reason = $reason,
                    r.estimatedProcessingTime = $estimatedProcessingTime,
                    r.requestedAt = $requestedAt,
                    r.message = $message,
                    r.createdAt = datetime()
                MERGE (o)-[:HAS_REFUND]->(r)
                RETURN r
                """,
                {
                    "order_id": order_id,
                    "refund_id": refund_id,
                    "status": refund_data["status"],
                    "amount": refund_data["amount"],
                    "currency": refund_data["currency"],
                    "reason": refund_data["reason"],
                    "estimatedProcessingTime": refund_data["estimatedProcessingTime"],
                    "requestedAt": refund_data["requestedAt"],
                    "message": refund_data["message"]
                }
            )
        except Exception as e:
            print(f"[neo4j] Error saving refund: {e}")
            raise
    
    await async_with_session(_work)
    
    return refund_data

