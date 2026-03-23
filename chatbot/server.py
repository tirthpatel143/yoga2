from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel
from chatbot import setup_chatbot
from typing import List, Optional, Dict
import nest_asyncio
import uvicorn
import json
import db
import requests
import re
from urllib.parse import quote, urlparse
from config import ORDER_API_URL, X_PUBLISHABLE_KEY, PRODUCT_DATA_PATH
import tiny_erp

"""
ORDER SYSTEM ARCHITECTURE:
--------------------------
1. TinyERP Orders (PRIMARY for CPF/CNPJ queries):
   - Source: TinyERP API -> stored in tiny_erp_orders.json
   - Used when: User provides CPF/CNPJ to search orders
   - Contains: Brazilian customer orders with CPF/CNPJ identification
   
2. Legacy Orders (SECONDARY for user_id/email queries):
   - Source: orders.json (Medusa/legacy system)
   - Used when: User logs in with email/user_id (non-CPF/CNPJ flow)
   - Contains: Customer metadata and order info for email-based authentication
   
IMPORTANT: When in TinyERP conversation flow (CPF/CNPJ-based), do NOT mix with legacy orders.
"""

# Fix for "asyncio.run() cannot be called from a running event loop"
nest_asyncio.apply()

@asynccontextmanager
async def lifespan(app: FastAPI):
    global chat_engine, product_lookup
    print("Building product lookup cache...")
    product_lookup = build_product_lookup()
    
    print("Initializing Database...")
    db.init_db()
    
    print("Initializating Chatbot Engine...")
    chat_engine = setup_chatbot()
    yield
    print("Application shutdown complete.")

app = FastAPI(title="Yogateria Chatbot API", lifespan=lifespan)

# Enable CORS for frontend interaction
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

 # Global instances
chat_engine = None
product_lookup = {}
product_variants = {}

# Conversation state tracker for order queries
conversation_state = {}

def _canonical_color_terms(text: str):
    """Map raw color/design strings to a small set of canonical color names."""
    if not text:
        return set()
    t = text.lower()
    color_map = {
        "green": ["green", "verde", "esmeralda", "verde oliva", "verde alecrim", "verde floresta", "verde musgo", "verde militar", "verde escuro", "verde pistache"],
        "blue": ["blue", "azul", "azul escuro", "azul claro", "azul céu", "azul índigo", "azul marinho", "azul mar", "azul / aqua"],
        "black": ["black", "preto", "preto e branco", "preto e verde"],
        "white": ["white", "branco", "offwhite"],
        "red": ["red", "vermelho", "vermelho / laranja", "amora", "amora / rosa", "rosa", "rosa chá", "rosa goiaba", "rosa orquídea", "bordô", "vinho","burgundy"],
        "beige": ["beige", "bege", "bege escuro", "bege e azul", "madurai / bege"],
        "purple": ["purple", "roxo", "lilás", "lilás / azul"],
        "pink": ["pink", "pink / roxo"],
        "brown": ["brown", "marrom", "café", "cacau", "cinza eucalipto", "telha", "terracota"],
        "grey": ["grey", "gray", "cinza", "cinza claro", "cinza / ameixa", "cinza nude", "grafite"],
        "gold": ["gold", "dourado", "açafrão", "amarelo", "amarelo ocre"],
        "turquoise": ["turquoise", "turquesa", "petróleo", "oceano"],
        "orange": ["orange", "laranja"],
        "nude": ["nude"],
        "blueberry": ["blueberry / vanilla"],
        "mandala": ["mandala / azul escuro"],
        "paisley": ["paisley / petróleo"],
        "raja": ["raja / nude"],
        "mayuri": ["mayuri / bordô"],
        "madurai": ["madurai / bege"],
        "leaves": ["leaves / esmeralda"],
        "lotus": ["lótus / amora"],
        "bandhani": ["bandhani / preto e branco"],
        "amazonia": ["amazônia / preto e verde"],
        "caatinga": ["caatinga / pêssego e azul"],
        "atlantica": ["atlântica / azul e petróleo"],
        "cerrado": ["cerrado / ameixa e rosê"],
        "pantanal": ["pantanal / bege e azul"],
        "ameixa": ["ameixa"],
        "aqua": ["aqua"],
        "yellow": ["yellow", "amarelo", "amarelo ocre", "açafrão"],
    }
    result = set()
    for canon, aliases in color_map.items():
        for a in aliases:
            if a in t:
                result.add(canon)
                break
    return result


def _extract_colors_from_query(text: str):
    """Return canonical color names mentioned in user query/response."""
    if not text:
        return set()
    return _canonical_color_terms(text)


def build_product_lookup():
    """Build caches of product and variant details for the UI cards."""
    global product_variants
    try:
        if not PRODUCT_DATA_PATH:
            print("PRODUCT_DATA_PATH not set; skipping product lookup build.")
            return {}

        with open(PRODUCT_DATA_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)

        lookup = {}
        product_variants = {}

        for p in data.get("products", []):
            title = p.get("title")
            if not title:
                continue

            handle = p.get("handle", "")
            base_url = f"https://test.yogateria.com.br/produto/{handle}" if handle else "https://test.yogateria.com.br/"

            # Base product card (fallback when no specific variant is requested)
            price = "Available on site"
            variants = p.get("variants", [])
            if variants:
                calc = variants[0].get("calculated_price", {})
                if calc.get("calculated_amount"):
                    price = f"R$ {calc['calculated_amount']}"

            subtitle_raw = p.get("subtitle") or ""
            # Simple HTML tag removal for subtitle consistency in UI cards
            subtitle_clean = re.sub(r'<[^>]+>', '', subtitle_raw).strip() if subtitle_raw else ""

            lookup[title] = {
                "title": title,
                "subtitle": subtitle_clean,
                "price": price,
                "image": p.get("thumbnail") or (p.get("images")[0]["url"] if p.get("images") else "https://via.placeholder.com/200"),
                "url": base_url,
            }

            # Build variant-level entries keyed per product
            key = title.lower()
            product_variants[key] = []

            # Map variant_id -> variant object for URL parameters if needed
            variant_by_id = {v.get("id"): v for v in variants if v.get("id")}
            
            # Create a mapping from option values to variants with their thumbnails and full options
            variant_option_map = {}
            for v in variants:
                # Get variant thumbnail from product_variant_images
                variant_thumb = None
                pvi = v.get("product_variant_images", {})
                if pvi and isinstance(pvi, dict):
                    variant_thumb = pvi.get("thumbnail")
                
                # Map option values to this variant (store all options for URL building)
                v_options = v.get("options", [])
                for v_opt in v_options:
                    v_opt_value = v_opt.get("value", "")
                    if v_opt_value:
                        variant_option_map[v_opt_value] = {
                            "thumbnail": variant_thumb,
                            "variant_id": v.get("id"),
                            "price": v.get("calculated_price", {}).get("calculated_amount"),
                            "options": v_options  # Store all options for dynamic URL building
                        }

            # Options can be "cor" or "design" according to user
            for opt in p.get("options", []):
                opt_title = (opt.get("title") or "").strip().lower()
                if opt_title not in ("cor", "design"):
                    continue

                for val in opt.get("values", []):
                    raw_value = val.get("value") or ""
                    if not raw_value:
                        continue

                    colors = _canonical_color_terms(raw_value)
                    
                    # Get variant-specific thumbnail and details
                    variant_info = variant_option_map.get(raw_value, {})
                    thumb = variant_info.get("thumbnail") or lookup[title]["image"]
                    variant_id = variant_info.get("variant_id")
                    variant_price = f"R$ {variant_info['price']}" if variant_info.get("price") else price

                    # Build a variant-specific URL with query parameters
                    # Extract all options from the variant to build dynamic URL
                    # Example: ?Cor=Cinza&Espessura=4mm&Material=Borracha+natural
                    variant_url = base_url
                    if variant_id:
                        variant_options = variant_info.get("options", [])
                        
                        if variant_options:
                            query_params = []
                            for v_opt in variant_options:
                                opt_value = v_opt.get("value", "")
                                # Get option metadata to retrieve the option title/name
                                opt_metadata = v_opt.get("option", {})
                                if isinstance(opt_metadata, dict):
                                    opt_title = opt_metadata.get("title", "")
                                else:
                                    opt_title = ""
                                
                                # Build query parameter with proper URL encoding
                                if opt_title and opt_value:
                                    query_params.append(f"{quote(opt_title)}={quote(opt_value)}")
                            
                            if query_params:
                                variant_url = f"{base_url}?{'&'.join(query_params)}"
                        
                        print(f"[VARIANT URL DEBUG] Product: {title}, Color: {raw_value}, Variant ID: {variant_id}, URL: {variant_url}")

                    product_variants[key].append(
                        {
                            "title": title,
                            "subtitle": p.get("subtitle") or "",
                            "price": variant_price,
                            "image": thumb,
                            "url": variant_url,
                            "variant_id": variant_id,  # Include variant_id for frontend
                            "variant_label": raw_value,
                            "colors": list(colors) if colors else [],
                        }
                    )

        return lookup
    except Exception as e:
        print(f"Lookup Error: {e}")
        return {}

