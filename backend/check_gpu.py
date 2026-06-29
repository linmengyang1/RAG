"""检查 GPU 与依赖是否就绪（临时验证脚本）"""
import sys

print("=" * 60)
print("Python:", sys.version.split()[0])
print("=" * 60)

# 1. torch + CUDA
try:
    import torch
    print(f"[OK] torch {torch.__version__}")
    print(f"     CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"     GPU: {torch.cuda.get_device_name(0)}")
        print(f"     显存: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
except Exception as e:
    print(f"[FAIL] torch: {e}")
    sys.exit(1)

# 2. FlagEmbedding (BGE-M3)
try:
    from FlagEmbedding import BGEM3FlagModel
    print("[OK] FlagEmbedding (BGEM3FlagModel 可用)")
except Exception as e:
    print(f"[FAIL] FlagEmbedding: {e}")
    sys.exit(1)

# 3. sentence-transformers
try:
    from sentence_transformers import SentenceTransformer
    print("[OK] sentence-transformers")
except Exception as e:
    print(f"[FAIL] sentence-transformers: {e}")
    sys.exit(1)

# 4. Milvus 连接
try:
    from pymilvus import MilvusClient
    client = MilvusClient(uri="http://milvus:19530")
    cols = client.list_collections()
    print(f"[OK] Milvus 连接成功，集合: {cols}")
except Exception as e:
    print(f"[FAIL] Milvus: {e}")

# 5. PostgreSQL 连接
try:
    import asyncio
    from app.db.session import async_session_factory
    from sqlalchemy import text

    async def check_pg():
        async with async_session_factory() as s:
            r = await s.execute(text("SELECT 1"))
            return r.scalar()

    asyncio.run(check_pg())
    print("[OK] PostgreSQL 连接成功")
except Exception as e:
    print(f"[FAIL] PostgreSQL: {e}")

print("=" * 60)
print("检查完成")
