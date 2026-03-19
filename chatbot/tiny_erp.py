"""
TinyERP Integration Module
Handles fetching and managing customer orders from TinyERP API based on CNPJ/CPF
"""

import json
import os
import requests
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from config import TINY_ERP_URL, TINY_ERP_API_KEY, TINY_ERP_ORDER_DETAILS_URL


def parse_date(date_str: str) -> datetime:
    """
    Parse date string in DD/MM/YYYY format to datetime object
    
    Args:
        date_str: Date string in DD/MM/YYYY format
        
    Returns:
        datetime object or min datetime if parsing fails
    """
    try:
        return datetime.strptime(date_str, '%d/%m/%Y')
    except (ValueError, AttributeError, TypeError):
        return datetime.min


# Path to store TinyERP order data
TINY_ERP_ORDERS_FILE = os.path.join(os.path.dirname(__file__), 'tiny_erp_orders.json')


def fetch_orders_from_tiny_erp(cpf_cnpj: str) -> Optional[Dict]:
    """
    Fetch orders from TinyERP API based on CPF/CNPJ number
    
    Args:
        cpf_cnpj: Customer's CPF or CNPJ number
        
    Returns:
        Dict containing order data or None if error
    """
    if not TINY_ERP_URL:
        print("[TINY_ERP] TINY_ERP_URL not configured")
        return None
    
    # Remove non-numeric characters from CPF/CNPJ
    cpf_cnpj_clean = ''.join(filter(str.isdigit, cpf_cnpj))
    
    if not cpf_cnpj_clean:
        print("[TINY_ERP] Invalid CPF/CNPJ format")
        return None
    
    try:
        # Build the API URL
        url = f"{TINY_ERP_URL}?cpf_cnpj={cpf_cnpj_clean}"
        
        # Prepare headers
        headers = {}
        if TINY_ERP_API_KEY:
            headers['x-publishable-api-key'] = TINY_ERP_API_KEY
        
        print(f"[TINY_ERP] Fetching orders for CPF/CNPJ: {cpf_cnpj_clean}")
        
        # Make API request
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"[TINY_ERP] Successfully fetched orders")
            return data
        elif response.status_code == 500 and "API Bloqueada" in response.text:
            print("[TINY_ERP] API Rate Limited (Bloqueada). Exceeded number of accesses.")
            return {"error": "rate_limit", "message": "TinyERP API Rate Limited"}
        else:
            print(f"[TINY_ERP] API request failed with status code: {response.status_code}")
            # Try to get error message from response
            try:
                error_msg = response.text[:200]  # First 200 chars
                print(f"[TINY_ERP] API error response: {error_msg}")
            except:
                pass
            return None
            
    except requests.exceptions.Timeout:
        print("[TINY_ERP] API request timed out")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[TINY_ERP] API request error: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"[TINY_ERP] JSON decode error: {e}")
        return None
    except Exception as e:
        print(f"[TINY_ERP] Unexpected error: {e}")
        return None


def parse_tiny_erp_orders(api_response: Dict) -> List[Dict]:
    """
    Parse TinyERP API response and extract relevant order information
    
    Args:
        api_response: Raw API response from TinyERP
        
    Returns:
        List of parsed order dictionaries
    """
    parsed_orders = []
    
    try:
        # Navigate to the orders array in the response structure
        retorno = api_response.get('retorno', {})
        pedidos = retorno.get('pedidos', [])
        
        for pedido_wrapper in pedidos:
            pedido = pedido_wrapper.get('pedido', {})
            
            # Extract required fields — strictly prioritizing internal 'id' for the order ID
            raw_id = pedido.get('id') or pedido.get('numero_ecommerce') or pedido.get('numero')
            order_id = str(raw_id) if raw_id else 'N/A'
            name = pedido.get('nome', 'Unknown')
            total = pedido.get('valor', 0)
            status = pedido.get('situacao', 'Unknown')
            date = pedido.get('data_pedido', '')
            tracking_code = pedido.get('codigo_rastreamento', '')
            tracking_url = pedido.get('url_rastreamento', '')
            
            # Build parsed order object
            parsed_order = {
                'order_id': order_id,
                'customer_name': name,
                'total': float(total) if total else 0.0,
                'status': status,
                'order_date': date,
                'tracking_code': tracking_code if tracking_code else None,
                'tracking_url': tracking_url if tracking_url else None
            }
            
            parsed_orders.append(parsed_order)
        
        print(f"[TINY_ERP] Parsed {len(parsed_orders)} orders")
        return parsed_orders
        
    except Exception as e:
        print(f"[TINY_ERP] Error parsing orders: {e}")
        return []


