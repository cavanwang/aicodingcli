import numpy as np
from numpy.testing import assert_allclose
from agent.semantic import CodeEmbedder, get_embedder


class TestCodeEmbedder:
    def test_model_initialization(self):
        """测试模型是否成功初始化（异步）"""
        embedder = get_embedder()
        # 等待模型加载（实际应加超时，此处简化）
        import time
        time.sleep(2)
        assert embedder.model is not None, "模型应成功加载"
        assert embedder.tokenizer is not None, "分词器应成功加载"

    def test_embed_basic(self):
        """测试基础代码向量生成"""
        embedder = get_embedder()
        code = "def hello(): print('Hello')"
        vec = embedder.embed(code)
        
        assert vec is not None, "应生成有效向量"
        assert vec.shape == (1, 768), f"向量维度应为(1,768)，实际{vec.shape}"

    def test_truncation(self):
        """测试长代码截断处理"""
        embedder = get_embedder()
        long_code = "def x():\n" + "    a = 1\n" * 1000  # 超过512 token
        vec_long = embedder.embed(long_code)
        
        short_code = long_code[:500]
        vec_short = embedder.embed(short_code)
        
        # 验证截断后关键语义保留（余弦相似度>0.9）
        similarity = np.dot(vec_long[0], vec_short[0]) / (
            np.linalg.norm(vec_long[0]) * np.linalg.norm(vec_short[0])
        )
        assert similarity > 0.9, f"截断应保留语义，实际相似度{similarity:.2f}"

    def test_similarity_calculation(self):
        """测试语义相似代码的向量一致性"""
        embedder = get_embedder()
        
        # 两个语义相同的分页实现
        code1 = "def paginate(items, size): return items[page*size:(page+1)*size]"
        code2 = "def get_page(data, page_size): return data[page*page_size:(page+1)*page_size]"
        
        vec1 = embedder.embed(code1)
        vec2 = embedder.embed(code2)
        
        similarity = np.dot(vec1[0], vec2[0]) / (
            np.linalg.norm(vec1[0]) * np.linalg.norm(vec2[0])
        )
        assert similarity > 0.85, f"相似代码应高相似度，实际{similarity:.2f}"

    def test_model_failure_fallback(self):
        """测试模型加载失败时的降级处理"""
        # 模拟模型加载失败
        embedder = CodeEmbedder()
        embedder.model = None
        
        result = embedder.embed("test code")
        assert result is None, "模型未加载时应返回None"