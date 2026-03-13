"""
Test script to verify TinyERP API connection
"""
import requests
from config import TINY_ERP_URL, TINY_ERP_API_KEY

# Test CPF/CNPJ
test_cpf = "27005184033"

print("=" * 50)
print("TinyERP API Test")
print("=" * 50)
print(f"API URL: {TINY_ERP_URL}")
print(f"API Key configured: {'Yes' if TINY_ERP_API_KEY else 'No'}")
print(f"Testing with CPF/CNPJ: {test_cpf}")
print("=" * 50)

if not TINY_ERP_URL:
    print("❌ ERROR: TINY_ERP_URL not configured in .env file")
    exit(1)

url = f"{TINY_ERP_URL}?cpf_cnpj={test_cpf}"
headers = {}
if TINY_ERP_API_KEY:
    headers['x-publishable-api-key'] = TINY_ERP_API_KEY

print("\nMaking API request...")
try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")
    print(f"\nResponse Body:")
    print(response.text)
    
    if response.status_code == 200:
        print("\n✅ API connection successful!")
        data = response.json()
        pedidos = data.get('retorno', {}).get('pedidos', [])
        print(f"Orders found: {len(pedidos)}")
    else:
        print(f"\n❌ API returned error status: {response.status_code}")
        
except Exception as e:
    print(f"❌ Request failed: {e}")
