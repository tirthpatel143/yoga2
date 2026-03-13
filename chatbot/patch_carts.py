import json

with open("carts.json", "r") as f:
    data = json.load(f)

new_user = {
    "user_id": "cus_01JZCGH00YJ1YZ9RSCX4834YRB",
    "name": "Cliente VIP",
    "email": "cliente@email.com",
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
        "free_shipping": true
    }
}

# Check if already exists
if not any(u.get("user_id") == "cus_01JZCGH00YJ1YZ9RSCX4834YRB" for u in data["users"]):
    data["users"].append(new_user)
    with open("carts.json", "w") as f:
        json.dump(data, f, indent=4)
    print("User added successfully!")
else:
    print("User already exists!")
