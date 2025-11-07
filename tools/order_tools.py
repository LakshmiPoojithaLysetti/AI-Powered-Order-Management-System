# tools/order_tools.py
# Order-related operations with Neo4j integration.
# Uses embedded order data from neo4j_module.py (EMBEDDED_ORDER_DATA from data.cypher).
# All order data is accessed from Neo4j database seeded from data.cypher.
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import re
import sys
from pathlib import Path

# Add parent directory to path to import neo4j_module
sys.path.insert(0, str(Path(__file__).parent.parent))
from neo4j_module import (
    async_with_session, 
    is_neo4j_available,
    get_order_status as neo4j_get_order_status,
    get_order_purchase_date as neo4j_get_order_purchase_date,
    get_order_expected_delivery as neo4j_get_order_expected_delivery,
    get_order_price as neo4j_get_order_price,
    check_return_eligibility as neo4j_check_return_eligibility,
    initiate_return_request as neo4j_initiate_return_request,
    approve_return_request as neo4j_approve_return_request,
    get_return_policy as neo4j_get_return_policy,
    get_coupon_details as neo4j_get_coupon_details,
    get_shipping_method as neo4j_get_shipping_method,
    get_tax_rate as neo4j_get_tax_rate,
    get_fraud_rules as neo4j_get_fraud_rules,
    get_payment_gateway as neo4j_get_payment_gateway,
    get_shipping_account as neo4j_get_shipping_account,
    get_product_by_name as neo4j_get_product_by_name,
    get_inventory_for_product as neo4j_get_inventory_for_product
)


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
            
            record_data = record.data() if hasattr(record, "data") else dict(record)  # type: ignore
            order = record_data.get("o") or record["o"]
            
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
            expected_delivery_raw = record_data.get("expectedDelivery") or order_dict.get("expectedDelivery")
            expected_delivery = _convert_value(expected_delivery_raw)
            
            order_date_raw = record_data.get("orderDate") or order_dict.get("orderDate")
            order_date = _convert_value(order_date_raw)
            
            # Get totalAmount from RETURN or node
            total_amount_raw = record_data.get("totalAmount") or order_dict.get("totalAmount")
            try:
                total_amount = float(total_amount_raw) if total_amount_raw is not None else 0.0
            except (ValueError, TypeError):
                total_amount = 0.0
            
            # Get status from RETURN clause first, then fallback to node properties
            # Try multiple ways to get status
            status = None
            if record_data.get("status"):
                status = record_data["status"]
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
            tracking = record_data.get("tracking") or order_dict.get("tracking")
            
            return {
                "id": order_dict.get("id") or str(order_id),
                "status": status if status else "Unknown",
                "carrier": record_data.get("carrier_name") or order_dict.get("carrier"),
                "tracking": tracking,
                "expectedDelivery": expected_delivery,
                "orderDate": order_date,
                "totalAmount": total_amount,
                "items": record_data.get("items") or [],
                "customerId": record_data.get("customer_id"),
                "customerName": record_data.get("customer_name")
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
    Look up order status from Neo4j (seeded from embedded order data in neo4j_module from data.cypher).
    All order data comes from data.cypher embedded in neo4j_module.py.
    If not found in Neo4j, return None instead of creating demo data.
    """
    if not order_id:
        return None

    # Use neo4j_module function to get order status (from data.cypher)
    status_result = await neo4j_get_order_status(order_id)
    
    if not status_result:
        print(f"[order_tools] Order {order_id} not found in Neo4j. Please ensure order data has been loaded from data.cypher using seed_order_data() or seed_order_data_async().")
        return None
    
    # Get full order details for compatibility
    order = await _get_order_from_neo4j(order_id)
    
    if order:
        print(f"[order_tools] Found order {order_id} in Neo4j (from data.cypher): {order.get('status')}")
        return order
    
    # Fallback: return status result if full order not available
    return {
        "id": status_result.get("orderId"),
        "orderId": status_result.get("orderId"),
        "status": status_result.get("status", "Unknown"),
        "orderDate": status_result.get("orderDate")
    }


async def track_order(order_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Track an order by order ID. Retrieves from Neo4j (seeded from embedded order data in neo4j_module from data.cypher).
    All order data comes from data.cypher embedded in neo4j_module.py.
    If not found in Neo4j, returns None.
    """
    if not order_id:
        return None
    
    # Get order details from Neo4j (from data.cypher)
    order = await _get_order_from_neo4j(order_id)
    
    if not order:
        print(f"[order_tools] Order {order_id} not found in Neo4j for tracking. Please ensure order data has been loaded from data.cypher using seed_order_data() or seed_order_data_async().")
        return None
    
    # Get expected delivery from neo4j_module function
    delivery_info = await neo4j_get_order_expected_delivery(order_id)
    expected_delivery = delivery_info.get("expectedDelivery") if delivery_info else order.get("expectedDelivery")
    
    # Get tracking history from Neo4j (from data.cypher)
    async def _get_tracking_history() -> List[Dict[str, Any]]:
        def _convert_value(value):
            """Convert Neo4j date/datetime objects to strings."""
            if value is None:
                return None
            if hasattr(value, "iso_format"):
                return value.iso_format()
            if hasattr(value, "to_native"):
                native = value.to_native()
                if hasattr(native, "isoformat"):
                    return native.isoformat()
                return str(native)
            if hasattr(value, "isoformat"):
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
                history: List[Dict[str, Any]] = []
                for record in result:
                    date_val = _convert_value(record.get("date"))
                    history.append(
                        {
                        "date": date_val,
                        "location": record.get("location"),
                            "status": record.get("status"),
                        }
                    )
                return history
            except Exception as e:
                print(f"[neo4j] Error retrieving tracking history: {e}")
                return []
        
        return await async_with_session(_work)

    history = await _get_tracking_history()
        
        # Get current location from most recent tracking event
        current_location = "Unknown"
    if history:
            current_location = history[0].get("location", "Unknown")
        
    # Create tracking response from order data (from data.cypher)
        tracking = {
            "orderId": order.get("id"),
            "status": order.get("status", "Unknown"),
            "carrier": order.get("carrier"),
            "trackingNumber": order.get("tracking"),
            "currentLocation": current_location,
        "estimatedDelivery": expected_delivery,
            "lastUpdate": datetime.now().isoformat(),
        "trackingHistory": history if history else [],
        }
        
        return tracking


async def process_refund(order_id: Optional[str], reason: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Process a refund request for an order with human-in-the-loop approval.
    Uses order data from Neo4j (seeded from data.cypher embedded in neo4j_module.py).
    All order data comes from data.cypher.
    
    This function ALWAYS requires human approval - it creates a pending return request
    that must be approved or rejected by a human user.
    """
    if not order_id:
        return None
    
    # Check return eligibility first (uses data from data.cypher)
    eligibility = await neo4j_check_return_eligibility(order_id)
    
    if not eligibility.get("eligible", False):
        return {
            "orderId": str(order_id),
            "refundId": None,
            "status": "Rejected",
            "amount": 0.0,
            "currency": "USD",
            "reason": reason or "Customer request",
            "message": f"Order {order_id} is not eligible for return: {eligibility.get('reason', 'Unknown reason')}",
            "eligibility": eligibility,
            "requiresApproval": False,
            "needsHumanReview": False
        }
    
    # ALWAYS require human approval for refunds
    # Initiate return request with human approval (uses data from data.cypher)
    return_request = await neo4j_initiate_return_request(order_id, reason=reason, requires_approval=True)
    
    if not return_request.get("success", False):
        return {
        "orderId": str(order_id),
            "refundId": None,
            "status": "Failed",
            "amount": 0.0,
        "currency": "USD",
        "reason": reason or "Customer request",
            "message": return_request.get("message", "Failed to process refund request"),
            "requiresApproval": False,
            "needsHumanReview": False
        }
    
    # Get order price for display
    order_price = await neo4j_get_order_price(order_id)
    total_amount = return_request.get("amount", 0.0)
    
    # Convert return request format to refund format for compatibility
    # IMPORTANT: This always requires human approval
    return {
        "orderId": return_request.get("orderId"),
        "refundId": return_request.get("returnRequestId"),
        "status": "Pending Approval",
        "amount": total_amount,
        "currency": "USD",
        "reason": return_request.get("reason", reason or "Customer request"),
        "estimatedProcessingTime": "5-7 business days",
        "requestedAt": datetime.now().isoformat(),
        "message": f"Refund request for order {order_id} (${total_amount:,.2f}) is pending approval. Please approve or reject this request.",
        "requiresApproval": True,
        "needsHumanReview": True,  # Flag to indicate workflow should pause
        "eligibility": eligibility,
        "returnRequestId": return_request.get("returnRequestId")  # Store for approval/rejection
    }


# ============================================================================
# Schema Validation Functions (UserTask1: Intake & schema validation)
# ============================================================================

def validate_order_schema(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate order data against Pydantic-like schema.
    Returns validation result with missing fields and errors.
    Used by UserTask1: Intake & schema validation (Pydantic models).
    """
    required_fields = ["orderId", "customerId", "items"]
    missing_fields = []
    errors = []
    
    for field in required_fields:
        if field not in order_data or not order_data[field]:
            missing_fields.append(field)
            errors.append(f"Missing required field: {field}")
    
    # Validate items if present
    if "items" in order_data:
        items = order_data["items"]
        if not isinstance(items, list) or len(items) == 0:
            errors.append("Items must be a non-empty list")
        else:
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    errors.append(f"Item {i} must be a dictionary")
                elif "name" not in item or "quantity" not in item:
                    errors.append(f"Item {i} missing required fields: name, quantity")
    
    is_valid = len(errors) == 0
    
    return {
        "valid": is_valid,
        "missing_fields": missing_fields,
        "errors": errors,
        "next_action": "ASK_USER" if not is_valid else None,
        "questions": [f"Please provide {field}" for field in missing_fields] if missing_fields else []
    }


# ============================================================================
# Deterministic Tool Functions (ToolTask1: tax, shipping, coupon, fraud checks)
# ============================================================================

async def calculate_tax(order_amount: float, shipping_address: Optional[str] = None) -> Dict[str, Any]:
    """
    Calculate tax for an order (non-LLM deterministic tool).
    Used by ToolTask1: Non-LLM deterministic tools (tax, shipping, coupon, fraud checks).
    """
    region = None
    if shipping_address:
        match = re.search(r'\b([A-Z]{2})\b', shipping_address.upper())
        if match:
            region = match.group(1)

    tax_info = await neo4j_get_tax_rate(region)
    tax_rate = 0.06  # fallback default
    tax_description = None
    tax_region = None

    if tax_info:
        tax_rate = float(tax_info.get("rate", tax_rate))
        tax_description = tax_info.get("description")
        tax_region = tax_info.get("region")

    tax_amount = round(order_amount * tax_rate, 2)

    return {
        "taxRate": tax_rate,
        "taxAmount": round(tax_amount, 2),
        "totalWithTax": round(order_amount + tax_amount, 2),
        "currency": "USD",
        "region": tax_region,
        "description": tax_description
    }


async def calculate_shipping(order_amount: float, shipping_method: str = "standard") -> Dict[str, Any]:
    """
    Calculate shipping cost (non-LLM deterministic tool).
    Used by ToolTask1: Non-LLM deterministic tools (tax, shipping, coupon, fraud checks).
    """
    method_id = (shipping_method or "standard").lower()
    method_info = await neo4j_get_shipping_method(method_id)

    base_rates = {
        "standard": 7.99,
        "express": 19.99,
        "overnight": 29.99,
        "free": 0.0
    }

    if not method_info and method_id not in base_rates:
        # fallback to standard if unknown
        method_info = await neo4j_get_shipping_method("standard")
        method_id = "standard"

    shipping_cost = base_rates.get(method_id, base_rates["standard"])
    delivery_estimate = "3-5 business days"
    method_name = method_id.title()

    if method_info:
        method_name = method_info.get("name", method_name)
        delivery_estimate = method_info.get("deliveryEstimate", delivery_estimate)
        base_rate = method_info.get("baseRate")
        if base_rate is not None:
            try:
                shipping_cost = float(base_rate)
            except (TypeError, ValueError):
                shipping_cost = shipping_cost

    # Free shipping threshold
    if order_amount >= 50.0 and method_id in {"standard", "free"}:
        shipping_cost = 0.0
        method_id = "free"
        method_name = "Free Shipping"

    return {
        "shippingMethod": method_id,
        "shippingLabel": method_name,
        "shippingCost": round(shipping_cost, 2),
        "estimatedDays": {
            "standard": 5,
            "express": 2,
            "overnight": 1,
            "free": 5
        }.get(method_id, 5),
        "deliveryEstimate": delivery_estimate,
        "currency": "USD"
    }


async def apply_coupon(order_amount: float, coupon_code: Optional[str] = None) -> Dict[str, Any]:
    """
    Apply coupon code and calculate discount (non-LLM deterministic tool).
    Used by ToolTask1: Non-LLM deterministic tools (tax, shipping, coupon, fraud checks).
    """
    if not coupon_code:
        return {
            "applied": False,
            "discount": 0.0,
            "finalAmount": order_amount
        }

    coupon = await neo4j_get_coupon_details(coupon_code)
    if not coupon or not coupon.get("active", False):
        return {
            "applied": False,
            "error": "Invalid or inactive coupon code",
            "discount": 0.0,
            "finalAmount": order_amount
        }

    minimum_amount = coupon.get("minimumOrderAmount") or 0.0
    if minimum_amount and order_amount < minimum_amount:
        return {
            "applied": False,
            "error": f"Coupon requires minimum order amount of ${minimum_amount:.2f}",
            "discount": 0.0,
            "finalAmount": order_amount
        }

    discount_type = (coupon.get("discountType") or "percentage").lower()
    discount_value = coupon.get("discountValue") or 0.0
    discount_amount = 0.0
    final_amount = order_amount
    metadata: Dict[str, Any] = {}

    if discount_type == "percentage":
        rate = discount_value
        if rate > 1:
            rate = rate / 100.0
        discount_amount = order_amount * rate
        final_amount = order_amount - discount_amount
        metadata["discountRate"] = rate
    elif discount_type == "flat":
        discount_amount = float(discount_value)
        final_amount = max(order_amount - discount_amount, 0.0)
    elif discount_type == "shipping":
        metadata["freeShipping"] = True
    else:
        return {
            "applied": False,
            "error": "Unsupported coupon type",
            "discount": 0.0,
            "finalAmount": order_amount
        }

    return {
        "applied": True,
        "couponCode": coupon.get("code"),
        "discountType": discount_type,
        "discount": round(discount_amount, 2),
        "finalAmount": round(final_amount, 2),
        **metadata
    }


async def fraud_check(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Perform fraud check on order (non-LLM deterministic tool).
    Used by ToolTask1: Non-LLM deterministic tools (tax, shipping, coupon, fraud checks).
    """
    risk_score = 0
    flags: List[str] = []
    manual_review_required = False

    # Neo4j-backed fraud rules
    order_amount = float(order_data.get("totalAmount", 0.0) or 0.0)
    fraud_rules = await neo4j_get_fraud_rules()
    for rule in fraud_rules:
        threshold = rule.get("thresholdAmount") or 0.0
        if threshold and order_amount >= threshold:
            risk_score += 20
            flags.append(rule.get("description") or f"Amount exceeds ${threshold:.2f}")
            if rule.get("requiresManualReview"):
                manual_review_required = True

    # Additional heuristic checks
    customer_id = order_data.get("customerId", "")
    if not customer_id or customer_id.startswith("GUEST"):
        risk_score += 15
        flags.append("Guest or missing customer ID")

    items = order_data.get("items", [])
    if len(items) > 10:
        risk_score += 10
        flags.append("Unusually high item count")

    if any((item or {}).get("price", 0.0) for item in items):
        average_price = sum((item.get("price", 0.0) or 0.0) for item in items) / max(len(items), 1)
        if average_price > 500.0:
            risk_score += 5
            flags.append("High average item price")

    # Determine risk level
    if risk_score >= 30 or manual_review_required:
        risk_level = "HIGH"
        approved = False
    elif risk_score >= 15:
        risk_level = "MEDIUM"
        approved = True
    else:
        risk_level = "LOW"
        approved = True

    return {
        "riskScore": risk_score,
        "riskLevel": risk_level,
        "approved": approved,
        "flags": flags,
        "requiresReview": manual_review_required or risk_score >= 15,
        "rulesEvaluated": [rule.get("id") for rule in fraud_rules]
    }


# ============================================================================
# External System Orchestration (AgentTask1: payment, inventory, shipping)
# ============================================================================

async def process_payment(order_data: Dict[str, Any], payment_method: str = "credit_card") -> Dict[str, Any]:
    """
    Process payment for an order (background task).
    Used by AgentTask1: Orchestrate external systems (payment, inventory hold, shipping label).
    """
    order_id = order_data.get("orderId") or order_data.get("id")
    amount = order_data.get("totalAmount", 0.0)
    gateway = await neo4j_get_payment_gateway()

    # Simulate payment processing
    import asyncio
    await asyncio.sleep(0.1)  # Simulate API call
    
    gateway_id_value = gateway.get("id") if gateway else "default-gateway"
    gateway_id = str(gateway_id_value or "default-gateway")
    payment_id = f"{gateway_id.upper()}-{order_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    provider = gateway.get("provider") if gateway else "Simulated"

    return {
        "success": True,
        "paymentId": payment_id,
        "orderId": order_id,
        "amount": amount,
        "paymentMethod": payment_method,
        "status": "completed",
        "processedAt": datetime.now().isoformat(),
        "gatewayId": gateway_id,
        "provider": provider,
        "supports3DS": gateway.get("supports3DS") if gateway else False
    }


async def hold_inventory(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Hold inventory for order items (background task).
    Used by AgentTask1: Orchestrate external systems (payment, inventory hold, shipping label).
    """
    order_id = order_data.get("orderId") or order_data.get("id")
    items = order_data.get("items", [])

    # Simulate inventory hold
    import asyncio
    await asyncio.sleep(0.1)  # Simulate API call
    
    held_items = []
    for item in items:
        item_id = item.get("id") or item.get("name")
        quantity = item.get("quantity", 0)
        product_name = item.get("name")
        product_info = await neo4j_get_product_by_name(product_name) if product_name else None
        inventory_records = await neo4j_get_inventory_for_product(product_info.get("sku") if product_info else product_name)

        total_available = sum(record.get("available", 0) for record in inventory_records)
        status = "held" if total_available >= quantity else "backorder"

        held_items.append({
            "itemId": item_id,
            "quantityRequested": quantity,
            "quantityAvailable": total_available,
            "status": status,
            "locations": inventory_records,
            "heldAt": datetime.now().isoformat()
        })

    return {
        "success": True,
        "orderId": order_id,
        "heldItems": held_items,
        "heldAt": datetime.now().isoformat()
    }


async def generate_shipping_label(order_data: Dict[str, Any], carrier: str = "UPS") -> Dict[str, Any]:
    """
    Generate shipping label for order (background task).
    Used by AgentTask1: Orchestrate external systems (payment, inventory hold, shipping label).
    """
    order_id = order_data.get("orderId") or order_data.get("id")
    shipping_account = await neo4j_get_shipping_account()

    # Simulate shipping label generation
    import asyncio
    await asyncio.sleep(0.1)  # Simulate API call
    
    carrier_name = shipping_account.get("carrier") if shipping_account else carrier
    tracking_number = f"{carrier_name}-{order_id}-{datetime.now().strftime('%Y%m%d')}"
    
    return {
        "success": True,
        "orderId": order_id,
        "trackingNumber": tracking_number,
        "carrier": carrier_name,
        "labelUrl": f"https://shipping.example.com/labels/{tracking_number}",
        "generatedAt": datetime.now().isoformat(),
        "accountNumber": shipping_account.get("accountNumber") if shipping_account else None,
        "pickupWindow": shipping_account.get("pickupWindow") if shipping_account else None
    }


# ============================================================================
# Additional helper functions using neo4j_module functions
# ============================================================================

async def get_order_price(order_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Get the price of an order from Neo4j (from data.cypher).
    All order data comes from data.cypher embedded in neo4j_module.py.
    """
    if not order_id:
        return None
    
    return await neo4j_get_order_price(order_id)


async def get_order_purchase_date(order_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Get the purchase date of an order from Neo4j (from data.cypher).
    All order data comes from data.cypher embedded in neo4j_module.py.
    """
    if not order_id:
        return None
    
    return await neo4j_get_order_purchase_date(order_id)


async def get_order_expected_delivery(order_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Get the expected delivery date of an order from Neo4j (from data.cypher).
    All order data comes from data.cypher embedded in neo4j_module.py.
    """
    if not order_id:
        return None
    
    return await neo4j_get_order_expected_delivery(order_id)


async def check_return_eligibility(order_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Check if an order is eligible for return based on 30-day return policy.
    Uses order data from Neo4j (from data.cypher).
    All order data comes from data.cypher embedded in neo4j_module.py.
    """
    if not order_id:
        return None
    
    return await neo4j_check_return_eligibility(order_id)


async def initiate_return(order_id: Optional[str], reason: Optional[str] = None, requires_approval: bool = True) -> Optional[Dict[str, Any]]:
    """
    Initiate a return request for an order with human-in-the-loop approval.
    Uses order data from Neo4j (from data.cypher).
    All order data comes from data.cypher embedded in neo4j_module.py.
    """
    if not order_id:
        return None
    
    return await neo4j_initiate_return_request(order_id, reason=reason, requires_approval=requires_approval)


async def approve_return(return_request_id: Optional[str], approved: bool = True) -> Optional[Dict[str, Any]]:
    """
    Approve or reject a return request (human-in-the-loop).
    Uses order data from Neo4j (from data.cypher).
    """
    if not return_request_id:
        return None
    
    return await neo4j_approve_return_request(return_request_id, approved=approved)


async def get_return_policy_info() -> Dict[str, Any]:
    """
    Get the return policy information.
    Returns 30-day return policy details.
    """
    return await neo4j_get_return_policy()

