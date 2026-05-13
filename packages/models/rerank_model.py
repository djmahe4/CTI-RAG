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
    """Think.AI Reranker - Use the spectraAIOther OrganiserAPI"""
    def __init__(self, config, **kwargs):
        self.url = "https://open.bigmodel.cn/api/paas/v4/rerank"
        self.model = "rerank"
        
        api_key = os.getenv("ZHIPUAI_API_KEY")
        assert api_key, "ZHIPUAI_API_KEY is required for ZhipuReranker"
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        logger.info(f"ZhipuReranker Initialization succeeded，Model: {self.model}")

    def compute_score(self, sentence_pairs, batch_size=256, max_length=4096, normalize=False):
        """
        Calculates the document 's relevance to queries，Compatible two input formats。
        1. [query, [doc1, doc2, ...]]
        2. [[query, doc1], [query, doc2], ...]
        """
        # Format Fit
        if (isinstance(sentence_pairs, list) and len(sentence_pairs) > 0 and
                isinstance(sentence_pairs[0], list) and len(sentence_pairs[0]) == 2):
            logger.debug(f"ZhipuReranker: Fitting list of pairs Input Format。")
            query = sentence_pairs[0][0]
            documents = [pair[1] for pair in sentence_pairs]
        elif (isinstance(sentence_pairs, list) and len(sentence_pairs) == 2 and
                isinstance(sentence_pairs[0], str) and isinstance(sentence_pairs[1], list)):
            logger.debug(f"ZhipuReranker: Use [query, [documents]] Input Format。")
            query, documents = sentence_pairs
        else:
            raise ValueError(f"ZhipuReranker Received invalid input format: {type(sentence_pairs)}")

        # Interrupted long documents
        truncated_docs = [doc[:max_length] if len(doc) > max_length else doc for doc in documents]
        
        # Build Request Payload
        payload = {
            "model": self.model,
            "query": query[:max_length],  # The query is also limited to 4096 characters.
            "documents": truncated_docs,
            "return_documents": False,  # Do not return original text, save bandwidth
        }
        
        try:
            logger.debug(f"Call the brainbook.AI Rerank API: query='{query[:50]}...', Number of documents={len(documents)}")
            response = requests.post(self.url, json=payload, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            response_data = response.json()
            logger.debug(f"Think.AI Rerank API Response: {response_data}")
            
            results = response_data.get("results", [])
            
            if not results:
                logger.warning(f"Think.AI Rerank API Return empty result")
                return [0.5] * len(documents)  # Returns default score
            
            # Rebuild the fraction list in original index order
            scores = [0.0] * len(documents)
            for result in results:
                index = result.get("index", 0)
                score = result.get("relevance_score", 0.0)
                if 0 <= index < len(documents):
                    scores[index] = score
            
            # Normalization (if required)
            if normalize:
                scores = [sigmoid(score) for score in scores]
            
            logger.info(f"Think.AI Rerank Success: Processing {len(documents)} Document, Average score={sum(scores)/len(scores):.4f}")
            return scores
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Think.AI Rerank API Request Failed: {e}"
            if e.response is not None:
                error_msg += f", Response: {e.response.text}"
            logger.error(error_msg)
            raise RuntimeError(f"Think.AI Rerank API Call Failed: {e}") from e
        except Exception as e:
            logger.error(f"Think.AI Rerank Process error: {e}")
            raise RuntimeError(f"Think.AI Rerank Process failed: {e}") from e

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
        Calculates the document 's relevance to queries，Compatible two input formats。
        1. [query, [doc1, doc2, ...]]
        2. [[query, doc1], [query, doc2], ...]
        """
        # Format Fit
        if (isinstance(sentence_pairs, list) and len(sentence_pairs) > 0 and
                isinstance(sentence_pairs[0], list) and len(sentence_pairs[0]) == 2):
            logger.debug(f"SiliconFlowReranker: Fitting list of pairs Input Format。")
            query = sentence_pairs[0][0]
            documents = [pair[1] for pair in sentence_pairs]
        elif (isinstance(sentence_pairs, list) and len(sentence_pairs) == 2 and
                isinstance(sentence_pairs[0], str) and isinstance(sentence_pairs[1], list)):
            logger.debug(f"SiliconFlowReranker: Use [query, [documents]] Input Format。")
            query, documents = sentence_pairs
        else:
            raise ValueError(f"SiliconFlowReranker Received invalid input format: {type(sentence_pairs)}")

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
