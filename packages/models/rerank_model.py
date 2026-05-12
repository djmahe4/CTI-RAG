import os
import json
import requests
import numpy as np

from .. import config
from ..utils.logging_config import logger


class LocalReranker:
    def __init__(self, config, **kwargs):
        model_info = config.reranker_names[config.reranker]
        model_name_or_path = config.model_local_paths.get(model_info["name"], model_info.get("local_path"))
        model_name_or_path = model_name_or_path or model_info["name"]
        logger.info(f"Loading Reranker model {config.reranker} from {model_name_or_path}")

        from FlagEmbedding import FlagReranker

        self._model = FlagReranker(model_name_or_path, use_fp16=True, device=config.device, **kwargs)
        logger.info(f"Reranker model {config.reranker} loaded")

    def compute_score(self, sentence_pairs, batch_size=256, max_length=512, normalize=False):
        """
        Adapts the input format for FlagReranker and computes scores.
        This method handles two formats:
        1. [query, [doc1, doc2, ...]] (from our retriever)
        2. [[query, doc1], [query, doc2], ...] (native FlagReranker format)
        """
        # Case 1: Input from our retriever: [query, [documents]]
        if (isinstance(sentence_pairs, list) and len(sentence_pairs) == 2 and
                isinstance(sentence_pairs[0], str) and isinstance(sentence_pairs[1], list)):
            
            query, documents = sentence_pairs
            
            # Adapt to FlagReranker's expected format: [[query, doc1], [query, doc2], ...]
            logger.debug(f"LocalReranker: Adapting [query, [documents]] input to list of pairs.")
            pairs = [[query, doc] for doc in documents]
            
            return self._model.compute_score(pairs, batch_size=batch_size, max_length=max_length, normalize=normalize)
        
        # Case 2: Assume native FlagReranker format or something it can handle
        else:
            logger.warning(f"LocalReranker: Received input not in [query, [documents]] format. Passing to parent compute_score directly. Input type: {type(sentence_pairs)}")
            return self._model.compute_score(sentence_pairs, batch_size=batch_size, max_length=max_length, normalize=normalize)


def sigmoid(x):
    return 1 / (1 + np.exp(-x))

