# test_my_tools.py — run this to confirm both tools work standalone

from tools.tool_8_delivery import get_delivery_performance
from tools.tool_9_knowledge import knowledge_search

print("=== Testing get_delivery_performance ===")
print(get_delivery_performance("SUP-019", "last_30_days"))
# Should show degradation_flag: True

print(get_delivery_performance("SUP-022", "last_30_days"))
# Should show degradation_flag: False

print(get_delivery_performance("SUP-999"))
# Should return SUPPLIER_NOT_FOUND error object

print("\n=== Testing knowledge_search ===")
print(knowledge_search("supplier delivery delay causing stockout"))
# Should return 2 relevant documents with similarity scores

print(knowledge_search("return rate size chart update"))
# Should return SOP and past case about size charts

print(knowledge_search(""))
# Should return EMPTY_QUERY error