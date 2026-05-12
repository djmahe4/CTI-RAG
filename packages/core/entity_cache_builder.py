"""实体候选缓存构建器

该模块负责从 Neo4j 图数据库导出实体的基础信息，并构建本地缓存文件，
为强化学习推理模型和新图检索接口提供快速的候选实体召回能力。

输出文件默认位于 `RL/cache/entity_candidates.json`，结构如下：

```
{
    "generated_at": 1730800000,
    "total": 100,
    "items": [
        {
            "name": "示例实体",
            "type": "vulnerability",
            "aliases": ["别名1", "别名2"],
            "description": "实体描述",
            "is_event": false,
            "tokens": ["示例", "实体"],
            "embedding": [...]  # 可选
        }
    ],
    "token_index": {
        "示例": ["示例实体"],
        "实体": ["示例实体"]
    }
}
```

缓存中的 token 用于倒排索引式的快速模糊召回；如果需要向量召回，可启用
`include_embeddings=True` 将 Neo4j 节点上的向量属性直接写入缓存。
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

import torch
from neo4j import GraphDatabase

from packages.utils import get_project_root
from packages.utils.logging_config import logger


# 尝试加载中文分词器，缺失时使用降级方案
try:
    import jieba  # type: ignore
except Exception:  # noqa: B902
    jieba = None  # type: ignore
EMBED_MODEL_RELATIVE_PATH = os.path.join("models", "embedding_model", "bge-m3")


_embedding_model_singleton = None


def _normalize_device(device: str) -> str:
    lowered = (device or "").lower()
    if lowered in ("cuda", "gpu"):
        return "cuda"
    return "cpu"


def _get_embedding_model(model_path: Optional[str] = None, device: str = "gpu"):
    global _embedding_model_singleton
    if _embedding_model_singleton is not None:
        return _embedding_model_singleton

    try:
        from RL.utils.embedding_utils import EmbeddingModel
    except Exception as exc:  # noqa: B902
        logger.warning(f"无法导入 EmbeddingModel，跳过实体向量计算: {exc}")
        _embedding_model_singleton = None
        return None

    if not model_path:
        candidate_paths = [
            os.path.join(get_project_root(), EMBED_MODEL_RELATIVE_PATH),
            os.path.join("/app", EMBED_MODEL_RELATIVE_PATH),
        ]
        for cand in candidate_paths:
            if os.path.exists(cand):
                model_path = cand
                break
        else:
            model_path = candidate_paths[0]

    resolved_device = _normalize_device(device)
    if resolved_device == "cuda" and not torch.cuda.is_available():
        resolved_device = "cpu"

    try:
        _embedding_model_singleton = EmbeddingModel(
            model_path=model_path,
            device=resolved_device,
        )
        logger.info(
            f"实体缓存构建器: 已加载向量模型 {model_path} (device={resolved_device})"
        )
    except Exception as exc:  # noqa: B902
        logger.warning(f"加载向量模型失败({model_path}): {exc}")
        _embedding_model_singleton = None

    return _embedding_model_singleton


DEFAULT_OUTPUT_RELATIVE_PATH = os.path.join("RL", "cache", "entity_candidates.json")
DEFAULT_ADJACENCY_PATH = os.path.join("RL", "cache", "adjacency.json")


def _contains_chinese(text: str) -> bool:
    """检查文本是否包含中文字符"""

    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _normalize_aliases(raw_alias: Any) -> List[str]:
    """将 Neo4j 中的 alias/aliases 字段归一化为字符串列表"""

    aliases: Set[str] = set()

    if not raw_alias:
        return []

    def _split_and_add(text: str) -> None:
        if not text:
            return
        parts = re.split(r"[;,，、/\\|]", text)
        for part in parts:
            cleaned = part.strip()
            if cleaned:
                aliases.add(cleaned)

    if isinstance(raw_alias, str):
        _split_and_add(raw_alias)
    elif isinstance(raw_alias, Sequence):  # type: ignore[isinstance-comparison]
        for item in raw_alias:
            if isinstance(item, str):
                _split_and_add(item)
    else:
        _split_and_add(str(raw_alias))

    return sorted(aliases)


def _generate_tokens(*texts: str) -> List[str]:
    """根据名称与别名生成用于倒排索引的 token 列表"""

    token_set: Set[str] = set()

    for text in texts:
        if not text:
            continue
        normalized = text.strip()
        if not normalized:
            continue

        token_set.add(normalized)
        token_set.add(normalized.lower())

        # 英文/符号按非字母数字拆分
        for part in re.split(r"[^A-Za-z0-9]+", normalized.lower()):
            if part:
                token_set.add(part)

        # 中文分词（若可用）
        if jieba is not None and _contains_chinese(normalized):
            for token in jieba.lcut(normalized, cut_all=False):  # type: ignore[attr-defined]
                cleaned = token.strip()
                if cleaned:
                    token_set.add(cleaned)
        else:
            # 简单地逐字符拆分中文，保留长度>1的片段
            chinese_parts = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
            token_set.update(chinese_parts)

    return sorted(token_set)


def generate_candidate_tokens(*texts: str) -> List[str]:
    """对外暴露的 token 生成函数"""

    return _generate_tokens(*texts)


def _load_adjacency_metadata(adjacency_path: str) -> Dict[str, Dict[str, Any]]:
    """加载 adjacency.json 中的节点信息，返回 {name: info} 结构"""

    if not os.path.exists(adjacency_path):
        logger.warning(f"邻接缓存不存在: {adjacency_path}")
        return {}

    try:
        with open(adjacency_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        nodes = payload.get("nodes", {}) or {}
        logger.info(f"已从邻接缓存加载 {len(nodes)} 个节点元信息")
        return nodes
    except Exception as exc:  # noqa: B902
        logger.warning(f"读取邻接缓存失败: {adjacency_path}, {exc}")
        return {}


@dataclass
class EntityRecord:
    """用于序列化的实体结构"""

    name: str
    type: Optional[str]
    aliases: List[str]
    description: Optional[str]
    tokens: List[str]
    is_event: bool
    embedding: Optional[List[float]] = None

    def to_payload(self, include_embedding: bool = False) -> Dict[str, Any]:
        payload = {
            "name": self.name,
            "type": self.type or "unknown",
            "aliases": self.aliases,
            "description": self.description or "",
            "is_event": self.is_event,
            "tokens": self.tokens,
        }
        if include_embedding and self.embedding is not None:
            payload["embedding"] = self.embedding
        return payload


class EntityCandidateCacheBuilder:
    """实体候选缓存构建器"""

    def __init__(
        self,
        neo4j_uri: Optional[str] = None,
        neo4j_user: Optional[str] = None,
        neo4j_password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        self.neo4j_uri = neo4j_uri or os.getenv("NEO4J_URL", "bolt://localhost:7688")
        self.neo4j_user = neo4j_user or os.getenv("NEO4J_USERNAME", "neo4j")
        self.neo4j_password = neo4j_password or os.getenv("NEO4J_PASSWORD", "12345678")
        self.database = database or os.getenv("NEO4J_DATABASE", "neo4j")

        self.driver = GraphDatabase.driver(
            self.neo4j_uri,
            auth=(self.neo4j_user, self.neo4j_password),
        )
        logger.info(
            f"Neo4j 连接初始化成功: uri={self.neo4j_uri}, db={self.database}"
        )

        self._embedding_model = None

    def close(self) -> None:
        """关闭 Neo4j 连接"""

        if hasattr(self, "driver") and self.driver is not None:
            self.driver.close()

    def fetch_entities(self, batch_size: int = 1000) -> Iterable[Dict[str, Any]]:
        """批量获取实体信息"""

        skip = 0
        query = (
            "MATCH (n:Entity) "
            "RETURN n.name AS name, n.type AS type, n.alias AS alias, "
            "n.aliases AS aliases, n.description AS description, n.embedding AS embedding, "
            "n.is_event AS is_event "
            "ORDER BY n.name "
            "SKIP $skip LIMIT $limit"
        )

        while True:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, skip=skip, limit=batch_size)
                records = list(result)

            if not records:
                break

            logger.info(f"已获取实体 {skip + 1} ~ {skip + len(records)}")
            for record in records:
                yield record.data()

            skip += batch_size

    def build_cache(
        self,
        output_path: Optional[str] = None,
        include_embeddings: bool = False,
        adjacency_path: Optional[str] = None,
    ) -> str:
        """构建实体候选缓存"""

        project_root = get_project_root()
        if not output_path:
            output_path = os.path.join(project_root, DEFAULT_OUTPUT_RELATIVE_PATH)
        elif not os.path.isabs(output_path):
            output_path = os.path.join(project_root, output_path)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        if adjacency_path is None:
            adjacency_path = os.path.join(project_root, DEFAULT_ADJACENCY_PATH)
        elif not os.path.isabs(adjacency_path):
            adjacency_path = os.path.join(project_root, adjacency_path)

        adjacency_nodes = _load_adjacency_metadata(adjacency_path)

        if include_embeddings and self._embedding_model is None:
            preferred_device = os.getenv("ENTITY_EMBEDDING_DEVICE", "cuda")
            self._embedding_model = _get_embedding_model(device=preferred_device)

        items: List[EntityRecord] = []
        token_index: Dict[str, List[str]] = {}

        for entity in self.fetch_entities():
            name = entity.get("name")
            if not name:
                continue

            aliases = _normalize_aliases(entity.get("aliases"))
            alias_single = _normalize_aliases(entity.get("alias"))
            merged_aliases = sorted({*aliases, *alias_single})

            description = entity.get("description") or ""
            entity_type = entity.get("type") or "unknown"
            embedding = entity.get("embedding") if include_embeddings else None

            # 兼容 adjacency.json 中的类型与事件标记
            node_meta = adjacency_nodes.get(name, {}) if adjacency_nodes else {}
            if node_meta:
                entity_type = node_meta.get("type", entity_type) or entity_type
            is_event = bool(
                entity.get("is_event")
                or node_meta.get("is_event")
                or node_meta.get("isEvent")
            )

            if include_embeddings and embedding is None and self._embedding_model is not None:
                text_segments = [name]
                if merged_aliases:
                    text_segments.extend(merged_aliases)
                if description:
                    text_segments.append(description)
                combined = "\n".join([seg for seg in text_segments if seg])
                if combined:
                    try:
                        vector = self._embedding_model.encode_text(combined)
                        embedding = [float(v) for v in vector]
                    except Exception as exc:  # noqa: B902
                        logger.debug(f"实体向量计算失败 {name}: {exc}")
                        embedding = None

            tokens = _generate_tokens(name, *merged_aliases)

            record = EntityRecord(
                name=name,
                type=entity_type,
                aliases=merged_aliases,
                description=description,
                tokens=tokens,
                is_event=is_event,
                embedding=embedding,
            )
            items.append(record)

            for token in tokens:
                token_index.setdefault(token, []).append(name)

        payload = {
            "generated_at": int(time.time()),
            "total": len(items),
            "items": [item.to_payload(include_embedding=include_embeddings) for item in items],
            "token_index": token_index,
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        logger.info(f"实体候选缓存已生成: {output_path}, 共 {len(items)} 条记录")
        return output_path


def build_entity_candidate_cache(
    output_path: Optional[str] = None,
    include_embeddings: bool = False,
    adjacency_path: Optional[str] = None,
) -> str:
    """快捷函数：构建实体候选缓存并自动关闭连接"""

    builder = EntityCandidateCacheBuilder()
    try:
        return builder.build_cache(
            output_path=output_path,
            include_embeddings=include_embeddings,
            adjacency_path=adjacency_path,
        )
    finally:
        builder.close()


if __name__ == "__main__":
    # 允许直接运行脚本生成缓存
    import argparse

    parser = argparse.ArgumentParser(description="构建实体候选缓存")
    parser.add_argument(
        "--output",
        dest="output_path",
        default=None,
        help="缓存文件输出路径（默认 RL/cache/entity_candidates.json）",
    )
    parser.add_argument(
        "--include-embeddings",
        action="store_true",
        help="是否包含节点 embedding 向量",
    )
    parser.add_argument(
        "--adjacency",
        dest="adjacency_path",
        default=None,
        help="邻接缓存路径（用于补充节点类型/事件标签）",
    )

    args = parser.parse_args()
    build_entity_candidate_cache(
        output_path=args.output_path,
        include_embeddings=args.include_embeddings,
        adjacency_path=args.adjacency_path,
    )

