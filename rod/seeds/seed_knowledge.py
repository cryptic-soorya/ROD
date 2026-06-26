import os
import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = os.getenv("CHROMA_PATH", "./knowledge_base/chroma_db")

embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name="all-MiniLM-L6-v2"
)

client = chromadb.PersistentClient(path=CHROMA_PATH)
collection = client.get_or_create_collection(
    name="retail_kb",
    embedding_function=embedding_fn
)

documents = [
    {
        "id": "DOC-0001",
        "text": "When return rate for a SKU exceeds 30% in a 14-day window, the first investigation step must be to check for supplier attribute changes within the preceding 60 days (SOP-RC-07).",
        "category": "SOP",
        "tags": "returns,supplier,size_chart"
    },
    {
        "id": "DOC-0047",
        "text": "SKU-3109 Return Spike Q3 2025: Root cause traced to 21-day lag between supplier updating size_chart and listing refresh. Resolution: automated daily sync job introduced.",
        "category": "Past Case",
        "tags": "returns,supplier,size_chart,listing"
    },
    {
        "id": "DOC-0012",
        "text": "Listing Accuracy SOP v2.3: Supplier attribute changes must be reflected in product listing within 48 hours of supplier notification.",
        "category": "SOP",
        "tags": "listing,supplier,accuracy"
    },
    {
        "id": "DOC-0033",
        "text": "When a supplier's avg delivery days exceed 150% of their baseline, immediately cross-check with inventory levels for all SKUs from that supplier. Stockouts during promotions are a common downstream effect.",
        "category": "SOP",
        "tags": "supplier,delivery,inventory,stockout"
    },
    {
        "id": "DOC-0051",
        "text": "Promotion underperformance case Q1 2026: PROMO-2026-01 for SKU-7782 showed only 8% uplift vs 25% projected. Investigation found inventory stockout on day 3 of the promotion window. Root cause: replenishment order delayed by SUP-031.",
        "category": "Past Case",
        "tags": "promotion,inventory,supplier,stockout"
    },
    {
        "id": "DOC-0019",
        "text": "Supplier defect rate above 5% requires immediate escalation to procurement team. All incoming shipments from that supplier should be held for quality inspection before shelving.",
        "category": "SOP",
        "tags": "supplier,defect,quality,escalation"
    },
]

collection.upsert(
    ids=[d["id"] for d in documents],
    documents=[d["text"] for d in documents],
    metadatas=[{"category": d["category"], "tags": d["tags"]} for d in documents]
)

print(f"Seeded {len(documents)} documents into retail_kb.")
print(f"ChromaDB saved to {CHROMA_PATH}")
