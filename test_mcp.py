"""Quick test for MCP server data layer."""
import sys
sys.path.insert(0, '.')

try:
    from mcp_server.models import OrderStatus, LogisticsStatus, RefundEligibility
    print("models import: OK")
except Exception as e:
    print(f"models import FAILED: {e}")
    sys.exit(1)

try:
    from mcp_server.data_store import load_orders, load_logistics, load_refund_rules
    print("data_store import: OK")
except Exception as e:
    print(f"data_store import FAILED: {e}")
    sys.exit(1)

try:
    orders = load_orders()
    print(f"Loaded {len(orders)} orders")
except Exception as e:
    print(f"load_orders FAILED: {e}")
    sys.exit(1)

try:
    logistics = load_logistics()
    print(f"Loaded {len(logistics)} logistics records")
except Exception as e:
    print(f"load_logistics FAILED: {e}")
    sys.exit(1)

try:
    rules = load_refund_rules()
    print(f"Loaded {len(rules)} refund rules")
except Exception as e:
    print(f"load_refund_rules FAILED: {e}")
    sys.exit(1)

print("All tests passed!")
