# TinyERP Integration - User Guide

## Overview
The TinyERP integration allows customers to fetch their order history from the TinyERP system using their CPF or CNPJ number.

## Setup

### 1. Environment Variables
Add the following variables to your `.env` file:

```env
# TinyERP Configuration
TINY_ERP_URL=https://yogateria.medusajs.app/store/tiny-erp-orders
TINY_ERP_API_KEY=your_api_key_here
```

**Note:** Replace `your_api_key_here` with your actual TinyERP API key.

### 2. Files Created
- **`tiny_erp.py`**: Core module handling TinyERP API integration
- **`tiny_erp_orders.json`**: Local cache file (auto-generated) storing fetched orders

## How It Works

### User Flow

1. **User asks about orders:**
   ```
   User: "What are my past orders?"
   Bot: "To fetch your order history, I need your CPF or CNPJ number..."
   ```

2. **User provides CPF/CNPJ:**
   ```
   User: "12345678901"
   Bot: [Fetches orders and displays them in card format]
   ```

### Automatic Detection
The system automatically detects:
- Questions about orders: "my orders", "meus pedidos", "order history", "histórico de pedidos"
- CPF numbers: 11 digits (e.g., `12345678901` or `123.456.789-01`)
- CNPJ numbers: 14 digits (e.g., `12345678000190` or `12.345.678/0001-90`)

## API Response Format

### TinyERP API Structure
```json
{
  "retorno": {
    "status": "OK",
    "pedidos": [
      {
        "pedido": {
          "numero_ecommerce": "210391",
          "nome": "Customer Name",
          "valor": 326,
          "situacao": "Cancelado",
          "data_pedido": "31/08/2024",
          "codigo_rastreamento": "",
          "url_rastreamento": ""
        }
      }
    ]
  }
}
```

### Extracted Fields
The system extracts and displays:
- **Order ID**: `numero_ecommerce` (fallback to `numero`)
- **Customer Name**: `nome`
- **Total**: `valor` (in R$)
- **Status**: `situacao`
- **Order Date**: `data_pedido`
- **Tracking Code**: `codigo_rastreamento` (optional)
- **Tracking URL**: `url_rastreamento` (optional)

## Response Format

### Text Response
```
I found 14 order(s) for you:

**Order 1:**
- **Order ID:** cart_01KJ59S5HDND8GXQ88MA3WED1W
- **Customer:** Dharmik Patel
- **Total:** R$ 395.00
- **Status:** Em aberto
- **Date:** 23/02/2026

**Order 2:**
...
```

### JSON Response to Frontend
```json
{
  "response": "I found 14 order(s) for you...",
  "products": [],
  "orders": [
    {
      "order_id": "cart_01KJ59S5HDND8GXQ88MA3WED1W",
      "customer_name": "Dharmik Patel",
      "total": 395.0,
      "status": "Em aberto",
      "order_date": "23/02/2026",
      "tracking_code": null,
      "tracking_url": null
    }
  ],
  "message_id": 123,
  "follow_ups": [
    "Tell me more about a specific order",
    "What are the shipping options?",
    "How do I track my order?"
  ]
}
```

## Caching System

### Local Cache
- Orders are cached in `tiny_erp_orders.json` after fetching
- Cache is organized by CPF/CNPJ number
- Includes timestamp of when data was fetched

### Cache Structure
```json
{
  "12345678901": {
    "orders": [...],
    "fetched_at": "2026-03-11T10:30:00",
    "total_orders": 14
  }
}
```

### Cache Behavior
- **First request**: Fetches from API, saves to cache
- **Subsequent requests**: Returns cached data instantly
- **Force refresh**: Can be triggered programmatically with `force_refresh=True`
- **API failure**: Falls back to cached data if available

## Functions in tiny_erp.py

### Main Functions

#### `fetch_and_store_orders(cpf_cnpj, force_refresh=False)`
Main entry point - fetches orders from API or cache
- **Args**: CPF/CNPJ string, optional force_refresh flag
- **Returns**: List of parsed orders or None

#### `fetch_orders_from_tiny_erp(cpf_cnpj)`
Hits the TinyERP API endpoint
- Cleans CPF/CNPJ (removes formatting)
- Adds API key header
- Returns raw API response

#### `parse_tiny_erp_orders(api_response)`
Parses TinyERP API response structure
- Navigates nested JSON structure
- Extracts relevant fields
- Returns list of order dictionaries

#### `save_orders_to_file(orders, cpf_cnpj)`
Saves orders to local JSON cache
- Creates file if doesn't exist
- Updates existing data
- Adds timestamp

#### `load_orders_from_file(cpf_cnpj)`
Loads orders from local cache
- Returns cached orders if found
- Returns None if not cached

#### `format_orders_for_display(orders)`
Formats orders for user-friendly text display
- Sorts by date (most recent first)
- Creates bullet-point format
- Includes all relevant details