# Startup logic handled by lifespan

class ChatRequest(BaseModel):
    message: str
    user_id: Optional[str] = None
    product_url: Optional[str] = None

class FeedbackRequest(BaseModel):
    message_id: int
    feedback: str # "up" or "down"

@app.post("/feedback")
def submit_feedback(request: FeedbackRequest):
    """Submit feedback (thumbs up/down) for a chat message."""
    print(f"Received feedback '{request.feedback}' for message ID: {request.message_id}")
    
    if request.feedback not in ["up", "down"]:
        raise HTTPException(status_code=400, detail="Feedback must be 'up' or 'down'")
    
    # Update main table
    try:
        success = db.update_chat_feedback(request.message_id, request.feedback)
        if not success:
            print(f"Failed to update chat_history for ID {request.message_id}")
            raise HTTPException(status_code=500, detail="Failed to save feedback to history")

        # Save to specific tables as well
        if request.feedback == "up":
            print(f"Saving to GOOD_FEEDBACK table for ID {request.message_id}")
            db.save_good_feedback(request.message_id)
        elif request.feedback == "down":
            print(f"Saving to BAD_FEEDBACK table for ID {request.message_id}")
            db.save_bad_feedback(request.message_id)
            
        print("Feedback saved successfully.")
        return {"status": "success", "message": "Feedback received"}
    except Exception as e:
        print(f"Feedback Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    """Check server and database status."""
    db_status = "connected"
    db_rows = 0
    try:
        conn = db.get_db_connection()
        if conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM chat_history")
            db_rows = cur.fetchone()[0]
            cur.close()
            conn.close()
        else:
            db_status = "disconnected"
    except Exception as e:
        db_status = f"error: {str(e)}"
    
    return {
        "status": "ok",
        "chatbot_ready": chat_engine is not None,
        "database": db_status,
        "total_chat_messages": db_rows
    }

@app.get("/history")
def get_chat_history(limit: int = 50):
    """Retrieve chat history from the database."""
    try:
        conn = db.get_db_connection()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        cur = conn.cursor()
        cur.execute(
            "SELECT id, user_message, bot_response, timestamp FROM chat_history ORDER BY timestamp DESC LIMIT %s",
            (limit,)
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        
        history = [
            {
                "id": row[0],
                "user_message": row[1],
                "bot_response": row[2],
                "timestamp": row[3].isoformat() if row[3] else None
            }
            for row in rows
        ]
        return {"total": len(history), "history": history}
    except HTTPException:
        raise
    except Exception as e:
        print(f"History Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/history")
def clear_chat_history():
    """Clear all chat history from the database."""
    try:
        conn = db.get_db_connection()
        if not conn:
            raise HTTPException(status_code=500, detail="Database connection failed")
        
        cur = conn.cursor()
        cur.execute("DELETE FROM chat_history")
        deleted = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        return {"message": f"Cleared {deleted} chat messages from history"}
    except HTTPException:
        raise
    except Exception as e:
        print(f"Clear History Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/{user_id}")
def get_user_info(user_id: str):
    import os
    try:
        order_path = os.path.join(os.path.dirname(__file__), 'orders.json')
        if os.path.exists(order_path):
            with open(order_path, 'r', encoding='utf-8') as f:
                order_data = json.load(f)
            
            for order in order_data.get('orders', []):
                customer = order.get('customer', {})
                uid = str(customer.get('id', '')).lower()
                uemail = str(customer.get('email', '')).lower()
                query = str(user_id).lower()
                
                if uid == query or uemail == query:
                    first_name = customer.get('first_name')
                    last_name = customer.get('last_name')
                    email = customer.get('email', '')
                    
                    name = ""
                    if first_name and last_name:
                        name = f"{first_name} {last_name}"
                    elif first_name:
                        name = first_name
                    elif email:
                        name = email.split('@')[0]
                    else:
                        name = "User"
                        
                    return {"name": name, "email": email}
                    
        return {"name": user_id, "email": ""}
    except Exception as e:
        print(f"Error fetching user info: {e}")
        return {"name": user_id, "email": ""}

def fetch_order_info(query: str, user_id: str = None) -> str:
    if not ORDER_API_URL:
        return ""
        
    match = re.search(r'(order|pedido|cart|carrinho)\s*#?\s*([a-zA-Z0-9_-]+)', query, re.IGNORECASE)
    if not match:
        return ""
        
    req_type = match.group(1).lower()
    item_id = match.group(2)
    is_cart = req_type in ['cart', 'carrinho'] or item_id.startswith('cart_')
    
    headers = {}
    if X_PUBLISHABLE_KEY:
        headers['x-publishable-api-key'] = X_PUBLISHABLE_KEY
        
    try:
        if is_cart:
            cart_api_url = ORDER_API_URL.replace('/orders', '/carts')
            url = f"{cart_api_url}/{item_id}"
            resp = requests.get(url, headers=headers)
            
            if resp.status_code == 200:
                data = resp.json().get('cart', {})
                items = []
                for item in data.get('items', []):
                    qty = item.get('quantity', 1)
                    title = item.get('title', 'Item')
                    items.append(f"{qty}x {title}")
                    
                items_str = ", ".join(items) if items else "No items found"
                return f"System Note: The user (ID: {user_id}) is asking about cart #{item_id}. API Data: Items: {items_str}."
            else:
                return f"System Note: Could not fetch cart {item_id}. Status Code: {resp.status_code}"
        else:
            # Try getting by ID
            url = f"{ORDER_API_URL}/{item_id}"
            resp = requests.get(url, headers=headers)
            
            # If order not found by ID, try grabbing by display ID
            if resp.status_code == 404:
                url2 = f"{ORDER_API_URL}?display_id={item_id}"
                # Medusa often requires email along with display_id to fetch orders
                if user_id:
                    url2 += f"&email={user_id}"
                    
                resp2 = requests.get(url2, headers=headers)
                if resp2.status_code == 200:
                    orders = resp2.json().get('orders', [])
                    if orders:
                        data = orders[0]
                    else:
                        return f"System Note: No order found for display_id {item_id} and email {user_id}."
                else:
                    return f"System Note: Could not fetch order. Ensure the User ID (Email) matches the order email."
            elif resp.status_code == 200:
                data = resp.json().get('order', {})
            else:
                return ""
                
            status = data.get('status', 'unknown')
            fulfillment = data.get('fulfillment_status', 'unknown')
            
            items = []
            for item in data.get('items', []):
                qty = item.get('quantity', 1)
                title = item.get('title', 'Item')
                items.append(f"{qty}x {title}")
                
            items_str = ", ".join(items) if items else "No items found"
            return f"System Note: The user (ID: {user_id}) is asking about order #{item_id}. API Data: Status={status}, Fulfillment={fulfillment}. Items: {items_str}."
            
    except Exception as e:
        print(f"Error fetching API: {e}")
        return ""

def fetch_all_orders_for_user(user_id: str) -> str:
    if not user_id:
        return ""
    
    # Check local mock data in carts.json first
    import os
    info = ""
    try:
        carts_path = os.path.join(os.path.dirname(__file__), 'carts.json')
        if os.path.exists(carts_path):
            with open(carts_path, 'r', encoding='utf-8') as f:
                carts_data = json.load(f)
            
            for user in carts_data.get('users', []):
                uid = str(user.get('user_id', '')).lower()
                uemail = str(user.get('email', '')).lower()
                query = str(user_id).lower()
                if uid == query or uemail == query:
                    cart = user.get('cart', {})
                    info += f"System Note: The current user is {user.get('name')} (Email: {user.get('email')}, Phone: {user.get('phone')}).\n"
                    info += f"Delivery Address: {user.get('address')}.\n"
                    info += "They have the following recent tracked order items in their account:\n"
                    for item in cart.get('items', []):
                        info += f"- {item.get('quantity')}x {item.get('product_name')} (Variant: {item.get('variant')}) - Unit Price: R$ {item.get('unit_price')}\n"
                    info += f"Total: R$ {cart.get('cart_total')}. Free Shipping: {cart.get('free_shipping')}.\n"
                    return info
    except Exception as e:
        print(f"Error reading carts.json: {e}")

    try:
        order_path = os.path.join(os.path.dirname(__file__), 'orders.json')
        if os.path.exists(order_path):
            with open(order_path, 'r', encoding='utf-8') as f:
                order_data = json.load(f)
            
            user_orders = []
            for order in order_data.get('orders', []):
                uid = str(order.get('customer_id', '')).lower()
                customer = order.get('customer', {})
                uemail = str(customer.get('email', '')).lower()
                query = str(user_id).lower()
                if uid == query or uemail == query:
                    user_orders.append(order)
            
            if user_orders:
                info += f"\nSystem Note: The user also has {len(user_orders)} actual completed/past orders:\n"
                for o in user_orders[:10]: # limit to last 10
                    display_id = o.get('display_id', o.get('id', 'unknown'))
                    status = o.get('status', 'unknown')
                    fulfillment = o.get('fulfillment_status', 'unknown')
                    created_at = o.get('created_at', 'unknown').split('T')[0]
                    items = []
                    calc_total = 0
                    for item in o.get('items', []):
                        qty = item.get('quantity', 1)
                        title = item.get('product_title', item.get('title', 'Item'))
                        variant = item.get('variant_title', '')
                        u_price = item.get('unit_price', 0)
                        calc_total += (u_price * qty)
                        if variant and variant.lower() != 'default title':
                            items.append(f"{qty}x {title} ({variant}) - Unit Price: R$ {u_price}")
                        else:
                            items.append(f"{qty}x {title} - Unit Price: R$ {u_price}")
                            
                    items_str = ", ".join(items) if items else "No items found"
                    
                    summary_total = o.get('summary', {}).get('current_order_total', 0)
                    total = calc_total if calc_total > summary_total else summary_total
                    if calc_total > 0 and summary_total < 10: # Handle weird low totals in specific dumps
                         total = calc_total
                         
                    info += f"- Order #{display_id} (Date: {created_at}): Status={status}, Fulfillment={fulfillment}, Total: R$ {total}, Items: {items_str}.\n"
                return info # return here since we got local order data perfectly
            
            if info: # if we got cart info but no orders
                return info
    except Exception as e:
        print(f"Error reading order.json: {e}")

    # Fallback to API if ORDER_API_URL is configured
    if not ORDER_API_URL:
        return ""
        
    headers = {}
    if X_PUBLISHABLE_KEY:
        headers['x-publishable-api-key'] = X_PUBLISHABLE_KEY
        
    try:
        url = f"{ORDER_API_URL}?email={user_id}"
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            orders = resp.json().get('orders', [])
            if not orders:
                return f"System Note: The user {user_id} has no past orders."
                
            info += f"System Note: The user {user_id} has {len(orders)} orders available:\n"
            for data in orders[:5]: # limit to last 5 orders to save context
                status = data.get('status', 'unknown')
                display_id = data.get('display_id', data.get('id', 'unknown'))
                fulfillment = data.get('fulfillment_status', 'unknown')
                items = []
                for item in data.get('items', []):
                    qty = item.get('quantity', 1)
                    title = item.get('title', 'Item')
                    items.append(f"{qty}x {title}")
                items_str = ", ".join(items) if items else "No items found"
                info += f"- Order #{display_id}: Status={status}, Fulfillment={fulfillment}, Items: {items_str}.\n"
            return info
    except Exception as e:
        print(f"Error fetching orders for user: {e}")
        
    return ""

def extract_handle_from_url(url: str) -> Optional[str]:
    """Extract product handle from Yogateria URL robustly."""
    if not url:
        return None
    
    try:
        # Strip query and fragments
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        query = parsed.query
        
        # 1. Try common query parameter 'handle'
        handle_match = re.search(r'handle=([^&]+)', query)
        if handle_match:
            return handle_match.group(1)
            
        # 2. Try patterns with regex (prioritize specific product paths)
        patterns = [
            r'/produto/([^/?#]+)',
            r'/produtos-meditacao/([^/?#]+)',
            r'/tapetes-de-yoga/([^/?#]+)',
            r'/roupas-yoga/([^/?#]+)',
            r'/acessorios-yoga/([^/?#]+)',
            r'/peso-kali/([^/?#]+)',
            r'yogateria\.com\.br/([^/?#]+)/?$'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                res = match.group(1).rstrip('/')
                if res and len(res) > 2:
                    return res
        
        # 3. Fallback: the last NON-EMPTY segment of the path usually contains the handle
        segments = [s for s in path.split('/') if s]
        if segments:
            handle = segments[-1]
            if handle and len(handle) > 2:
                return handle.strip()
    except Exception as e:
        print(f"Error extracting handle: {e}")
        
    return None

def find_product_by_handle(handle: str, product_data: List[Dict]) -> Optional[Dict]:
    """Find product in catalog by its handle."""
    if not handle:
        return None
    for p in product_data:
        if p.get('handle') == handle or p.get('id') == handle:
            return p
    return None

def generate_llm_questions(product: Dict) -> List[str]:
    """Use the LLM to generate 4 relevant questions for a specific product."""
    from llama_index.core import Settings
    try:
        title = product.get('title', 'this product')
        description = product.get('description', '')[:1000] # Use first 1000 chars for context
        
        prompt = f"""As a Yogateria expert, generate 4 short, engaging, and specific questions a customer would ask about this product.
        Product: {title}
        Context: {description}
        
        ### LANGUAGE REQUIREMENT:
        **THE QUESTIONS MUST BE IN ENGLISH.** Even if the product title or description is in Portuguese or any other language, you MUST generate the 4 questions in English.
        
        Guidelines:
        - Make questions specific to the product type (e.g., if it's a book, ask about content/author; if a mat, ask about grip/thickness).
        - Keep them under 10 words each.
        - Return ONLY the questions, one per line, no numbering or extra text.
        """
        
        print(f"\n[LLM CALL] Generating Product Questions using {Settings.llm.model}...")
        response = Settings.llm.complete(prompt)
        # Filter and clean questions
        questions = []
        for line in str(response).split('\n'):
            q = line.strip().strip('"').strip("'").strip("-").strip("*").strip("123456789. ")
            if q and '?' in q:
                # Basic length sanity check
                if 5 < len(q) < 100:
                    questions.append(q)
        
        if not questions:
            # Fallback if LLM fails to format correctly
            return [
                f"What are the main features of {title}?",
                "What are the materials used?",
                "Is it suitable for beginners?",
                "What are the shipping options?"
            ]
        return questions[:4]
    except Exception as e:
        print(f"Error generating LLM questions: {e}")
        return ["Tell me more about this product.", "What are the features?", "What is the price?", "Is it available?"]

def clean_and_extract_follow_ups(resp_text: str) -> tuple[str, list[str]]:
    """
    Clean the LLM response text by removing 'FOLLOW-UPS' segment and extracting bullet points.
    Handles variations like '### FOLLOW-UPS:', '**FOLLOW-UPS:**', etc.
    """
    follow_ups = []
    # Use regex to find ANY variation of FOLLOW-UPS (###, ##, #, or none, with bolding/space)
    # Handles "### FOLLOW-UPS:", "**FOLLOW-UPS:**", "FOLLOW-UPS:", etc.
    pattern = r"(?i)(?:#{1,3}\s*|\*\*|__)*FOLLOW-UPS(?:\s*|:|\*\*|__)*"
    
    if re.search(pattern, resp_text, flags=re.MULTILINE):
        # We found a match. Let's split it.
        # we want to split by the first occurrence of the FOLLOW-UPS header
        parts = re.split(pattern, resp_text, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) > 1:
            clean_text = parts[0].strip()
            follow_ups_raw = parts[1].strip().split("\n")
            for line in follow_ups_raw:
                line = line.strip()
                # Extract question and remove bullet markers
                if line.startswith("- ") or line.startswith("* ") or line.startswith("• "):
                    follow_ups.append(line[2:].strip())
                elif line.startswith(tuple("123456789")):
                    # Handle numbered bullets too just in case
                    q = re.sub(r'^\d+\.?\s*', '', line).strip()
                    if q: follow_ups.append(q)
                elif "?" in line and len(line) > 5:
                    follow_ups.append(line.strip())
            return clean_text, follow_ups
            
    return resp_text, []

@app.post("/chat")
def chat_endpoint(request: ChatRequest):
    global chat_engine, product_lookup
    if not chat_engine:
        raise HTTPException(status_code=500, detail="Chatbot engine not initialized")
    
    try:
        user_message = request.message
        user_id = request.user_id
        product_url = request.product_url
        
        # --- Product Redirection / Context Logic ---
        product_context = ""
        suggested_questions = [] # Questions suggested by LLM for specific products
        inline_buttons = [] # Structured buttons to be rendered INSIDE the bubble
        is_url_turn = False
        if not product_url:
            url_match = re.search(r'https?://[^\s]+', user_message)
            if url_match:
                product_url = url_match.group(0)
        
        if product_url:
            handle = extract_handle_from_url(product_url)
            print(f"[PRODUCT REDIRECT] Handle: {handle} from URL: {product_url}")
            
            # Load product data for lookup
            with open(PRODUCT_DATA_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                catalog = data.get("products", [])
            
            product = find_product_by_handle(handle, catalog)
            
            # Determine if this is a "pure URL" message
            is_pure_url = user_message.strip() == product_url or not user_message.strip().replace(product_url, '').strip()
            
            if product:
                title = product.get('title')
                product_context = f"System Note: The user is currently viewing the product page for '{title}'. Here is the product description and features:\n"
                product_context += f"Description: {product.get('description')}\n"
                
                # Fetch variants for better context
                variants = product.get('variants', [])
                if variants:
                    product_context += "Available variants and prices:\n"
                    for v in variants:
                        price = v.get('calculated_price', {}).get('calculated_amount', 'N/A')
                        product_context += f"- {v.get('title')}: R$ {price}\n"
                
                # Use LLM to generate intelligent, product-specific questions
                suggested_questions = generate_llm_questions(product)
                
                # If pure URL, return activation response with intelligent inline buttons
                if is_pure_url:
                    resp_text = f"I see you're interested in the **{title}**! What would you like to know about it?"
                    
                    message_id = db.save_chat_message(request.message, resp_text)
                    print(f"[DEBUG] Pure URL activation response with {len(suggested_questions)} inline buttons: {suggested_questions}")
                    return {
                        "response": resp_text,
                        "products": [], 
                        "orders": [],
                        "message_id": message_id,
                        "follow_ups": [], # Clear follow-ups to keep it focused on the inline buttons
                        "inline_buttons": suggested_questions  # Contextual buttons for this product
                    }
            elif is_pure_url:
                # Recognizable URL but not in static catalog - avoid "cannot browse" fallback
                if "yogateria.com.br" in product_url.lower():
                    resp_text = "I see you've shared a Yogateria product link! While I don't have this specific item's details handy in my quick-lookup catalog, I can still help. What would you like to know about our products, or are you looking for a similar item?"
                    message_id = db.save_chat_message(request.message, resp_text)
                    return {
                        "response": resp_text,
                        "products": [],
                        "orders": [],
                        "message_id": message_id,
                        "follow_ups": ["See all products", "How can I track my order?", "Tell me about yoga mats"]
                    }
        
        # --------------------------------------------

        # If the user explicitly puts a user ID in the chat, override the stored one
        id_match = re.search(r'cus_[a-zA-Z0-9]+', user_message)
        if id_match:
            user_id = id_match.group(0)
            
        # Also check for emails inside the chat message
        email_match = re.search(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', user_message)
        if email_match:
            user_id = email_match.group(0)
        
        # --- TinyERP Orders Integration (CPF/CNPJ based) ---
        # Generate a unique session key for this user
        session_key = user_id if user_id else "anonymous"
        print(f"[DEBUG] session_key: {session_key}")
        print(f"[DEBUG] active conversation_state keys: {list(conversation_state.keys())}")
        if session_key in conversation_state:
             print(f"[DEBUG] state for this session: {conversation_state[session_key]}")

        
        # --- Check if user clicked an order card to view its details ---
        specific_order_details_match = re.search(r'(?:Show details for order|View details for order|Show details for|Pedido)\s*#?\s*([a-zA-Z0-9_\-]+)', user_message, re.IGNORECASE)
        if specific_order_details_match:
            order_id = specific_order_details_match.group(1)
            details_context, detailed_order = tiny_erp.fetch_order_details(order_id)
            
            try:
                system_msg = f"{details_context}\n\nPlease format the order details concisely and clearly for the user. Highlight the items and status."
                response = chat_engine.chat(system_msg)
                resp_text = str(response)
                # Clean and extract follow-ups to prevent them from printing in the text box
                resp_text, llm_follow_ups = clean_and_extract_follow_ups(resp_text)
            except Exception as e:
                print(f"Chat Error during order details: {e}")
                llm_follow_ups = []
                # Fallback text if LLM fails
                if detailed_order:
                    items_list = "\n".join([f"- {item}" for item in detailed_order.get('items', [])])
                    resp_text = f"Here are the details for your order **#{detailed_order['order_id']}**:\n\n"
                    resp_text += f"**Status:** {detailed_order['status']}\n"
                    resp_text += f"**Total:** R$ {detailed_order['total']:.2f}\n\n"
                    resp_text += f"**Items:**\n{items_list}\n"
                else:
                    resp_text = f"I was able to find order #{order_id}, but I'm having trouble retrieving the full details right now. Please try again in a moment."

            message_id = db.save_chat_message(request.message, resp_text)
            
            # Combine navigational buttons with LLM questions if any (limit to 5)
            nav_buttons = ["Show my recent orders", "Search by order date", "Search by order ID"]
            final_fups = list(set(nav_buttons + llm_follow_ups))
            if len(final_fups) > 5:
                final_fups = final_fups[:5]
            
            return {
                "response": resp_text,
                "products": [],
                "orders": [detailed_order] if detailed_order else [],
                "message_id": message_id,
                "follow_ups": final_fups,
                "inline_buttons": []
            }
        # --- Check for active TinyERP conversation states first to prevent loops ---
        
        # Check if we're in a state waiting for order search preference
        if session_key in conversation_state and conversation_state[session_key].get('awaiting_order_choice'):
            cpf_cnpj = conversation_state[session_key]['cpf_cnpj']
            
            # Check user's choice (adding support for exact button text and short codes)
            wants_recent = bool(re.search(r'(recent|last|latest|3|recentes|^1$|1\w|one)', user_message.lower().strip()))
            wants_search = bool(re.search(r'(date|order id|search|data|id do pedido|número|^2$|2\w|two)', user_message.lower().strip()))
            print(f"[DEBUG] wants_recent: {wants_recent}, wants_search: {wants_search}")

            
            if wants_recent:
                # User wants last 3 recent orders
                orders = tiny_erp.fetch_and_store_orders(cpf_cnpj)
                
                if orders:
                    sorted_orders = sorted(
                        orders, 
                        key=lambda x: tiny_erp.parse_date(x.get('order_date', '')), 
                        reverse=True
                    )
                    
                    # Prepare data for frontend cards (limit to 3 most recent)
                    orders_cards = []
                    for order in sorted_orders[:3]:
                        orders_cards.append({
                            "order_id": order.get('order_id', 'N/A'),
                            "customer_name": order.get('customer_name', 'N/A'),
                            "total": order.get('total', 0),
                            "status": order.get('status', 'Unknown'),
                            "order_date": order.get('order_date', ''),
                            "tracking_code": order.get('tracking_code'),
                            "tracking_url": order.get('tracking_url')
                        })
                    
                    orders_text = tiny_erp.format_orders_for_display(orders)
                    message_id = db.save_chat_message(request.message, orders_text)
                    
                    # Clear the awaiting flags but keep CPF/CNPJ stored for future queries
                    conversation_state[session_key]['awaiting_order_choice'] = False
                    conversation_state[session_key]['awaiting_search_param'] = False
                    
                    return {
                        "response": orders_text,
                        "products": [],
                        "orders": orders_cards,
                        "message_id": message_id,
                        "follow_ups": [
                            "Tell me more about a specific order",
                            "What are the shipping options?",
                            "How do I track my order?"
                        ],
                        "inline_buttons": []
                    }
            
            elif wants_search:
                # User wants to search by date or order ID
                conversation_state[session_key]['awaiting_search_param'] = True
                conversation_state[session_key]['awaiting_order_choice'] = False
                
                resp_text = "Sure! Please provide either:\n\n📅 **Order Date** (e.g., 03/03/2026 or 12/09/2024)\n🔢 **Order ID** (e.g., 755433675 or cart_01KJSAW1HZ3X2KJDKSMPXKBZYJ)\n\nI'll search for your order based on what you provide."
                message_id = db.save_chat_message(request.message, resp_text)
                
                return {
                    "response": resp_text,
                    "products": [],
                    "orders": [],
                    "message_id": message_id,
                    "follow_ups": [],
                    "inline_buttons": []
                }
            else:
                # User didn't make a clear choice, ask again
                order_buttons = ["1️⃣ Show my last 3 recent orders", "2️⃣ Search by order date or order ID"]
                resp_text = "I didn't quite understand. Would you like to:\n\nPlease let me know your preference!"
                message_id = db.save_chat_message(request.message, resp_text)
                
                return {
                    "response": resp_text,
                    "products": [],
                    "orders": [],
                    "message_id": message_id,
                    "follow_ups": [], # Clear to avoid duplication with inline buttons
                    "inline_buttons": order_buttons
                }
        
        # Check if we're waiting for search parameter (date or order ID)
        if session_key in conversation_state and conversation_state[session_key].get('awaiting_search_param'):
            cpf_cnpj = conversation_state[session_key]['cpf_cnpj']
            orders = tiny_erp.fetch_and_store_orders(cpf_cnpj)
            
            if orders:
                # Try to match by Order ID first
                order_id_match = re.search(r'(cart_[a-zA-Z0-9]+|\d{6,})', user_message)
                
                # Try to match by date
                date_match = re.search(r'\b(\d{2}[\/\-]\d{2}[\/\-]\d{4}|\d{2}[\/\-]\d{2}[\/\-]\d{2})\b', user_message)
                
                filtered_orders = []
                search_type = ""
                search_value = ""
                
                if order_id_match:
                    # Search by Order ID
                    search_order_id = order_id_match.group(0)
                    search_type = "Order ID"
                    search_value = search_order_id
                    
                    for order in orders:
                        if search_order_id.lower() in order.get('order_id', '').lower():
                            filtered_orders.append(order)
                
                elif date_match:
                    # Search by Date
                    search_date = date_match.group(0)
                    search_type = "Order Date"
                    search_value = search_date
                    
                    for order in orders:
                        if search_date in order.get('order_date', ''):
                            filtered_orders.append(order)
                
                if filtered_orders:
                    # Found matching orders
                    orders_cards = []
                    for order in filtered_orders[:3]:  # Limit to 3
                        orders_cards.append({
                            "order_id": order.get('order_id', 'N/A'),
                            "customer_name": order.get('customer_name', 'N/A'),
                            "total": order.get('total', 0),
                            "status": order.get('status', 'Unknown'),
                            "order_date": order.get('order_date', ''),
                            "tracking_code": order.get('tracking_code'),
                            "tracking_url": order.get('tracking_url')
                        })
                    
                    count = len(filtered_orders)
                    resp_text = f"✅ I found **{count} order(s)** matching {search_type}: **{search_value}**"
                    message_id = db.save_chat_message(request.message, resp_text)
                    
                    # Clear the awaiting flags but keep CPF/CNPJ stored for future queries
                    conversation_state[session_key]['awaiting_order_choice'] = False
                    conversation_state[session_key]['awaiting_search_param'] = False
                    
                    return {
                        "response": resp_text,
                        "products": [],
                        "orders": orders_cards,
                        "message_id": message_id,
                        "follow_ups": [
                            "Search for another order",
                            "Show my recent orders"
                        ],
                        "inline_buttons": []
                    }
                else:
                    # No matching orders found
                    resp_text = f"❌ I couldn't find any orders matching your search. Please verify and try again, or you can:\n\n📋 Type 'recent orders' to see your last 3 orders"
                    message_id = db.save_chat_message(request.message, resp_text)
                    
                    # Keep the state for another try
                    return {
                        "response": resp_text,
                        "products": [],
                        "orders": [],
                        "message_id": message_id,
                        "follow_ups": ["Show recent orders", "Try another search"],
                        "inline_buttons": []
                    }

        # Check if user is asking about their orders/history (comprehensive check)
        is_asking_orders = bool(re.search(r'(my order|meu pedido|my orders|meus pedidos|past order|pedidos anteriores|order history|histórico de pedidos|minhas compras|my purchase|track.*order|where.*order|order.*status|check.*order|find.*order|search.*order|view.*order|show.*order|previous order|recent order)', user_message.lower()))
        
        # Check if user provided CPF/CNPJ (11 or 14 digits)
        cpf_cnpj_match = re.search(r'\b(\d{11}|\d{14}|\d{3}\.?\d{3}\.?\d{3}-?\d{2}|\d{2}\.?\d{3}\.?\d{3}/?0001-?\d{2})\b', user_message)
        
        # Check if we already have CPF/CNPJ stored in the session
        stored_cpf_cnpj = None
        if session_key in conversation_state:
            stored_cpf_cnpj = conversation_state[session_key].get('cpf_cnpj')
            
        is_new_cpf = False
        # If CPF/CNPJ is provided, store it in session for future use
        if cpf_cnpj_match:
            cpf_cnpj = cpf_cnpj_match.group(0)
            print(f"[SERVER] Detected CPF/CNPJ: {cpf_cnpj} - Storing in session")
            
            if not stored_cpf_cnpj or stored_cpf_cnpj != cpf_cnpj:
                is_new_cpf = True
            
            # Store or update CPF/CNPJ in session
            if session_key not in conversation_state:
                conversation_state[session_key] = {}
            conversation_state[session_key]['cpf_cnpj'] = cpf_cnpj
        
        # If user is asking about orders
        if is_asking_orders:
            # Check if we have CPF/CNPJ (either just provided or already stored)
            current_cpf_cnpj = cpf_cnpj_match.group(0) if cpf_cnpj_match else stored_cpf_cnpj
            
            if not current_cpf_cnpj:
                # First time - ask for CPF/CNPJ
                resp_text = "To check your order information, I need your CPF or CNPJ number. Please provide your CPF (11 digits) or CNPJ (14 digits).\n\nFor example: '270.051.840-33' or '12.345.678/0001-90'"
                message_id = db.save_chat_message(request.message, resp_text)
                return {
                    "response": resp_text,
                    "products": [],
                    "orders": [],
                    "message_id": message_id,
                    "follow_ups": ["What products do you offer?", "Tell me about yoga mats", "How can I help you today?"],
                    "inline_buttons": []
                }
            else:
                # We have CPF/CNPJ - fetch orders and show options
                orders = tiny_erp.fetch_and_store_orders(current_cpf_cnpj)
                
                if orders:
                    # Store in session and set awaiting choice
                    if session_key not in conversation_state:
                        conversation_state[session_key] = {}
                    
                    conversation_state[session_key]['cpf_cnpj'] = current_cpf_cnpj
                    conversation_state[session_key]['awaiting_order_choice'] = True
                    conversation_state[session_key]['awaiting_search_param'] = False
                    
                    total_count = len(orders)
                    order_buttons = ["1️⃣ Show my last 3 recent orders", "2️⃣ Search by order date or order ID"]
                    resp_text = f"I found **{total_count} orders** for you! How would you like to view them?"
                    message_id = db.save_chat_message(request.message, resp_text)
                    
                    return {
                        "response": resp_text,
                        "products": [],
                        "orders": [],
                        "message_id": message_id,
                        "follow_ups": [], # Already in inline buttons
                        "inline_buttons": order_buttons
                    }
                else:
                    resp_text = f"I couldn't find any orders for CPF/CNPJ: {current_cpf_cnpj}. Please verify the number and try again."
                    message_id = db.save_chat_message(request.message, resp_text)
                    return {
                        "response": resp_text,
                        "products": [],
                        "orders": [],
                        "message_id": message_id,
                        "follow_ups": ["Try another CPF/CNPJ", "What products do you offer?", "Tell me about yoga mats"],
                        "inline_buttons": []
                    }
        

        
        # Handle case where user just provides CPF/CNPJ (in response to our request or spontaneously)
        # Only trigger options if we just stored new CPF/CNPJ and user isn't in middle of another flow
        if cpf_cnpj_match and not is_asking_orders:
            cpf_cnpj = cpf_cnpj_match.group(0)
            
            # Check if this is a NEW CPF/CNPJ (not already stored) or if we're expecting it
            # We already calculated is_new_cpf at the top
            
            if is_new_cpf:
                # User provided CPF/CNPJ - fetch orders and show options
                orders = tiny_erp.fetch_and_store_orders(cpf_cnpj)
                
                if orders:
                    # Store CPF/CNPJ and set state
                    if session_key not in conversation_state:
                        conversation_state[session_key] = {}
                    
                    conversation_state[session_key]['cpf_cnpj'] = cpf_cnpj
                    conversation_state[session_key]['awaiting_order_choice'] = True
                    conversation_state[session_key]['awaiting_search_param'] = False
                    
                    # Ask user what they want to do
                    total_count = len(orders)
                    order_buttons = ["1️⃣ Show my last 3 recent orders", "2️⃣ Search by order date or order ID"]
                    resp_text = f"Great! I found **{total_count} orders** for CPF/CNPJ: {cpf_cnpj}.\n\nHow would you like to view them?"
                    message_id = db.save_chat_message(request.message, resp_text)
                    
                    return {
                        "response": resp_text,
                        "products": [],
                        "orders": [],
                        "message_id": message_id,
                        "follow_ups": [], # Already in inline buttons
                        "inline_buttons": order_buttons
                    }
                else:
                    # No orders found or API error
                    resp_text = f"I couldn't find any orders for CPF/CNPJ: {cpf_cnpj}. Please verify the number and try again."
                    message_id = db.save_chat_message(request.message, resp_text)
                    return {
                        "response": resp_text,
                        "products": [],
                        "orders": [],
                        "message_id": message_id,
                        "follow_ups": ["Try another CPF/CNPJ", "What products do you offer?", "Tell me about yoga mats"],
                        "inline_buttons": []
                    }
        # --- End TinyERP Integration ---
        
        # Check if we're in an active TinyERP flow (waiting for user input)
        in_tinyerp_flow = (session_key in conversation_state and 
                          (conversation_state[session_key].get('awaiting_order_choice') or 
                           conversation_state[session_key].get('awaiting_search_param')))
        
        # Check if user has CPF/CNPJ stored (even if not actively in a flow)
        has_stored_cpf = session_key in conversation_state and conversation_state[session_key].get('cpf_cnpj')
        
        # DO NOT fetch order info from orders.json if user has CPF/CNPJ or is asking about orders
        system_context = ""
        
        if has_stored_cpf and not in_tinyerp_flow:
            cpf_cnpj = conversation_state[session_key].get('cpf_cnpj')
            orders = tiny_erp.fetch_and_store_orders(cpf_cnpj)
            if orders:
                system_context += tiny_erp.format_orders_for_llm_context(orders)
        elif user_id and not has_stored_cpf and not is_asking_orders and not in_tinyerp_flow:
            # Only add basic user context, no order data from orders.json
            system_context = f"System Note: The current user is {user_id}.\n\n"

        # --- Personalization Check for Clothing/Human Products ---
        is_clothing_query = bool(re.search(r'(dress|clothing|shirt|pants|legging|bra|top|shoe|wear|apparel|clothes|jacket|top|bottom)', user_message.lower()))
        is_providing_profile = bool(re.search(r'\b(male|female|man|woman|boy|girl|mens|womens)\b', user_message.lower()) or re.search(r'(size|\bxs\b|\bs\b|\bm\b|\bl\b|\bxl\b|\bxxl\b|\bxxxl\b|large|medium|small)', user_message.lower()))
        
        user_profile = None
        if user_id:
            user_profile = db.get_user_profile(user_id)
            
            if not user_profile:
                if is_clothing_query and not is_providing_profile:
                    resp_text = "To recommend the best yoga products for you, I need a bit of info first. Could you please tell me:\n\n- Your gender\n- Your usual clothing size for tops and/or bottoms For example: \"I am male, usually size L for tops and 42 for shoes.\""
                    message_id = db.save_chat_message(request.message, resp_text)
                    return {
                        "response": resp_text,
                        "products": [],
                        "orders": [],
                        "message_id": message_id,
                        "follow_ups": [],
                        "inline_buttons": []
                    }
                elif is_providing_profile:
                    # Try to extract gender explicitly for better context
                    gender = "Unknown"
                    msg_lower = user_message.lower()
                    if re.search(r'\b(male|man|boy|mens)\b', msg_lower):
                        gender = "Male"
                    elif re.search(r'\b(female|woman|girl|womens)\b', msg_lower):
                        gender = "Female"
                        
                    db.save_user_profile(user_id, gender, user_message)
                    user_profile = {"gender": gender, "size": user_message}
            
            if user_profile:
                system_context += f"System Note: The current user's profile with gender and size details is: Gender - {user_profile['gender']}, Details - '{user_profile['size']}'. CRITICAL: You MUST use this information to filter products. If the user is male, ONLY suggest men's products and DO NOT suggest sports bras, women's leggings, or female tops. If the user is female, suggest female clothing. Filter the catalog explicitly by this gender and size.\n\n"
        # ---------------------------------------------------------
            
        # Determine if the query is order or cart related
        is_order_related = bool(re.search(r'(order|pedido|cart|carrinho|history|histórico|status|track|rastrear)', user_message, re.IGNORECASE))
        
        if is_order_related:
            order_info = fetch_order_info(user_message, user_id)
            if order_info:
                system_context = order_info + "\n\n" + system_context

        # --- Color-specific variant filter context ---
        # If the user is asking about colors (e.g., green/blue mat), provide
        # the LLM with a clear mapping of allowed variants so it doesn't
        # describe or invent other colors for this response.
        requested_colors_for_llm = set()
        if not is_order_related:
            requested_colors_for_llm = _extract_colors_from_query(user_message)

        if requested_colors_for_llm:
            try:
                color_lines = []
                all_available_labels = []  # Collect ALL variant labels for fallback
                # Scan ALL products (no cap) to ensure we don't miss yoga mats or other items
                for title_lower, variants in product_variants.items():
                    matching = []
                    for v in variants:
                        v_colors = set(v.get("colors") or [])
                        if v_colors & requested_colors_for_llm:
                            matching.append(v)
                        # Collect available labels for this product (for alternative suggestions)
                        lbl = v.get("variant_label")
                        if lbl:
                            all_available_labels.append((title_lower, lbl))
                    if not matching:
                        continue

                    human_title = next((t for t in product_lookup.keys() if t.lower() == title_lower), title_lower)
                    labels = ", ".join(f"'{v.get('variant_label')}'" for v in matching)
                    color_lines.append(f"- {human_title}: allowed variants for this query -> {labels}")

                color_names = ", ".join(sorted(list(requested_colors_for_llm)))
                if color_lines:
                    color_note = (
                        f"System Note: The user explicitly requested the following color(s): {color_names}. "
                        "Based on the product catalog, the following variants match that color. "
                        "Recommend ONLY these variants for the color-sensitive part of your answer. "
                        "Do NOT say a color is unavailable unless the retrieved context also confirms it is not available.\n"
                        "IMPORTANT: The retrieved context from the knowledge base is the authoritative source — "
                        "if the context mentions additional colors or variants not listed here, trust the context as well.\n"
                        + "Matching color variants in catalog:\n"
                        + "\n".join(color_lines)
                        + "\n\n"
                    )
                    system_context = color_note + system_context
                else:
                    # No local variant matched the requested color — guide the LLM to check
                    # the retrieved context (Qdrant) before concluding unavailability
                    color_note = (
                        f"System Note: The user is asking about color(s): {color_names}. "
                        "The quick local catalog lookup did not find an exact color match for this query. "
                        "However, BEFORE saying the color is unavailable, you MUST carefully check the "
                        "retrieved product context below for any mention of this color or similar shades. "
                        "If the context shows the product IS available in that color (or a similar shade), "
                        "tell the user about it and show them what IS available. "
                        "Only say the color is unavailable if the retrieved context also does not mention it. "
                        "In that case, politely suggest the closest available colors from the context.\n\n"
                    )
                    system_context = color_note + system_context
                    print(f"[COLOR FILTER] No local variant found for colors: {color_names}. Sending guidance note to LLM.")
            except Exception as e:
                print(f"Color context build error: {e}")

        if product_context:
            system_context = product_context + "\n" + system_context

        # --- Final Context Assembly and Chat ---
        from llama_index.core import Settings
        if system_context:
            final_prompt = (
                f"### System Context & Data\n{system_context}\n\n"
                f"### Behavioral Requirements\n"
                f"1. **Clarifying Questions**: If the user's query is vague, you MUST ask 2-3 specific counter-questions to narrow down their needs before suggesting products.\n"
                f"2. **Follow-up Buttons**: You MUST always end your response with exactly 3 RELEVANT follow-up questions under the '### FOLLOW-UPS:' header. These MUST be directly related to the current product or topic being discussed (e.g., if talking about statues, do not ask about essential oils).\n"
                f"3. **Format**: Use the professional and Zen Yogateria tone.\n\n"
                f"### User Question\n{user_message}"
            )
            print(f"\n[LLM CALL] Final Synthesis using {Settings.llm.model} (Context provided)...")
            response = chat_engine.chat(final_prompt)
        else:
            final_prompt = (
                f"### Behavioral Requirements\n"
                f"1. **Clarifying Questions**: If the user's query is vague, you MUST ask 2-3 specific counter-questions to narrow down their needs before suggesting products.\n"
                f"2. **Follow-up Buttons**: You MUST always end your response with exactly 3 RELEVANT follow-up questions under the '### FOLLOW-UPS:' header. These MUST be directly related to the current topic.\n"
                f"3. **Format**: Use the professional and Zen Yogateria tone.\n\n"
                f"### User Question\n{user_message}"
            )
            print(f"\n[LLM CALL] Final Synthesis using {Settings.llm.model} (No Context)...")
            response = chat_engine.chat(final_prompt)
            
        resp_text = str(response)
        
        # Parse Follow-ups using the robust helper
        resp_text, follow_ups = clean_and_extract_follow_ups(resp_text)
        
        # Save to DB
        message_id = db.save_chat_message(request.message, resp_text)
        
        # Extract product cards using the lookup cache
        products = []
        
        # Check if the query is a basic greeting or non-product query
        is_basic_greeting = bool(re.search(r'^(hi|hello|hey|ola|olá|oi|bom dia|boa tarde|boa noite|thanks|thank you|obrigado|obrigada|tks|how are you|tudo bem|who are you|quem é você|help|ajuda).*$', user_message.strip(), re.IGNORECASE))
        
        if not is_order_related and not is_basic_greeting:
            seen_titles = set()

            # Detect color intent from user query (primary) and response text (fallback)
            requested_colors = _extract_colors_from_query(user_message)
            if not requested_colors:
                requested_colors = _extract_colors_from_query(resp_text)

            if requested_colors:
                print(f"[COLOR QUERY] Requested canonical colors: {sorted(list(requested_colors))}")

            # Helper: choose variant matching requested colors if available
            def pick_card_for_title(title: str):
                base_info = product_lookup.get(title)
                if not base_info:
                    return None

                # If no color requested, just return base card
                if not requested_colors:
                    print(f"[COLOR PICK] No color requested. Using base product card for '{title}'.")
                    return base_info

                variants_for_product = product_variants.get(title.lower()) or []
                # Prefer first variant whose canonical colors intersect the query colors
                for v in variants_for_product:
                    v_colors = set(v.get("colors") or [])
                    if v_colors & requested_colors:
                        merged = base_info.copy()
                        merged.update(
                            {
                                "image": v.get("image") or base_info.get("image"),
                                "url": v.get("url") or base_info.get("url"),
                                "variant_id": v.get("variant_id"),  # Pass variant_id to frontend
                                "variant_label": v.get("variant_label"),
                            }
                        )
                        print(
                            f"[COLOR PICK] Matched variant for '{title}' -> variant_label='{v.get('variant_label')}', "
                            f"variant_id='{v.get('variant_id')}', colors={sorted(list(v_colors))}, url={merged.get('url')}"
                        )
                        return merged

                # Fallback: no matching variant, use base card
                print(f"[COLOR PICK] No matching variant colors for '{title}'. Using base card.")
                return base_info

            # 1. NEW: Extraction from numbered lists in response (most reliable)
            # Pattern: 1️⃣ **Product Name**, 1. **Product Name**, etc.
            numbered_matches = re.finditer(r'(?:[1-3]️⃣|\d+\.|\*)\s*\*\*?([^*]+)\*\*?', resp_text)
            for m in numbered_matches:
                extracted_title = m.group(1).strip()
                # Find the best match in our lookup
                for title in product_lookup.keys():
                    if extracted_title.lower() == title.lower() or title.lower() in extracted_title.lower():
                        card = pick_card_for_title(title)
                        if card and title not in seen_titles:
                            products.append(card)
                            seen_titles.add(title)
                if len(products) >= 3:
                    break

            # 2. Fallback: Prioritize products whose names appear as keywords in the response
            # We look for long enough strings (ignore small words like "Yoga" or "Mat" by themselves)
            if len(products) < 3:
                for title in product_lookup.keys():
                    if title in seen_titles: continue
                    # Multi-word names are strong matches. Single words must be at least 6 chars
                    if ' ' in title or len(title) > 5:
                        if title.lower() in resp_text.lower():
                            card = pick_card_for_title(title)
                            if card:
                                products.append(card)
                                seen_titles.add(title)
                    if len(products) >= 3:
                        break

            # 2. Strict source node check (only if we still have room and the match is STRONG)
            if len(products) < 3 and hasattr(response, 'source_nodes'):
                for node in response.source_nodes:
                    metadata = node.node.metadata
                    title = metadata.get('title')

                    if title and title in product_lookup and title not in seen_titles:
                        # Very strict keyword matching for source nodes to avoid over-including
                        title_words = [w.lower() for w in title.replace('-', ' ').replace('/', ' ').split() if len(w) > 4]
                        resp_text_lower = resp_text.lower()
                        
                        # Must match most of the unique words in the title
                        matches = sum(1 for w in title_words if w in resp_text_lower)
                        
                        if len(title_words) > 0 and matches >= len(title_words) * 0.7:
                            card = pick_card_for_title(title)
                            if card:
                                products.append(card)
                                seen_titles.add(title)

                    if len(products) >= 3:
                        break

        # Decide where to show suggested questions:
        # - "Inline" (inside the bubble) is for the first time a user visits a product URL
        # - "Follow-up" (bottom pills) is for regular conversation turns
        
        final_inline_buttons = []
        # If it was a pure URL turn, we already returned early above.
        # This part handles regular turns where a product context is active.
        # We put suggested questions as navigation pills at the bottom to avoid cluttering the bubble.
        final_follow_ups_with_suggestions = []
        seen_fups = set()
        # Prioritize LLM generated follow-ups as they are contextually aware
        # but also include suggested questions if they exist
        for q in follow_ups + suggested_questions:
            q_clean = q.strip()
            if q_clean and q_clean not in seen_fups:
                final_follow_ups_with_suggestions.append(q_clean)
                seen_fups.add(q_clean)
        
        if len(final_follow_ups_with_suggestions) > 5:
            final_follow_ups_with_suggestions = final_follow_ups_with_suggestions[:5]

        return {
            "response": resp_text,
            "products": products,
            "orders": [],  # Empty for regular product queries
            "message_id": message_id,
            "follow_ups": final_follow_ups_with_suggestions,
            "inline_buttons": [] # Use pills (follow_ups) for regular turns
        }
    except Exception as e:
        print(f"Chat Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)
