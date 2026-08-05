from __future__ import annotations

import numpy as np
import threading
from pathlib import Path
from transformers import AutoTokenizer, AutoModel


class CodeEmbedder:
    """轻量级代码嵌入引擎，支持512 token截断的语义向量化"""

    def __init__(self):
        self.tokenizer = None
        self.model = None
        # 启动后台预加载线程
        threading.Thread(target=self._load_model, daemon=True).start()

    def _load_model(self):
        """异步加载模型，避免阻塞主流程"""
        try:
            cache_dir = Path(".cache/models")
            cache_dir.mkdir(parents=True, exist_ok=True)
            
            self.tokenizer = AutoTokenizer.from_pretrained(
                "huggingface/CodeBERTa-small-v1",
                cache_dir=str(cache_dir)
            )
            self.model = AutoModel.from_pretrained(
                "huggingface/CodeBERTa-small-v1",
                cache_dir=str(cache_dir)
            )
        except Exception as e:
            # 降级处理：记录错误但不中断主流程
            import logging
            logging.warning(f"Model load failed: {str(e)}")

    def embed(self, code: str) -> np.ndarray | None:
        """生成代码的语义向量，自动处理截断和异常
        
        Args:
            code: Python代码字符串
        
        Returns:
            768维向量或None（模型未加载时）
        """
        if self.model is None:
            return None
        
        try:
            inputs = self.tokenizer(
                code,
                return_tensors="pt",
                truncation=True,
                max_length=512
            )
            outputs = self.model(**inputs)
            # 取最后一层隐藏状态的平均值
            return outputs.last_hidden_state.mean(dim=1).detach().numpy()
        except Exception as e:
            import logging
            logging.error(f"Embedding failed: {str(e)}")
            return None


# 全局单例（避免重复加载）
_embedder = None

def get_embedder() -> CodeEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = CodeEmbedder()
    return _embedder