"""
TinyERP Integration Module
Handles fetching and managing customer orders from TinyERP API based on CNPJ/CPF
"""

import json
import os
import requests
from typing import Optional, Dict, List
from datetime import datetime
from config import TINY_ERP_URL, TINY_ERP_API_KEY


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
            
            # Extract required fields
            order_id = pedido.get('numero_ecommerce', '') or pedido.get('numero', 'N/A')
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


def load_orders_from_file(cpf_cnpj: str) -> Optional[List[Dict]]:
    """
    Load orders from local JSON file
    
    Args:
        cpf_cnpj: Customer's CPF/CNPJ
        
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
            print(f"[TINY_ERP] Loaded {customer_data.get('total_orders', 0)} orders from file")
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
    
    if not api_response:
        # If API fails, try to use cached data as fallback
        print("[TINY_ERP] API failed, attempting to use cached data")
        return load_orders_from_file(cpf_cnpj)
    
    # Parse the orders
    parsed_orders = parse_tiny_erp_orders(api_response)
    
    if parsed_orders:
        # Save to file
        save_orders_to_file(parsed_orders, cpf_cnpj)
        return parsed_orders
    
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