#### `format_orders_for_llm_context(orders)`
Formats orders as system context for LLM
- Used when LLM needs order context
- Structured for easy parsing

## Integration with server.py

### Detection Logic
```python
# Detect if user asks about orders
is_asking_orders = bool(re.search(
    r'(my orders|meus pedidos|past orders|order history)', 
    user_message.lower()
))

# Detect CPF/CNPJ in message
cpf_cnpj_match = re.search(
    r'\b(\d{11}|\d{14}|\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b', 
    user_message
)
```

### Flow Control
1. User asks about orders WITHOUT CPF/CNPJ → Ask for it
2. User provides CPF/CNPJ → Fetch and display orders
3. API fails → Show error message with fallback options

## Error Handling

### Scenarios Covered
- ❌ **TinyERP URL not configured**: Logs warning, returns None
- ❌ **Invalid CPF/CNPJ format**: Logs error, returns None
- ❌ **API timeout**: Logs timeout, tries cache fallback
- ❌ **API error**: Logs error, tries cache fallback
- ❌ **JSON decode error**: Logs error, returns None
- ❌ **No orders found**: Returns empty list with friendly message

### Fallback Strategy
```
API Request → Fail → Check Cache → Still Fail → Show Error
```

## Testing

### Test Cases

1. **Valid CPF/CNPJ with orders:**
   ```
   Input: "My past orders: 27005184033"
   Expected: Display all orders in card format
   ```

2. **Valid CPF/CNPJ without orders:**
   ```
   Input: "My orders: 99999999999"
   Expected: "I couldn't find any orders for CPF/CNPJ: 99999999999"
   ```

3. **Ask without CPF/CNPJ:**
   ```
   Input: "What are my past orders?"
   Expected: "To fetch your order history, I need your CPF or CNPJ..."
   ```

4. **Formatted CPF/CNPJ:**
   ```
   Input: "My orders: 123.456.789-01"
   Expected: System extracts and uses "12345678901"
   ```

## Frontend Integration

The frontend should handle the `orders` array in the response:

```javascript
// Response structure
{
  response: "I found 14 order(s)...",
  orders: [
    {
      order_id: "210391",
      customer_name: "Customer Name",
      total: 326.0,
      status: "Cancelado",
      order_date: "31/08/2024",
      tracking_code: null,
      tracking_url: null
    }
  ]
}
```

### Suggested Card Layout
```html
<div class="order-card">
  <h3>Order #210391</h3>
  <p>Customer: Customer Name</p>
  <p>Total: R$ 326.00</p>
  <p>Status: <span class="status-canceled">Cancelado</span></p>
  <p>Date: 31/08/2024</p>
</div>
```

## Maintenance

### Clearing Cache
To clear the cache, delete or clear the file:
```bash
rm chatbot/tiny_erp_orders.json
```

### Updating API URL
Update `.env` file and restart the server:
```env
TINY_ERP_URL=https://new-api-url.com/orders
```

## Troubleshooting

### Issue: "No orders found" but orders exist
- ✅ Verify CPF/CNPJ is correct
- ✅ Check if API is returning data (check logs)
- ✅ Verify `TINY_ERP_URL` is correct in `.env`

### Issue: API timeout
- ✅ Check internet connection
- ✅ Verify TinyERP API is online
- ✅ System will use cached data if available

### Issue: Orders not displaying
- ✅ Check frontend is handling `orders` array in response
- ✅ Verify JSON structure matches expected format
- ✅ Check browser console for errors

## Logs

### Successful Fetch
```
[TINY_ERP] Fetching orders for CPF/CNPJ: 27005184033
[TINY_ERP] Successfully fetched orders
[TINY_ERP] Parsed 14 orders
[TINY_ERP] Saved 14 orders to file for CPF/CNPJ: 27005184033
[SERVER] Detected CPF/CNPJ: 27005184033
```

### Cache Hit
```
[TINY_ERP] Loaded 14 orders from file
[TINY_ERP] Using cached orders
[SERVER] Detected CPF/CNPJ: 27005184033
```

### API Failure with Cache Fallback
```
[TINY_ERP] API request timed out
[TINY_ERP] API failed, attempting to use cached data
[TINY_ERP] Loaded 14 orders from file
[SERVER] Detected CPF/CNPJ: 27005184033
```

## Security Considerations

- ⚠️ CPF/CNPJ data is sensitive - ensure proper access controls
- ⚠️ Cache file contains customer information - secure appropriately
- ⚠️ API keys should never be committed to version control
- ⚠️ Consider adding rate limiting to prevent API abuse
- ⚠️ Consider encryption for cached order data

## Future Enhancements

Potential improvements:
- [ ] Cache expiration (auto-refresh after X hours)
- [ ] Order detail endpoint (fetch single order details)
- [ ] Order status updates via webhooks
- [ ] Email notifications for order status changes
- [ ] CSV export of order history
- [ ] Order filtering by date range or status
- [ ] Pagination for large order lists
