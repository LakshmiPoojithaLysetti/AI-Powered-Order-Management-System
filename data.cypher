// Neo4j data seed file - Order Management System
// Usage: cat data.cypher | cypher-shell -u neo4j -p password

// Create Carriers

MERGE (ups:Carrier {name: 'UPS'})
SET ups.code = 'UPS'
SET ups.website = 'https:\/\/www.ups.com'

MERGE (fedex:Carrier {name: 'FedEx'})
SET fedex.code = 'FDX'
SET fedex.website = 'https:\/\/www.fedex.com'

MERGE (usps:Carrier {name: 'USPS'})
SET usps.code = 'USPS'
SET usps.website = 'https:\/\/www.usps.com'

MERGE (dhl:Carrier {name: 'DHL'})
SET dhl.code = 'DHL'
SET dhl.website = 'https:\/\/www.dhl.com'

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
SET order1.orderDate = date("2025-01-15")
SET order1.expectedDelivery = date("2025-01-20")
SET order1.totalAmount = 199.99
SET order1.createdAt = datetime("2025-01-15T10:30:00Z")
SET order1.updatedAt = datetime("2025-01-18T14:20:00Z")

MERGE (order1)-[:PLACED_BY]->(cust1)
MERGE (order1)-[:SHIPPED_BY]->(ups)

// Order 12345 Items
MERGE (item1_1:OrderItem {id: "12345-item-1", orderId: "12345"})
SET item1_1.name = "Product A"
SET item1_1.quantity = 2
SET item1_1.price = 99.99

MERGE (order1)-[:HAS_ITEM]->(item1_1)

// Order 12345 Tracking
MERGE (track1_1:TrackingEvent {orderId: "12345", date: datetime("2025-01-15T10:30:00Z")})
SET track1_1.location = "Warehouse"
SET track1_1.status = "Order Placed"

MERGE (track1_2:TrackingEvent {orderId: "12345", date: datetime("2025-01-16T08:15:00Z")})
SET track1_2.location = "Distribution Center"
SET track1_2.status = "Shipped"

MERGE (track1_3:TrackingEvent {orderId: "12345", date: datetime("2025-01-17T12:30:00Z")})
SET track1_3.location = "Chicago, IL"
SET track1_3.status = "In Transit"

MERGE (order1)-[:HAS_TRACKING]->(track1_1)
MERGE (order1)-[:HAS_TRACKING]->(track1_2)
MERGE (order1)-[:HAS_TRACKING]->(track1_3)

// Order 67890
MERGE (order2:Order {id: "67890"})
SET order2.status = "In Transit"
SET order2.tracking = "1Z888AA10234567890"
SET order2.orderDate = date("2025-01-20")
SET order2.expectedDelivery = date("2025-01-25")
SET order2.totalAmount = 349.99
SET order2.createdAt = datetime("2025-01-20T09:15:00Z")
SET order2.updatedAt = datetime("2025-01-21T16:45:00Z")

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

MERGE (track2_1:TrackingEvent {orderId: "67890", date: datetime("2025-01-20T09:15:00Z")})
SET track2_1.location = "Warehouse"
SET track2_1.status = "Order Placed"

MERGE (track2_2:TrackingEvent {orderId: "67890", date: datetime("2025-01-21T10:00:00Z")})
SET track2_2.location = "Distribution Center"
SET track2_2.status = "Shipped"

MERGE (track2_3:TrackingEvent {orderId: "67890", date: datetime("2025-01-21T16:45:00Z")})
SET track2_3.location = "New York, NY"
SET track2_3.status = "In Transit"

MERGE (order2)-[:HAS_TRACKING]->(track2_1)
MERGE (order2)-[:HAS_TRACKING]->(track2_2)
MERGE (order2)-[:HAS_TRACKING]->(track2_3)

// Order 11111
MERGE (order3:Order {id: "11111"})
SET order3.status = "Delivered"
SET order3.tracking = "9400111899223197428490"
SET order3.orderDate = date("2025-06-01")
SET order3.expectedDelivery = date("2025-06-05")
SET order3.totalAmount = 89.99
SET order3.createdAt = datetime("2025-06-01T11:20:00Z")
SET order3.updatedAt = datetime("2025-06-05T14:30:00Z")

