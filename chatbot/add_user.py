import json
import os

filepath = "carts.json"
if os.path.exists(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
else:
    data = {"users": []}

new_user = {
    "user_id": "cus_01JZCGH00YJ1YZ9RSCX4834YRB",
    "name": "Cliente VIP",
    "email": "vipc@email.com",
    "phone": "+55 11 99999-9999",
    "address": "Rua Yoga, 108 - São Paulo, SP",
    "cart": {
        "items": [
            {
                "product_id": "P_ESTOJO",
                "product_name": "Estojo para limpador de lingua",
                "variant": "Único",
                "quantity": 1,
                "unit_price": 49,
                "subtotal": 49
            },
            {
                "product_id": "P_LEGGING",
                "product_name": "Calça Legging Deva",
                "variant": "Único",
                "quantity": 1,
                "unit_price": 197,
                "subtotal": 197
            },
            {
                "product_id": "P_LIMPADOR",
                "product_name": "Limpador de Língua 100% cobre puro",
                "variant": "Único",
                "quantity": 1,
                "unit_price": 69,
                "subtotal": 69
            }
        ],
        "total_items": 3,
        "cart_total": 315,
        "free_shipping": True
    }
}

if not any(u.get("user_id") == new_user["user_id"] for u in data.get("users", [])):
    data["users"].append(new_user)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    print("User added successfully!")
else:
    print("User already exists!")
