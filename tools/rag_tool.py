import os
import uuid
from pymilvus import MilvusClient

DB_PATH = "./storage/milvus_db/milvus_lite.db"
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
client = MilvusClient(DB_PATH)
COLLECTION_NAME = "lens_knowledge"

def init_lens_collection():
    if client.has_collection(COLLECTION_NAME):
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        dimension=1024
    )
    # 示例插入一条镜头知识库
    sample_data = [
        {
            "id": uuid.uuid4().int % (2**63),
            "vector": [0.1]*1024,
            "text": "近景人物情绪镜头，柔和侧光，慢推镜头，短剧悲情风格"
        }
    ]
    client.insert(COLLECTION_NAME, sample_data)

def retrieve_lens_knowledge(query_vector: list, top_k=3) -> list:
    res = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_vector],
        limit=top_k
    )
    return [item["entity"]["text"] for item in res[0]]

init_lens_collection()
