"""Entity Candidate Index

Provide quick search capability to start entities for queries，For RL Use of graphic reasoning services。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch

from packages.utils import get_project_root
from packages.utils.logging_config import logger

from .entity_cache_builder import generate_candidate_tokens


DEFAULT_CACHE_RELATIVE_PATH = os.path.join("RL", "cache", "entity_candidates.json")


class EntityCandidateIndex:
    """Entity Candidate Indexer"""

    def __init__(self, cache_path: Optional[str] = None) -> None:
        self.cache_path = cache_path
        self.items: List[Dict[str, Any]] = []
        self.token_index: Dict[str, List[str]] = {}
        self.item_map: Dict[str, Dict[str, Any]] = {}
        self.items_with_embedding: List[Dict[str, Any]] = []
        self.embedding_matrix: Optional[np.ndarray] = None
        self._embedding_model = None

        self._load()

    def _resolve_cache_path(self) -> str:
        if self.cache_path:
            if os.path.isabs(self.cache_path):
                return self.cache_path
            return os.path.join(get_project_root(), self.cache_path)
        return os.path.join(get_project_root(), DEFAULT_CACHE_RELATIVE_PATH)

    def _load(self) -> None:
        path = self._resolve_cache_path()
        if not os.path.exists(path):
            logger.warning(
                f"实体候选缓存未找到: {path}，请先运行 packages.core.entity_cache_builder"  # noqa: E501
            )
            self.items = []
            self.token_index = {}
            self.item_map = {}
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as exc:  # noqa: B902
            logger.error(f"Failed to load entity cache: {path}, {exc}")
            self.items = []
            self.token_index = {}
            self.item_map = {}
            return

        self.items = payload.get("items", []) or []
        self.token_index = payload.get("token_index", {}) or {}
        self.item_map = {item["name"]: item for item in self.items if item.get("name")}

        self.items_with_embedding = []
        embeddings: List[np.ndarray] = []
        for item in self.items:
            vector = item.get("embedding")
            if isinstance(vector, list) and vector:
                np_vec = np.asarray(vector, dtype=np.float32)
                norm = float(np.linalg.norm(np_vec))
                if norm > 0.0:
                    np_vec = np_vec / norm
                self.items_with_embedding.append(item)
                embeddings.append(np_vec)

        if embeddings:
            self.embedding_matrix = np.stack(embeddings)
        else:
            self.embedding_matrix = None

        logger.info(
            f"Entity Cache Load complete: {path}, Total {len(self.items)} Notes"
        )

    def reload(self) -> None:
        """Reload Cache File"""

        self._load()

    def get_embedding_model(self):
        if self.embedding_matrix is None:
            return None

        if self._embedding_model is not None:
            return self._embedding_model

        from RL.utils.embedding_utils import EmbeddingModel

        model_path = os.getenv(
            "ENTITY_EMBED_MODEL_PATH",
            os.path.join(get_project_root(), "models", "embedding_model", "bge-m3"),
        )
        device = os.getenv("ENTITY_EMBEDDING_DEVICE", "cuda").lower()
        if device in ("cuda", "gpu"):
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = "cpu"

        try:
            self._embedding_model = EmbeddingModel(model_path=model_path, device=device)
            logger.info(f"Entity Index: Loaded vector model {model_path} (device={device})")
        except Exception as exc:  # noqa: B902
            logger.error(f"Entity Index Loading Vector Model failed: {exc}")
            self._embedding_model = None

        return self._embedding_model

    def _score_candidate(self, candidate: Dict[str, Any], query: str) -> float:
        score = 0.0
        name = candidate.get("name", "")
        aliases = candidate.get("aliases", []) or []
        description = candidate.get("description", "") or ""

        query_lower = query.lower()
        if name and name.lower() in query_lower:
            score += 2.0

        for alias in aliases:
            if alias and alias.lower() in query_lower:
                score += 1.5

        if description and name and name in description:
            score += 0.5

        return score

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.5,
    ) -> Tuple[List[Dict[str, Any]], Optional[List[float]]]:
        """Returns a matching entity candidate based on query text"""

        if not query or not self.items:
            return [], None

        if self.embedding_matrix is not None and len(self.items_with_embedding) > 0:
            embedding_model = self.get_embedding_model()
            if embedding_model is not None:
                try:
                    query_vec = np.asarray(embedding_model.encode_text(query), dtype=np.float32)
                    norm = float(np.linalg.norm(query_vec))
                    if norm > 0.0:
                        query_vec = query_vec / norm
                    scores = self.embedding_matrix @ query_vec
                    sorted_indices = np.argsort(-scores)
                    results: List[Dict[str, Any]] = []
                    for idx in sorted_indices:
                        candidate = self.items_with_embedding[idx]
                        score = float(scores[idx])
                        if score < min_score:
                            continue
                        enriched = dict(candidate)
                        enriched.pop("embedding", None)
                        enriched["score"] = score
                        results.append(enriched)
                        if len(results) >= top_k:
                            break
                    if results:
                        return results, query_vec.tolist()
                except Exception as exc:  # noqa: B902
                    logger.error(f"Entities embedding Match Failed: {exc}")

        # fallback: token + keyword match
        tokens = generate_candidate_tokens(query)
        candidate_scores: Dict[str, float] = {}

        for token in tokens:
            related_names = self.token_index.get(token, [])
            if not related_names:
                continue
            token_weight = 1.0 + min(len(token) / 10.0, 1.0)
            for name in related_names:
                candidate_scores[name] = candidate_scores.get(name, 0.0) + token_weight

        for name, item in self.item_map.items():
            candidate_scores[name] = candidate_scores.get(name, 0.0) + self._score_candidate(item, query)

        scored_items: List[Tuple[float, Dict[str, Any]]] = []
        for name, score in candidate_scores.items():
            candidate = self.item_map.get(name)
            if not candidate or score < min_score:
                continue
            scored_items.append((score, candidate))

        scored_items.sort(key=lambda x: x[0], reverse=True)

        results: List[Dict[str, Any]] = []
        for score, candidate in scored_items[:top_k]:
            enriched = dict(candidate)
            enriched.pop("embedding", None)
            enriched["score"] = score
            results.append(enriched)

        return results, None


# Individual Index (avoiding the reloading of large files on API)
_cached_index: Optional[EntityCandidateIndex] = None


def get_entity_candidate_index() -> EntityCandidateIndex:
    global _cached_index
    if _cached_index is None:
        _cached_index = EntityCandidateIndex()
    return _cached_index

