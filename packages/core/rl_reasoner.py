"""基于强化学习的图推理器

该模块封装了策略网络与图谱环境，提供从自然语言查询到候选路径
的推理能力，供新 API 使用。
"""

from __future__ import annotations

import os
import traceback
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
import torch

from packages import config
from packages.utils import get_project_root
from packages.utils.logging_config import logger

from .entity_candidate_index import get_entity_candidate_index


try:
    from RL.policy_network import GraphReasoningPolicy
    from RL.graph_env import GraphReasoningEnv
except Exception as exc:  # noqa: B902
    logger.error(f"导入 RL 组件失败: {exc}")
    raise


@dataclass
class RLPathResult:
    start_entity: str
    path: List[Any]
    reward: float
    steps: int
    reason: str
    reached_target: bool
    candidate_info: Dict[str, Any]


class RLGraphReasoner:
    """强化学习图推理器"""

    def __init__(self) -> None:
        self.project_root = get_project_root()
        self.device = config.get("rl_device", "cuda")
        if self.device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                "RL 推理配置为使用 CUDA，但当前环境未检测到可用 GPU。"
            )

        self.base_model_path = self._resolve_path(config.get("rl_base_model_path"))
        self.lora_path = self._resolve_path(config.get("rl_lora_path"))
        self.policy_checkpoint = self._resolve_path(
            config.get("rl_policy_checkpoint_path")
        )

        self.max_steps = int(config.get("rl_max_steps", 4))
        self.candidate_top_k = int(config.get("rl_candidate_top_k", 3))

        self.neo4j_uri = os.getenv("NEO4J_URL", "bolt://localhost:7688")
        self.neo4j_user = os.getenv("NEO4J_USERNAME", "neo4j")
        self.neo4j_password = os.getenv("NEO4J_PASSWORD", "12345678")
        self.neo4j_db = os.getenv("NEO4J_DATABASE", "neo4j")

        self.adjacency_path = self._resolve_path(
            config.get("rl_adjacency_path", os.path.join("RL", "cache", "adjacency.json"))
        )

        self.policy: Optional[GraphReasoningPolicy] = None
        self.policy_loaded = False
        self.candidate_index = get_entity_candidate_index()

    def _resolve_path(self, path: Optional[str]) -> Optional[str]:
        if not path:
            return None
        if os.path.isabs(path):
            return path
        return os.path.join(self.project_root, path)

    def _ensure_policy(self) -> None:
        if self.policy_loaded:
            return

        if not self.base_model_path or not os.path.exists(self.base_model_path):
            raise RuntimeError(f"RL 基础模型路径不存在: {self.base_model_path}")
        if not self.policy_checkpoint or not os.path.exists(self.policy_checkpoint):
            raise RuntimeError(f"RL 策略权重不存在: {self.policy_checkpoint}")

        logger.info(
            f"初始化 RL 策略网络: base={self.base_model_path}, lora={self.lora_path}, device={self.device}"
        )

        self.policy = GraphReasoningPolicy(
            base_model_path=self.base_model_path,
            lora_path=self.lora_path,
            device=self.device,
        )
        self.policy.eval()

        try:
            self.policy.load(self.policy_checkpoint)
            self.policy.eval()
            self.policy_loaded = True
            logger.info("RL 策略权重加载完成")
        except Exception as exc:  # noqa: B902
            logger.error(f"加载 RL 策略权重失败: {exc}, {traceback.format_exc()}")
            raise

    def _create_env(self) -> GraphReasoningEnv:
        return GraphReasoningEnv(
            neo4j_uri=self.neo4j_uri,
            neo4j_user=self.neo4j_user,
            neo4j_password=self.neo4j_password,
            max_steps=self.max_steps,
            adjacency_path=self.adjacency_path,
            reward_mode="event_centric",
        )

    def _run_episode(
        self,
        env: GraphReasoningEnv,
        query: str,
        start_entity: str,
        candidate_info: Dict[str, Any],
        deterministic: bool = True,
    ) -> RLPathResult:
        assert self.policy is not None

        state = env.reset(
            question=query,
            start_entity=start_entity,
            question_type="threat_qa",
            answer_paths=[],
            expected_entities=None,
        )

        total_reward = 0.0
        steps = 0
        final_reason = ""
        reached_target = False
        last_info: Dict[str, Any] = {}

        while True:
            action, action_info = self.policy.select_action(
                state,
                deterministic=deterministic,
                temperature=1.0,
            )

            state, reward, done, info = env.step(action)
            steps += 1
            total_reward += reward
            last_info = info

            if done:
                final_reason = info.get("reason", "finished")
                reached_target = bool(info.get("reached_target"))
                break

        path = last_info.get("path", []) if last_info else []

        return RLPathResult(
            start_entity=start_entity,
            path=path,
            reward=total_reward,
            steps=steps,
            reason=final_reason,
            reached_target=reached_target,
            candidate_info=candidate_info,
        )

    def reason(
        self,
        query: str,
        top_k: Optional[int] = None,
        deterministic: bool = True,
    ) -> List[Dict[str, Any]]:
        if not query:
            return []

        self._ensure_policy()

        top_k = top_k or self.candidate_top_k
        candidates, query_vector = self.candidate_index.search(query, top_k=top_k)
        if not candidates:
            logger.warning(f"RL 推理未找到候选起始实体: {query}")
            return []

        query_embedding = None
        if query_vector is not None:
            query_embedding = np.asarray(query_vector, dtype=np.float32)
            norm = float(np.linalg.norm(query_embedding))
            if norm > 0.0:
                query_embedding = query_embedding / norm

        env = self._create_env()
        results: List[Dict[str, Any]] = []

        try:
            for candidate in candidates:
                start_entity = candidate.get("name")
                if not start_entity:
                    continue

                try:
                    episode = self._run_episode(
                        env=env,
                        query=query,
                        start_entity=start_entity,
                        candidate_info=candidate,
                        deterministic=deterministic,
                    )

                    collected = env.get_collected_subgraph()
                    results.append(
                        {
                            "start_entity": episode.start_entity,
                            "candidate": candidate,
                            "path": episode.path,
                            "reward": episode.reward,
                            "steps": episode.steps,
                            "reason": episode.reason,
                            "reached_target": episode.reached_target,
                            "collected_subgraph": collected,
                        }
                    )
                except Exception as exc:  # noqa: B902
                    logger.error(
                        f"RL 推理失败: start_entity={start_entity}, {exc}, {traceback.format_exc()}"
                    )
                    continue

        finally:
            env.close()

        results = self._rerank_paths(results, query_embedding)
        return results

    def _rerank_paths(
        self,
        results: List[Dict[str, Any]],
        query_embedding: Optional[np.ndarray],
    ) -> List[Dict[str, Any]]:
        if not results or query_embedding is None:
            results.sort(key=lambda item: item.get("reward", 0.0), reverse=True)
            return results

        embedding_model = self.candidate_index.get_embedding_model()
        if embedding_model is None:
            results.sort(key=lambda item: item.get("reward", 0.0), reverse=True)
            return results

        reranked: List[Dict[str, Any]] = []
        for item in results:
            path = item.get("path") or []
            path_segments = []
            for hop in path:
                if isinstance(hop, (list, tuple)) and len(hop) >= 3:
                    path_segments.append(f"{hop[0]} {hop[1]} {hop[2]}")
            path_text = "\n".join(path_segments)

            similarity = 0.0
            if path_text:
                try:
                    path_vec = np.asarray(
                        embedding_model.encode_text(path_text), dtype=np.float32
                    )
                    norm = float(np.linalg.norm(path_vec))
                    if norm > 0.0:
                        path_vec = path_vec / norm
                        similarity = float(np.dot(query_embedding, path_vec))
                except Exception as exc:  # noqa: B902
                    logger.debug(f"路径相似度计算失败: {exc}")

            enriched = dict(item)
            enriched["similarity"] = similarity
            reranked.append(enriched)

        reranked.sort(
            key=lambda item: (item.get("similarity", 0.0), item.get("reward", 0.0)),
            reverse=True,
        )
        return reranked


_rl_reasoner_instance: Optional[RLGraphReasoner] = None


def get_rl_reasoner() -> RLGraphReasoner:
    global _rl_reasoner_instance
    if _rl_reasoner_instance is None:
        _rl_reasoner_instance = RLGraphReasoner()
    return _rl_reasoner_instance