MERGE (order3)-[:PLACED_BY]->(cust3)
MERGE (order3)-[:SHIPPED_BY]->(usps)

MERGE (item3_1:OrderItem {id: "11111-item-1", orderId: "11111"})
SET item3_1.name = "Product D"
SET item3_1.quantity = 1
SET item3_1.price = 89.99

MERGE (order3)-[:HAS_ITEM]->(item3_1)

MERGE (track3_1:TrackingEvent {orderId: "11111", date: datetime("2025-06-01T11:20:00Z")})
SET track3_1.location = "Warehouse"
SET track3_1.status = "Order Placed"

MERGE (track3_2:TrackingEvent {orderId: "11111", date: datetime("2025-06-02T09:00:00Z")})
SET track3_2.location = "Distribution Center"
SET track3_2.status = "Shipped"

MERGE (track3_3:TrackingEvent {orderId: "11111", date: datetime("2025-06-04T13:15:00Z")})
SET track3_3.location = "Los Angeles, CA"
SET track3_3.status = "Out for Delivery"

MERGE (track3_4:TrackingEvent {orderId: "11111", date: datetime("2025-06-05T14:30:00Z")})
SET track3_4.location = "Los Angeles, CA"
SET track3_4.status = "Delivered"

MERGE (order3)-[:HAS_TRACKING]->(track3_1)
MERGE (order3)-[:HAS_TRACKING]->(track3_2)
MERGE (order3)-[:HAS_TRACKING]->(track3_3)
MERGE (order3)-[:HAS_TRACKING]->(track3_4)

// Order 22222
MERGE (order4:Order {id: "22222"})
SET order4.status = "Processing"
SET order4.orderDate = date("2025-02-01")
SET order4.totalAmount = 159.99
SET order4.createdAt = datetime("2025-02-01T08:00:00Z")
SET order4.updatedAt = datetime("2025-02-01T08:00:00Z")

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
SET refund1.requestedAt = datetime("2025-02-01T10:00:00Z")
SET refund1.message = "Your refund request has been received and is being processed."
SET refund1.createdAt = datetime("2025-02-01T10:00:00Z")

MERGE (order4)-[:HAS_REFUND]->(refund1)

// Additional Orders

// Order 33333
MERGE (order5:Order {id: "33333"})
SET order5.status = "Pending"
SET order5.orderDate = date("2025-02-18")
SET order5.totalAmount = 299.99
SET order5.createdAt = datetime("2025-02-18T12:00:00Z")
SET order5.updatedAt = datetime("2025-02-18T12:00:00Z")

MERGE (order5)-[:PLACED_BY]->(cust2)

MERGE (item5_1:OrderItem {id: "33333-item-1", orderId: "33333"})
SET item5_1.name = "Product F"
SET item5_1.quantity = 2
SET item5_1.price = 149.99

MERGE (order5)-[:HAS_ITEM]->(item5_1)

// Order 44444
MERGE (order6:Order {id: "44444"})
SET order6.status = "Cancelled"
SET order6.orderDate = date("2025-02-12")
SET order6.totalAmount = 79.99
SET order6.createdAt = datetime("2025-02-12T15:30:00Z")
SET order6.updatedAt = datetime("2025-02-13T09:00:00Z")

MERGE (order6)-[:PLACED_BY]->(cust3)

MERGE (item6_1:OrderItem {id: "44444-item-1", orderId: "44444"})
SET item6_1.name = "Product G"
SET item6_1.quantity = 1
SET item6_1.price = 79.99

MERGE (order6)-[:HAS_ITEM]->(item6_1)


// Additional Workflow Support Data -------------------------------------------------

// Return Policy for RenderTask / UserTask2 messaging
MERGE (policy:ReturnPolicy {id: "return-policy-default"})
SET policy.description = "Items can be returned within 300 days of delivery if unused and in original packaging."
SET policy.returnWindowDays = 300
SET policy.restockingFee = 0.0
SET policy.contactEmail = "returns@example.com"

// Catalog / Inventory data for RetrievalTask1
MERGE (prodA:Product {sku: "SKU-1001"})
SET prodA.name = "High Torque Screwdriver Set"
SET prodA.category = "Fasteners"
SET prodA.price = 49.99
SET prodA.currency = "USD"

MERGE (prodB:Product {sku: "SKU-1002"})
SET prodB.name = "Industrial Bolt Pack"
SET prodB.category = "Fasteners"
SET prodB.price = 29.99
SET prodB.currency = "USD"