class ZhipuReranker():
    """智谱AI Reranker - 使用智谱AI的文本重排序API"""
    def __init__(self, config, **kwargs):
        self.url = "https://open.bigmodel.cn/api/paas/v4/rerank"
        self.model = "rerank"
        
        api_key = os.getenv("ZHIPUAI_API_KEY")
        assert api_key, "ZHIPUAI_API_KEY is required for ZhipuReranker"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        logger.info(f"ZhipuReranker 初始化成功，模型: {self.model}")

    def compute_score(self, sentence_pairs, batch_size=256, max_length=4096, normalize=False):
        """
        计算文档与查询的相关性分数，兼容两种输入格式。
        1. [query, [doc1, doc2, ...]]
        2. [[query, doc1], [query, doc2], ...]
        """
        # 格式适配
        if (isinstance(sentence_pairs, list) and len(sentence_pairs) > 0 and
                isinstance(sentence_pairs[0], list) and len(sentence_pairs[0]) == 2):
            logger.debug(f"ZhipuReranker: 正在适配 list of pairs 输入格式。")
            query = sentence_pairs[0][0]
            documents = [pair[1] for pair in sentence_pairs]
        elif (isinstance(sentence_pairs, list) and len(sentence_pairs) == 2 and
                isinstance(sentence_pairs[0], str) and isinstance(sentence_pairs[1], list)):
            logger.debug(f"ZhipuReranker: 使用 [query, [documents]] 输入格式。")
            query, documents = sentence_pairs
        else:
            raise ValueError(f"ZhipuReranker 接收到无效的输入格式: {type(sentence_pairs)}")

        # 截断过长的文档
        truncated_docs = [doc[:max_length] if len(doc) > max_length else doc for doc in documents]
        
        # 构建请求payload
        payload = {
            "model": self.model,
            "query": query[:max_length],  # 查询也限制在4096字符
            "documents": truncated_docs,
            "return_documents": False,  # 不返回原始文本，节省带宽
        }
        
        try:
            logger.debug(f"调用智谱AI Rerank API: query='{query[:50]}...', 文档数={len(documents)}")
            response = requests.post(self.url, json=payload, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            response_data = response.json()
            logger.debug(f"智谱AI Rerank API 响应: {response_data}")
            
            results = response_data.get("results", [])
            
            if not results:
                logger.warning(f"智谱AI Rerank API 返回空结果")
                return [0.5] * len(documents)  # 返回默认分数
            
            # 按原始索引顺序重建分数列表
            scores = [0.0] * len(documents)
            for result in results:
                index = result.get("index", 0)
                score = result.get("relevance_score", 0.0)
                if 0 <= index < len(documents):
                    scores[index] = score
            
            # 归一化（如果需要）
            if normalize:
                scores = [sigmoid(score) for score in scores]
            
            logger.info(f"智谱AI Rerank 成功: 处理 {len(documents)} 个文档, 平均分数={sum(scores)/len(scores):.4f}")
            return scores
            
        except requests.exceptions.RequestException as e:
            error_msg = f"智谱AI Rerank API 请求失败: {e}"
            if e.response is not None:
                error_msg += f", 响应: {e.response.text}"
            logger.error(error_msg)
            raise RuntimeError(f"智谱AI Rerank API 调用失败: {e}") from e
        except Exception as e:
            logger.error(f"智谱AI Rerank 处理错误: {e}")
            raise RuntimeError(f"智谱AI Rerank 处理失败: {e}") from e

class SiliconFlowReranker():
    def __init__(self, config, **kwargs):
        self.url = "https://api.siliconflow.cn/v1/rerank"
        self.model = config.reranker_names[config.reranker]["name"]

        api_key = os.getenv("SILICONFLOW_API_KEY")
        assert api_key, "SILICONFLOW_API_KEY is required"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def compute_score(self, sentence_pairs, batch_size = 256, max_length = 512, normalize = False):
        """
        计算文档与查询的相关性分数，兼容两种输入格式。
        1. [query, [doc1, doc2, ...]]
        2. [[query, doc1], [query, doc2], ...]
        """
        # 格式适配
        if (isinstance(sentence_pairs, list) and len(sentence_pairs) > 0 and
                isinstance(sentence_pairs[0], list) and len(sentence_pairs[0]) == 2):
            logger.debug(f"SiliconFlowReranker: 正在适配 list of pairs 输入格式。")
            query = sentence_pairs[0][0]
            documents = [pair[1] for pair in sentence_pairs]
        elif (isinstance(sentence_pairs, list) and len(sentence_pairs) == 2 and
                isinstance(sentence_pairs[0], str) and isinstance(sentence_pairs[1], list)):
            logger.debug(f"SiliconFlowReranker: 使用 [query, [documents]] 输入格式。")
            query, documents = sentence_pairs
        else:
            raise ValueError(f"SiliconFlowReranker 接收到无效的输入格式: {type(sentence_pairs)}")

        payload = self.build_payload(query, documents, max_length)
        response = requests.request("POST", self.url, json=payload, headers=self.headers)
        response.raise_for_status()
        response = json.loads(response.text)

        results = sorted(response["results"], key=lambda x: x["index"])
        all_scores = [result["relevance_score"] for result in results]

        if normalize:
            all_scores = [sigmoid(score) for score in all_scores]

        return all_scores

    def build_payload(self, query, sentences, max_length = 512):
        return {
            "model": self.model,
            "query": query,
            "documents": sentences,
            "max_chunks_per_doc": max_length,
        }

def get_reranker(config):
    assert config.reranker in config.reranker_names.keys(), f"Unsupported Reranker: {config.reranker}, only support {config.reranker_names.keys()}"
    provider, model_name = config.reranker.split('/', 1)
    if provider == "local":
        return LocalReranker(config)
    elif provider == "siliconflow":
        return SiliconFlowReranker(config)
    elif provider == "zhipu":
        return ZhipuReranker(config)
    else:
        raise ValueError(f"Unsupported Reranker: {config.reranker}, only support {config.reranker_names.keys()}")
