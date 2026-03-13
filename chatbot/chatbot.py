import qdrant_client
from llama_index.core import VectorStoreIndex, Settings, PromptTemplate
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.vector_stores.qdrant import QdrantVectorStore

from config import (
    QDRANT_URL, COLLECTION_NAME, HF_TOKEN, 
    LLM_MODEL, EMBED_MODEL, TOP_K, SYSTEM_PROMPT, PRODUCT_DATA_PATH
)

def generate_catalog_summary():
    import json
    import os
    import requests
    from collections import Counter
    from config import PRODUCT_DATA_PATH, PRODUCT_API_URL, X_PUBLISHABLE_KEY
    
    try:
        if PRODUCT_API_URL:
            headers = {}
            if X_PUBLISHABLE_KEY:
                headers['x-publishable-api-key'] = X_PUBLISHABLE_KEY
            print(f"Fetching catalog summary from API: {PRODUCT_API_URL}")
            response = requests.get(PRODUCT_API_URL, headers=headers)
            response.raise_for_status()
            data = response.json()
        else:
            if not PRODUCT_DATA_PATH or not os.path.exists(PRODUCT_DATA_PATH):
                print(f"Warning: PRODUCT_DATA_PATH is not set or file does not exist.")
                return ""
            with open(PRODUCT_DATA_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
        
        products = data.get("products", [])
        price_data = []
        titles = []
        category_prices = {}
        
        for p in products:
            title = p.get("title", "")
            if not title: continue
            
            titles.append(title)
            
            variants = p.get("variants", [])
            for v in variants:
                calc_price = v.get("calculated_price", {})
                if calc_price:
                    amount = calc_price.get("calculated_amount")
                    if amount is not None and amount > 0:
                        price_data.append((amount, title))
                        
                        # Category heuristic
                        first_word = title.split()[0].title()
                        if first_word not in category_prices:
                            category_prices[first_word] = []
                        category_prices[first_word].append((amount, title))
                        break 
        
        if not price_data:
            return ""
            
        first_words = [t.split()[0].title() for t in titles if t]
        common_categories = [word for word, count in Counter(first_words).most_common(20) if len(word) > 2]
        
        price_data.sort()
        seen = set()
        unique = []
        for p, t in price_data:
            if t not in seen:
                unique.append((p, t))
                seen.add(t)
        
        cheapest = unique[:5]
        expensive = sorted(unique, key=lambda x: x[0], reverse=True)[:5]
        
        summary = "\n### GLOBAL & CATEGORY PRICING CATALOG OVERVIEW:\n"
        summary +=f"- **Categories Available**: {', '.join(common_categories)}\n\n"
        
        summary += "#### CATEGORY-WISE MIN/MAX PRICES:\n"
        summary += "USE THIS SECTION EXPLICITLY when answering questions like 'cheapest yoga mat', 'most expensive perfume', etc.\n"
        for cat in common_categories:
            cat_items_raw = category_prices.get(cat, [])
            if not cat_items_raw: continue
            cat_items_raw.sort()
            cat_seen = set()
            cat_unique = []
            for p, t in cat_items_raw:
                if t not in cat_seen:
                    cat_unique.append((p, t))
                    cat_seen.add(t)
            
            if cat_unique:
                c_cheapest = cat_unique[0]
                c_expensive = cat_unique[-1]
                summary += f" - **{cat}** (e.g. {cat.lower()}s, tapetes=mats, camisetas=t-shirts) -> Cheapest: {c_cheapest[1]} (BRL {c_cheapest[0]:.2f}) | Most Expensive: {c_expensive[1]} (BRL {c_expensive[0]:.2f})\n"
                
        summary += "\n#### OVERALL (ALL PRODUCTS):\n"
        summary += "- **Global Lowest**: " + ", ".join([f"{t} (BRL {p})" for p, t in cheapest]) + "\n"
        summary += "- **Global Highest**: " + ", ".join([f"{t} (BRL {p})" for p, t in expensive]) + "\n"
        summary += "\nNOTE: If the user asks for a specific category (e.g., 'cheapest yoga mat', 'cheapest tapete', 'most expensive perfume'), **ALWAYS use the 'CATEGORY-WISE MIN/MAX PRICES' information above.** This summary is the direct truth for category price extremes. Only rely on the retrieved context for product details or if the category isn't properly listed here.\n"
        return summary
    except Exception as e:
        print(f"Error generating summary: {e}")
        return ""

def setup_chatbot():
    if not HF_TOKEN:
        print("ERROR: HF_TOKEN is not set.")
        return None

    # Configure models
    from llama_index.llms.openai_like import OpenAILike
    from config import OPENROUTER_API_KEY
    
    Settings.llm = OpenAILike(
        model=LLM_MODEL, 
        api_key=OPENROUTER_API_KEY,
        api_base="https://openrouter.ai/api/v1",
        is_chat_model=True,
        context_window=100000, # Added context window to stop LlamaIndex looping 'refine' requests
        max_tokens=4096
    )
    Settings.context_window = 100000
    
    from llama_index.embeddings.huggingface import HuggingFaceEmbedding
    Settings.embed_model = HuggingFaceEmbedding(
        model_name=EMBED_MODEL
    )
    
    # Initialize Qdrant Client
    print(f"Connecting to Qdrant at {QDRANT_URL}...")
    client = qdrant_client.QdrantClient(url=QDRANT_URL)
    
    # Create Vector Store and get index
    vector_store = QdrantVectorStore(client=client, collection_name=COLLECTION_NAME)
    
    # Check if collection exists
    try:
        collections = client.get_collections().collections
        collection_names = [c.name for c in collections]
        
        if COLLECTION_NAME not in collection_names:
            print(f"WARNING: Collection '{COLLECTION_NAME}' not found.")
            # Fallback to base collection ONLY if it was created with LlamaIndex
            # Since we know 'yogateria_products' might be a raw collection, we should be careful
            if "yogateria_products" in collection_names:
                print("Checking 'yogateria_products' collection compatibility...")
                # Try to see if it has 'text' in payload schema - simplified check: just try to load
                vector_store = QdrantVectorStore(client=client, collection_name="yogateria_products")
            else:
                print("ERROR: No compatible collection found. Please run: python ingest.py")
                return None
    except Exception as e:
        print(f"Error connecting to Qdrant: {e}")
        return None

    try:
        index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        
        # Setup Chat Engine with Dynamic Price Summary and Memory Buffer
        catalog_summary = generate_catalog_summary()
        # We need a cleaner system prompt for the chat engine
        # Chat engine handles context and query strings differently
        clean_system_prompt = SYSTEM_PROMPT.split("### CONTEXT:")[0].strip()
        enhanced_system_prompt = f"{clean_system_prompt}\n\n{catalog_summary}"
        
        # Initialize memory buffer to keep history efficient (Pro Level)
        memory = ChatMemoryBuffer.from_defaults(token_limit=1500)
        
        chat_engine = index.as_chat_engine(
            chat_mode="condense_plus_context",
            memory=memory,
            similarity_top_k=TOP_K,
            system_prompt=enhanced_system_prompt
        )
        
        # Override the Condensation step with Groq if key is present
        from config import GROQ_API_KEY
        if GROQ_API_KEY:
            try:
                from llama_index.llms.groq import Groq as GroqLLM
                print("Setting up Groq for Context Condensation (llama-3.1-8b-instant)...")
                groq_condenser = GroqLLM(api_key=GROQ_API_KEY, model="llama-3.1-8b-instant")
                
                import types
                def custom_condense(self, chat_history, latest_message):
                    if self._skip_condense or len(chat_history) == 0:
                        return latest_message
                        
                    chat_history_str = "\n".join([f"{msg.role.value if hasattr(msg.role, 'value') else msg.role}: {msg.content}" for msg in chat_history])
                    
                    llm_input = self._condense_prompt_template.format(
                        chat_history=chat_history_str, question=latest_message
                    )
                    return str(groq_condenser.complete(llm_input))
                    
                chat_engine._condense_question = types.MethodType(custom_condense, chat_engine)
            except Exception as e:
                print(f"Warning: Could not setup Groq Condenser - {e}")
                
        return chat_engine
    except Exception as e:
        print(f"ERROR initializing index: {e}")
        print("Tip: This often happens if the collection schema is incompatible. Try running 'python ingest.py' for a fresh index.")
        return None

def extract_order_info(query: str) -> str:
    import re
    import requests
    from config import ORDER_API_URL, X_PUBLISHABLE_KEY
    if not ORDER_API_URL:
        return ""
        
    match = re.search(r'(?:order|pedido)\s*#?\s*([a-zA-Z0-9_-]+)', query, re.IGNORECASE)
    if not match:
        return ""
        
    order_id = match.group(1)
    headers = {}
    if X_PUBLISHABLE_KEY:
        headers['x-publishable-api-key'] = X_PUBLISHABLE_KEY
        
    try:
        url = f"{ORDER_API_URL}/{order_id}"
        resp = requests.get(url, headers=headers)
        
        if resp.status_code == 404:
            url2 = f"{ORDER_API_URL}?display_id={order_id}"
            resp2 = requests.get(url2, headers=headers)
            if resp2.status_code == 200:
                orders = resp2.json().get('orders', [])
                if orders:
                    data = orders[0]
                else:
                    return ""
            else:
                return ""
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
        return f"System Note: The user is asking about order #{order_id}. API Data: Status={status}, Fulfillment={fulfillment}. Items: {items_str}."
    except Exception as e:
        print(f"Error fetching order API: {e}")
        return ""

def fetch_all_orders_for_user(user_id: str) -> str:
    if not user_id:
        return ""
    
    import os, json
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

    import requests
    from config import ORDER_API_URL, X_PUBLISHABLE_KEY
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
            for data in orders[:5]: 
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

def chat():
    chat_engine = setup_chatbot()
    if not chat_engine:
        return

    print("\n" + "="*50)
    print("Welcome to Yogateria Support Chatbot!")
    print("I can help you with product information, features, and pricing.")
    print("Type 'exit' to quit.")
    print("="*50 + "\n")
    
    current_user_id = input("Chatbot: Please give me your ID? \nYou: ").strip()
    user_context = ""
    if current_user_id:
        user_orders_info = fetch_all_orders_for_user(current_user_id)
        if user_orders_info:
            user_context = f"{user_orders_info}\n\n"
            print(f"Chatbot: Thank you. I've found your account. How can I help you with your order or any of our products today?\n" + "-" * 30 + "\n")
        else:
            user_context = f"System Note: The current user is {current_user_id}.\n\n"
            print(f"Chatbot: Thank you. How can I help you today?\n" + "-" * 30 + "\n")
    else:
        print(f"Chatbot: Continuing as guest. How can I help you today?\n" + "-" * 30 + "\n")
    
    while True:
        try:
            user_input = input("You: ")
            if user_input.lower() in ['exit', 'quit', 'bye']:
                print("Chatbot: Namaste! Have a wonderful day!")
                break
            
            if not user_input.strip():
                continue
                
            print("Chatbot thinking...")
            
            # Dynamically extract Customer ID or Email from user prompt
            import re
            cus_match = re.search(r'(cus_[a-zA-Z0-9]+)', user_input)
            email_match = re.search(r'([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)', user_input)
            
            new_user_id = None
            if cus_match:
                new_user_id = cus_match.group(1)
            elif email_match:
                new_user_id = email_match.group(1)
                
            if new_user_id and new_user_id.lower() != str(current_user_id).lower():
                current_user_id = new_user_id
                user_orders_info = fetch_all_orders_for_user(current_user_id)
                if user_orders_info:
                    user_context = f"{user_orders_info}\n\n"
                else:
                    user_context = f"System Note: The current user is {current_user_id}. They have no active orders or carts found.\n\n"
            
            # Use order fetching if applicable
            order_info = extract_order_info(user_input)
            
            system_msg = user_context
            if order_info:
                system_msg += f"{order_info}\n\n"
                
            # Determine if the query is order or cart related
            is_order_related = bool(re.search(r'(order|pedido|cart|carrinho|history|histórico|status|track|rastrear)', user_input, re.IGNORECASE))
            
            if system_msg and is_order_related:
                final_prompt = f"User Account Data:\n{system_msg}\nPlease use the above user and order information to answer the user's query.\n\nUser Query: {user_input}"
                response = chat_engine.chat(final_prompt)
            else:
                response = chat_engine.chat(user_input)
            
            # Additional check for response validity
            if hasattr(response, 'response') and response.response:
                print(f"\nChatbot: {response.response}")
            elif str(response):
                print(f"\nChatbot: {response}")
            else:
                print("\nChatbot: I'm sorry, I couldn't find a definitive answer. Could you please rephrase?")
                
            print("-" * 30 + "\n")
            
        except KeyboardInterrupt:
            print("\nExiting...")
            break
        except Exception as e:
            if "TextNode" in str(e):
                print("\nData Error: The retrieval returned an invalid result. This usually means the Qdrant collection is corrupted or incompatible.")
                print("Please try running 'python ingest.py' to rebuild the index.")
            else:
                print(f"\nAn error occurred: {e}")

if __name__ == "__main__":
    chat()