MERGE (prodC:Product {sku: "SKU-1003"})
SET prodC.name = "Heavy Duty Anchors"
SET prodC.category = "Hardware"
SET prodC.price = 19.99
SET prodC.currency = "USD"

MERGE (prodA)-[:HAS_INVENTORY]->(:Inventory {location: "WH-1", quantity: 150, reserved: 35})
MERGE (prodB)-[:HAS_INVENTORY]->(:Inventory {location: "WH-2", quantity: 80, reserved: 10})
MERGE (prodC)-[:HAS_INVENTORY]->(:Inventory {location: "WH-3", quantity: 200, reserved: 5})

// Coupons / Discounts for ToolTask1 deterministic tools
MERGE (coupon10:Coupon {code: "SAVE10"})
SET coupon10.description = "10% off orders over $100"
SET coupon10.discountType = "percentage"
SET coupon10.discountValue = 10
SET coupon10.minimumOrderAmount = 100
SET coupon10.active = true

MERGE (couponShip:Coupon {code: "FREESHIP"})
SET couponShip.description = "Free standard shipping on any order"
SET couponShip.discountType = "shipping"
SET couponShip.active = true

// Shipping methods for ToolTask1 calculations
MERGE (shipStd:ShippingMethod {id: "standard"})
SET shipStd.name = "Standard Ground"
SET shipStd.baseRate = 7.99
SET shipStd.deliveryEstimate = "3-5 business days"

MERGE (shipExp:ShippingMethod {id: "express"})
SET shipExp.name = "Express Air"
SET shipExp.baseRate = 19.99
SET shipExp.deliveryEstimate = "1-2 business days"

// Tax rules for deterministic tax calculation
MERGE (taxCA:TaxRate {region: "CA"})
SET taxCA.rate = 0.0825
SET taxCA.description = "California combined tax"

MERGE (taxNY:TaxRate {region: "NY"})
SET taxNY.rate = 0.08875
SET taxNY.description = "New York combined tax"

MERGE (taxDefault:TaxRate {region: "DEFAULT"})
SET taxDefault.rate = 0.06
SET taxDefault.description = "Fallback sales tax"

// Fraud rules for ToolTask1 checks
MERGE (fraudRule:FraudRule {id: "high_amount_manual"})
SET fraudRule.description = "Orders over $500 require manual review"
SET fraudRule.thresholdAmount = 500
SET fraudRule.requiresManualReview = true

// Payment processor accounts for AgentTask1 orchestration
MERGE (paymentAcct:PaymentGateway {id: "stripe-main"})
SET paymentAcct.provider = "Stripe"
SET paymentAcct.merchantId = "acct_1234567890"
SET paymentAcct.supports3DS = true

// Shipping carrier accounts for AgentTask1 label generation
MERGE (shippingAcct:ShippingAccount {id: "ups-account"})
SET shippingAcct.carrier = "UPS"
SET shippingAcct.accountNumber = "1AB234"
SET shippingAcct.pickupWindow = "16:00-18:00"

// Example background tasks for AgentTask1 reference
MERGE (bgTaskPayment:BackgroundTask {id: "BG-PAYMENT-001"})
SET bgTaskPayment.type = "payment_capture"
SET bgTaskPayment.status = "completed"
SET bgTaskPayment.details = "Captured $159.99 for order 22222 via Stripe"

MERGE (bgTaskInventory:BackgroundTask {id: "BG-INVENTORY-001"})
SET bgTaskInventory.type = "inventory_hold"
SET bgTaskInventory.status = "completed"
SET bgTaskInventory.details = "Reserved inventory for order 22222"

MERGE (bgTaskShipping:BackgroundTask {id: "BG-SHIPPING-001"})
SET bgTaskShipping.type = "shipping_label"
SET bgTaskShipping.status = "queued"
SET bgTaskShipping.details = "Awaiting label generation for order 67890"

// Link background tasks to orders where applicable
MERGE (order4)-[:HAS_BACKGROUND_TASK]->(bgTaskPayment)
MERGE (order4)-[:HAS_BACKGROUND_TASK]->(bgTaskInventory)
MERGE (order2)-[:HAS_BACKGROUND_TASK]->(bgTaskShipping)