def save_orders_to_file(orders: List[Dict], cpf_cnpj: str):
    """
    Save orders to local JSON file
    
    Args:
        orders: List of parsed orders
        cpf_cnpj: Customer's CPF/CNPJ
    """
    try:
        # Load existing data or create new
        if os.path.exists(TINY_ERP_ORDERS_FILE):
            with open(TINY_ERP_ORDERS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}
        
        # Store orders by CPF/CNPJ with timestamp
        cpf_cnpj_clean = ''.join(filter(str.isdigit, cpf_cnpj))
        data[cpf_cnpj_clean] = {
            'orders': orders,
            'fetched_at': datetime.now().isoformat(),
            'total_orders': len(orders)
        }
        
        # Write to file
        with open(TINY_ERP_ORDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[TINY_ERP] Saved {len(orders)} orders to file for CPF/CNPJ: {cpf_cnpj_clean}")
        
    except Exception as e:
        print(f"[TINY_ERP] Error saving orders to file: {e}")


def load_orders_from_file(cpf_cnpj: str, ignore_ttl: bool = False) -> Optional[List[Dict]]:
    """
    Load orders from local JSON file
    
    Args:
        cpf_cnpj: Customer's CPF/CNPJ
        ignore_ttl: If True, returns cached data even if it's expired
        
    Returns:
        List of orders or None if not found
    """
    try:
        if not os.path.exists(TINY_ERP_ORDERS_FILE):
            return None
        
        # Check if file is empty
        if os.path.getsize(TINY_ERP_ORDERS_FILE) == 0:
            print("[TINY_ERP] Cache file is empty, initializing...")
            # Initialize with empty dict
            with open(TINY_ERP_ORDERS_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
            return None
        
        with open(TINY_ERP_ORDERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        cpf_cnpj_clean = ''.join(filter(str.isdigit, cpf_cnpj))
        customer_data = data.get(cpf_cnpj_clean)
        
        if customer_data:
            # --- Cache TTL check (2 hours) ---
            if not ignore_ttl:
                CACHE_TTL_HOURS = 2
                fetched_at = customer_data.get('fetched_at', '')
                try:
                    age = datetime.now() - datetime.fromisoformat(fetched_at)
                    if age > timedelta(hours=CACHE_TTL_HOURS):
                        print("[TINY_ERP] Cache expired, forcing refresh")
                        return None
                except Exception:
                    pass  # If timestamp is missing/malformed treat cache as valid
            
            print(f"[TINY_ERP] Loaded {customer_data.get('total_orders', 0)} orders from file (ignore_ttl={ignore_ttl})")
            return customer_data.get('orders', [])
        
        return None
        
    except json.JSONDecodeError as e:
        print(f"[TINY_ERP] Corrupted cache file, reinitializing: {e}")
        # Reset the file if corrupted
        try:
            with open(TINY_ERP_ORDERS_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)
        except:
            pass
        return None
    except Exception as e:
        print(f"[TINY_ERP] Error loading orders from file: {e}")
        return None


def fetch_and_store_orders(cpf_cnpj: str, force_refresh: bool = False) -> Optional[List[Dict]]:
    """
    Main function to fetch orders from API and store them
    
    Args:
        cpf_cnpj: Customer's CPF/CNPJ
        force_refresh: If True, always fetch from API even if cached
        
    Returns:
        List of parsed orders or None if error
    """
    # Try to load from cache first if not forcing refresh
    if not force_refresh:
        cached_orders = load_orders_from_file(cpf_cnpj)
        if cached_orders is not None:
            print("[TINY_ERP] Using cached orders")
            return cached_orders
    
    # Fetch from API
    api_response = fetch_orders_from_tiny_erp(cpf_cnpj)
    
    if not api_response or (isinstance(api_response, dict) and api_response.get('error') == 'rate_limit'):
        # If API fails or is rate-limited, try to use cached data as fallback (ignore TTL)
        reason = "API rate-limited" if isinstance(api_response, dict) and api_response.get('error') == 'rate_limit' else "API failed"
        print(f"[TINY_ERP] {reason}, attempting to use cached data as fallback (ignoring TTL)")
        return load_orders_from_file(cpf_cnpj, ignore_ttl=True)
    
    # Parse the orders
    parsed_orders = parse_tiny_erp_orders(api_response)
    
    if parsed_orders:
        # Save to file
        save_orders_to_file(parsed_orders, cpf_cnpj)
        return parsed_orders
    else:
        # If parsing fails or returns no orders, try fallback to cache
        print("[TINY_ERP] No orders parsed from API, checking cache as fallback")
        return load_orders_from_file(cpf_cnpj, ignore_ttl=True)
    
    return None


def format_orders_for_display(orders: List[Dict]) -> str:
    """
    Format orders into a brief user-friendly text response for cards
    
    Args:
        orders: List of parsed orders
        
    Returns:
        Brief formatted string for display
    """
    if not orders:
        return "No orders found for this CPF/CNPJ."
    
    # Sort by date (most recent first) using proper date parsing
    sorted_orders = sorted(orders, key=lambda x: parse_date(x.get('order_date', '')), reverse=True)
    
    # Show total count
    total_orders = len(orders)
    displayed_count = min(3, total_orders)
    
    if total_orders > 3:
        response = f"✅ I found **{total_orders} orders** for you! Here are your **{displayed_count} most recent orders** below. Click on any card to see more details."
    else:
        response = f"✅ I found **{total_orders} order(s)** for you! You can view the details in the cards below."
    
    return response


def format_orders_for_llm_context(orders: List[Dict]) -> str:
    """
    Format orders as system context for the LLM
    
    Args:
        orders: List of parsed orders
        
    Returns:
        Formatted string for LLM context
    """
    if not orders:
        return ""
    
    # Sort by date (most recent first) using proper date parsing
    sorted_orders = sorted(orders, key=lambda x: parse_date(x.get('order_date', '')), reverse=True)
    
    context = "System Note: TinyERP Order Data for Customer:\n\n"
    
    for idx, order in enumerate(sorted_orders, 1):
        context += f"Order {idx}:\n"
        context += f"  - Order ID: {order.get('order_id', 'N/A')}\n"
        context += f"  - Customer Name: {order.get('customer_name', 'N/A')}\n"
        context += f"  - Total: R$ {order.get('total', 0):.2f}\n"
        context += f"  - Status: {order.get('status', 'Unknown')}\n"
        context += f"  - Date: {order.get('order_date', 'N/A')}\n"
        
        if order.get('tracking_code'):
            context += f"  - Tracking Code: {order.get('tracking_code')}\n"
        
        context += "\n"
    
    context += f"Total orders found: {len(orders)}\n"
    
    return context


def fetch_order_details(order_id: str) -> str:
    """
    Fetch specific order details from TinyERP and format as LLM context
    
    Args:
        order_id: The ID of the order to fetch
        
    Returns:
        Tuple (context_string, detailed_order_dict)
    """
    if not TINY_ERP_ORDER_DETAILS_URL:
        return "", None
        
    try:
        url = f"{TINY_ERP_ORDER_DETAILS_URL}/{order_id}"
        
        headers = {}
        if TINY_ERP_API_KEY:
            headers['x-publishable-api-key'] = TINY_ERP_API_KEY
            
        print(f"[TINY_ERP] Fetching details for order: {order_id}")
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            # Handle nested structure: retorno -> pedido
            retorno = data.get('retorno', {})
            if 'pedido' in retorno:
                order_data = retorno['pedido']
            elif 'pedido' in data:
                order_data = data['pedido']
            elif 'order' in data:
                order_data = data['order']
            else:
                order_data = None
            
            # Check for API-level errors in 'retorno'
            if retorno.get('status') == 'Erro':
                errors = retorno.get('erros', [])
                error_msg = "; ".join([e.get('erro', 'Unknown error') for e in errors])
                return f"System Note: The TinyERP API returned an error for order #{order_id}: {error_msg}. Please inform the user that their request could not be completed at this moment.", None

            if not order_data:
                return f"System Note: Failed to parse details for order #{order_id}. The order may not exist or the API response was empty.", None
                
            # Try to handle Medusa-like structure or TinyERP native structure
            display_id = str(order_data.get('id', order_data.get('display_id', order_data.get('numero', order_id))))
            status = order_data.get('situacao', order_data.get('status', 'Unknown'))
            fulfillment = order_data.get('fulfillment_status', 'Unknown')
            # TinyERP uses 'total_pedido' or 'valor'
            total_raw = order_data.get('total_pedido') or order_data.get('valor') or order_data.get('total', 0)
            try:
                total = float(total_raw)
            except:
                total = 0.0
            
            # Extract items
            items_text = []
            items = order_data.get('items', [])
            
            # Handle TinyERP items format if present
            if 'itens' in order_data:
                items = order_data['itens']
                for item_wrapper in items:
                    item = item_wrapper.get('item', item_wrapper)
                    try:
                        qty = float(item.get('quantidade', 1))
                        # If it's an integer value, display as int
                        if qty == int(qty): qty = int(qty)
                    except:
                        qty = 1
                        
                    title = item.get('descricao', item.get('title', 'Item'))
                    
                    try:
                        price_raw = item.get('valor_unitario', item.get('unit_price', 0))
                        price = float(price_raw)
                    except:
                        price = 0.0
                        
                    if price > 0:
                        items_text.append(f"{qty}x {title} - R$ {price:.2f}")
                    else:
                        items_text.append(f"{qty}x {title}")
            else:
                # Handle standard format
                for item in items:
                    try:
                        qty = float(item.get('quantity', 1))
                        if qty == int(qty): qty = int(qty)
                    except:
                        qty = 1
                        
                    title = item.get('title', 'Item')
                    
                    try:
                        price_raw = item.get('unit_price', 0)
                        # Medusa uses cents, Tiny uses decimal strings
                        # Try to detect if it's cents (usually > 100 for small items)
                        price = float(price_raw)
                        if price > 1000 and not isinstance(price_raw, str): # Heuristic for Medusa cents
                             price = price / 100
                    except:
                        price = 0.0
                        
                    if price > 0:
                        items_text.append(f"{qty}x {title} - R$ {price:.2f}")
                    else:
                        items_text.append(f"{qty}x {title}")
                        
            items_str = "\\n  - ".join(items_text) if items_text else "No items found"
            
            # Format context with bypass instruction
            context = f"System Note: The user requested details for order #{display_id}. Identity and CPF have ALREADY been verified. Use the following details to answer DIRECTLY without asking for CPF/CNPJ:\\n"
            context += f"Status: {status}\\n"
            if fulfillment != 'Unknown':
                context += f"Fulfillment: {fulfillment}\\n"
            if total > 0:
                context += f"Total: {total:.2f}\\n"
                
            if isinstance(order_data.get('customer'), dict):
                customer = order_data['customer']
                email = customer.get('email', '')
                if email:
                    context += f"Customer Email: {email}\\n"
                    
            context += f"\\nItems in this order:\\n  - {items_str}\\n\\n"
            context += "Please provide a helpful summary of this order to the user."
            
            # Prepare detailed card data for frontend
            customer_name = order_data.get('nome', order_data.get('cliente', {}).get('nome', 'N/A'))
            
            detailed_order = {
                "order_id": display_id,
                "status": status,
                "total": float(total) if total else 0.0,
                "order_date": order_data.get('data_pedido', ''),
                "items": items_text,
                "customer_name": customer_name,
                "tracking_code": order_data.get('codigo_rastreamento'),
                "tracking_url": order_data.get('url_rastreamento'),
                "is_detailed": True
            }
            
            return context, detailed_order
            
        else:
            print(f"[TINY_ERP] Failed to fetch order details. Status: {response.status_code}")
            return f"System Note: The system failed to retrieve details for order #{order_id}. Error code: {response.status_code}.", None
            
    except Exception as e:
        print(f"[TINY_ERP] Error fetching order details: {e}")
        return f"System Note: There was an error trying to fetch details for order #{order_id}.", None
