import os
import json
import asyncio
import traceback
import uuid
import re
import requests
from fastapi import APIRouter, Body, Depends, HTTPException, Header, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk
from packages import executor, retriever, config
from packages.core import HistoryManager
from packages.models import build_model_router, select_model
from packages.utils.logging_config import logger
from rag.cache.redis_session import RedisSessionManager
from rag.cache.redis_runtime import RedisRuntimeStore
from rag.config.runtime_config import RuntimeConfig
from packages.manager.chat_session_manager import get_chat_session_manager
from rag.utils.coroutine_pool import CoroutinePool
from typing import Optional, Dict, List, Any
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 创建限流器
limiter = Limiter(key_func=get_remote_address)

# 创建路由
chat = APIRouter(prefix="/chat")

# 初始化Redis会话管理器
redis_session = RedisSessionManager(
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
    expire_time=int(os.getenv("SESSION_EXPIRE_TIME", "3600"))
)

# 初始化聊天会话管理器（整合MySQL和Redis）
chat_session_manager = get_chat_session_manager(redis_manager=redis_session)

# 初始化协程池
coroutine_pool = CoroutinePool(
    max_workers=int(os.getenv("MAX_CONCURRENT_CHATS", "20"))
)

SUBGRAPH_SERVICE_URL = os.getenv("SUBGRAPH_SERVICE_URL", "http://localhost:8013/prune_subgraph")
runtime_config = RuntimeConfig.from_env()
runtime_store = RedisRuntimeStore(
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    config=runtime_config,
)
model_router = build_model_router(config=runtime_config, runtime_store=runtime_store)

@chat.get("/")
async def chat_get():
    return "Chat Get!"


def _resolve_expected_route(meta: dict | None = None) -> tuple[str, str]:
    meta = meta or {}
    expected_provider = meta.get("model_provider") or config.model_provider
    model_info = config.model_names.get(expected_provider, {})
    expected_model_name = meta.get("model_name") or model_info.get("default") or config.model_name
    return expected_provider, expected_model_name


def _requested_route(meta: dict | None = None) -> tuple[str, str] | None:
    meta = meta or {}
    if not meta.get("model_provider") and not meta.get("model_name"):
        return None
    return _resolve_expected_route(meta)


def _populate_route_meta(meta: dict | None, expected_route: tuple[str, str], routed_prediction) -> dict:
    if meta is None:
        meta = {}
    expected_provider, expected_model_name = expected_route
    meta["expected_model_provider"] = expected_provider
    meta["expected_model_name"] = expected_model_name
    meta["actual_model_provider"] = routed_prediction.actual_provider
    meta["actual_model_name"] = routed_prediction.actual_model_name
    meta["degraded"] = routed_prediction.degraded
    meta["route_reason"] = routed_prediction.route_reason
    meta["server_model_provider"] = routed_prediction.actual_provider
    meta["server_model_name"] = routed_prediction.actual_model_name
    return meta


async def route_model_predict(messages, meta: dict | None = None, stream: bool = False):
    expected_route = _resolve_expected_route(meta)
    preferred_route = _requested_route(meta)
    routed_prediction = await model_router.predict(
        messages,
        preferred_route=preferred_route,
        stream=stream,
    )
    _populate_route_meta(meta, expected_route, routed_prediction)
    return routed_prediction.output

def _match_start_node_id(query: str, meta: dict | None = None) -> str | None:
    """
    仅匹配 IPv4 作为起始节点 ID。
    规则：
    1) meta.start_node_id 若是合法 IPv4，直接返回。
    2) 在 query 中查找 IPv4（含显式键值对，如 start_node_id=1.2.3.4，或自然语言中出现的 IP）。
    """
    meta = meta or {}

    def _is_ipv4(text: str) -> bool:
        m = re.match(r"^(?:\d{1,3}\.){3}\d{1,3}$", text.strip())
        if not m:
            return False
        parts = text.split(".")
        return all(0 <= int(p) <= 255 for p in parts)

    if meta.get("start_node_id") and _is_ipv4(str(meta["start_node_id"])):
        return str(meta["start_node_id"])

    text = query or ""
    # 先匹配显式键值对形式
    key_patterns = [
        r"start[_\s-]*node[_\s-]*id[:=]\s*((?:\d{1,3}\.){3}\d{1,3})",
        r"node[_\s-]*id[:=]\s*((?:\d{1,3}\.){3}\d{1,3})",
        r"\bnode[:=]\s*((?:\d{1,3}\.){3}\d{1,3})",
        r"ip[:=]\s*((?:\d{1,3}\.){3}\d{1,3})",
    ]
    for pat in key_patterns:
        if m := re.search(pat, text, flags=re.IGNORECASE):
            ip = m.group(1)
            if _is_ipv4(ip):
                return ip

    # 语义匹配：句子中出现的第一个 IPv4
    if m := re.search(r"((?:\d{1,3}\.){3}\d{1,3})", text):
        ip = m.group(1)
        if _is_ipv4(ip):
            return ip

    return None

@chat.post("/sessions/create")
async def create_new_session(
    user_id: int = Body(..., description="用户ID"),
    title: str = Body(None, description="会话标题（可选）"),
    system_prompt: str = Body(None, description="系统提示词（可选）")
):
    """创建新的聊天会话
    
    Args:
        user_id: 用户ID（必需）
        title: 会话标题（可选，如不提供则自动生成）
        system_prompt: 系统提示词（可选）
        
    Returns:
        新创建的会话信息，包含 session_id
    """
    try:
        session_id = await chat_session_manager.create_session(
            user_id=user_id,
            title=title,
            system_prompt=system_prompt
        )
        
        logger.info(f"创建新会话成功: session_id={session_id}, user_id={user_id}")
        
        return {
            "success": True,
            "session_id": session_id,
            "message": "会话创建成功"
        }
    except Exception as e:
        logger.error(f"创建会话失败: {e}")
        raise HTTPException(status_code=500, detail="创建会话失败，请稍后重试")

@chat.post("/stream")
@limiter.limit("30/minute")
async def chat_post(
        request: Request,
        query: str = Body(..., description="用户的输入查询文本"),
        user_id: int = Body(..., description="用户ID（必需）"),
        thread_id: str = Body(None, description="会话ID（可选，不提供则自动创建）"),
        meta: dict = Body(None, description="请求元数据")):
    """在会话中进行聊天（流式响应）
    
    Args:
        query: 用户的输入查询文本（必需）
        user_id: 用户ID（必需）
        thread_id: 会话ID（可选）
            - 如果提供：使用已有会话
            - 如果不提供：自动创建新会话
        meta: 包含请求元数据的字典，可以包含以下字段：
            - title: 会话标题（仅在自动创建时使用）
            - system_prompt: 系统提示词（仅在自动创建时使用）
            - use_web: 是否使用网络搜索
            - use_graph: 是否使用知识图谱
            - db_id: 数据库ID
            - history_round: 历史对话轮数限制
            - search_mode: 图搜索模式 (local/global/hybrid，默认hybrid)
            - top_k: 搜索结果数量限制 (默认10)
            - threshold: 相似度阈值 (默认0.7)
            - model_provider: 模型提供商 (可选，如 "deepseek", "custom" 等)
            - model_name: 模型名称 (可选)
            
    Returns:
        StreamingResponse: 返回一个流式响应
        
    Note:
        推荐先使用 POST /chat/sessions/create 创建会话以获得更好的控制
    """
    meta = meta or {}
    
    # 如果没有提供 thread_id，自动创建新会话
    if not thread_id:
        try:
            thread_id = await chat_session_manager.create_session(
                user_id=user_id,
                title=meta.get("title"),
                system_prompt=meta.get("system_prompt")
            )
            logger.info(f"自动创建新会话: thread_id={thread_id}, user_id={user_id}")
        except Exception as e:
            logger.error(f"创建会话失败: {e}")
            raise HTTPException(status_code=500, detail="创建会话失败，请稍后重试")
    else:
        # 验证会话是否存在且用户有权访问
        session = await chat_session_manager.get_session(
            session_id=thread_id,
            user_id=user_id,
            include_messages=False
        )
        
        if not session:
            logger.warning(f"会话不存在或用户无权访问: thread_id={thread_id}, user_id={user_id}")
            raise HTTPException(
                status_code=404,
                detail="会话不存在或无权访问"
            )
    
    # 从数据库获取历史记录（先Redis后MySQL）
    try:
        history = await chat_session_manager.get_history(
            session_id=thread_id,
            user_id=user_id
        )
        logger.debug(f"获取会话历史: thread_id={thread_id}, 消息数={len(history)}")
    except Exception as e:
        logger.error(f"获取会话历史失败: {e}")
        history = []
    
    # 初始化历史管理器
    history_manager = HistoryManager(history, system_prompt=meta.get("system_prompt"))
    logger.debug(f"Received query: {query} with meta: {meta}")
    
    # 确保meta中包含show_retrieval_info参数，默认为True
    if "show_retrieval_info" not in meta:
        meta["show_retrieval_info"] = True

    def make_chunk(content=None, **kwargs):
        return json.dumps({
            "response": content,
            "meta": meta,
            "thread_id": thread_id,  # 返回thread_id给客户端
            **kwargs
        }, ensure_ascii=False).encode('utf-8') + b"\n"

    def need_retrieve(meta):
        return meta.get("use_web") or meta.get("use_graph") or meta.get("db_id")

    async def process_chat():
        modified_query = query
        refs = None

        # 处理知识库检索
        if meta and need_retrieve(meta):
            yield make_chunk(status="searching")

            try:
                # 使用协程池提交检索任务
                retrieval_result = await coroutine_pool.submit(
                    asyncio.to_thread(retriever, modified_query, history_manager.messages, meta)
                )
                modified_query, refs = retrieval_result
            except Exception as e:
                logger.error(f"Retriever error: {e}, {traceback.format_exc()}")
                yield make_chunk(message=f"Retriever error: {e}", status="error")
                return

            yield make_chunk(status="generating")

        messages = history_manager.get_history_with_msg(modified_query, max_rounds=meta.get('history_round'))
        history_manager.add_user(query)  # 注意这里使用原始查询
        
        # 保存用户消息到数据库（同时写入MySQL和Redis）
        try:
            await chat_session_manager.add_message(
                session_id=thread_id,
                role="user",
                content=query,
                user_id=user_id
            )
        except Exception as e:
            logger.error(f"保存用户消息失败: {e}")

        content = ""
        reasoning_content = ""
        try:
            # 使用协程池提交模型预测任务
            model_stream = await route_model_predict(messages, meta, stream=True)
            
            for delta in model_stream:
                if not delta.content and hasattr(delta, 'reasoning_content'):
                    reasoning_content += delta.reasoning_content or ""
                    chunk = make_chunk(reasoning_content=reasoning_content, status="reasoning")
                    yield chunk
                    continue

                # 文心一言
                if hasattr(delta, 'is_full') and delta.is_full:
                    content = delta.content
                else:
                    content += delta.content or ""

                chunk = make_chunk(content=delta.content, status="loading")
                yield chunk

            logger.debug(f"Final response: {content}")
            logger.debug(f"Final reasoning response: {reasoning_content}")
            
            # 保存助手回复到数据库（同时写入MySQL和Redis）
            try:
                await chat_session_manager.add_message(
                    session_id=thread_id,
                    role="assistant",
                    content=content,
                    user_id=user_id
                )
            except Exception as e:
                logger.error(f"保存助手回复失败: {e}")
                
            # 只返回refs的摘要信息，避免输出大量数据
            refs_summary = None
            if refs:
                refs_summary = {
                    "knowledge_base_count": len(refs.get("knowledge_base", {}).get("results", [])),
                    "graph_base_count": len(refs.get("graph_base", {}).get("results", [])),
                    "web_search_count": len(refs.get("web_search", {}).get("results", [])),
                    "entities": refs.get("entities", [])[:5]  # 只返回前5个实体
                }
            
            yield make_chunk(status="finished",
                            history=history_manager.update_ai(content),
                            refs=refs_summary)
        except Exception as e:
            logger.error(f"Model error: {e}, {traceback.format_exc()}")
            yield make_chunk(message=f"Model error: {e}", status="error")
            return

    # 使用StreamingResponse返回异步生成器
    return StreamingResponse(process_chat(), media_type='application/json')


@chat.post("/temporary")
@limiter.limit("60/minute")
async def temporary_chat(
        request: Request,
        query: str = Body(..., description="用户的输入查询文本"),
        meta: dict = Body(None, description="请求元数据")):
    """
    进行一次性的临时聊天（流式响应），不涉及任何数据库读写或历史记录。
    主要用于功能测试和实验。

    Args:
        query: 用户的输入查询文本（必需）
        meta: 包含请求元数据的字典，功能与 /chat/stream 接口一致
            
    Returns:
        StreamingResponse: 返回一个流式响应
    """
    meta = meta or {}
    # history 被硬编码为空列表
    history = []

    # 初始化历史管理器 (使用空的临时历史)
    history_manager = HistoryManager(history, system_prompt=meta.get("system_prompt"))
    logger.debug(f"Temporary chat received query: {query} with meta: {meta}")
    
    # 确保meta中包含show_retrieval_info参数，默认为True
    if "show_retrieval_info" not in meta:
        meta["show_retrieval_info"] = True

    def make_chunk(content=None, **kwargs):
        return json.dumps({
            "response": content,
            "meta": meta,
            **kwargs
        }, ensure_ascii=False).encode('utf-8') + b"\n"

    def need_retrieve(meta):
        return meta.get("use_web") or meta.get("use_graph") or meta.get("db_id")

    async def process_chat():
        modified_query = query
        refs = None

        if meta and need_retrieve(meta):
            yield make_chunk(status="searching")

            try:
                # 使用协程池提交检索任务
                retrieval_result = await coroutine_pool.submit(
                    asyncio.to_thread(retriever, modified_query, history_manager.messages, meta)
                )
                modified_query, refs = retrieval_result
            except Exception as e:
                logger.error(f"Retriever error: {e}, {traceback.format_exc()}")
                yield make_chunk(message=f"Retriever error: {e}", status="error")
                return

            yield make_chunk(status="generating")

        messages = history_manager.get_history_with_msg(modified_query, max_rounds=meta.get('history_round'))
        
        content = ""
        try:
            # 使用协程池提交模型预测任务
            model_stream = await route_model_predict(messages, meta, stream=True)
            
            for delta in model_stream:
                content += delta.content or ""
                chunk = make_chunk(content=delta.content, status="loading")
                yield chunk

            logger.debug(f"Final response for temporary chat: {content}")
            
            refs_summary = None
            if refs:
                refs_summary = {
                    "knowledge_base_count": len(refs.get("knowledge_base", {}).get("results", [])),
                    "graph_base_count": len(refs.get("graph_base", {}).get("results", [])),
                    "web_search_count": len(refs.get("web_search", {}).get("results", [])),
                    "entities": refs.get("entities", [])[:5]
                }
            
            yield make_chunk(status="finished", refs=refs_summary)
        except Exception as e:
            logger.error(f"Model error in temporary chat: {e}, {traceback.format_exc()}")
            yield make_chunk(message=f"Model error: {e}", status="error")
            return

    return StreamingResponse(process_chat(), media_type='application/json')


@chat.post("/prune_subgraph")
async def prune_subgraph(
    query: str = Body(..., description="用户的输入查询文本，需包含起始节点标识"),
    meta: dict | None = Body(None, description="请求元数据（可选，支持 start_node_id、max_edges、return_mode）"),
):
    """
    基于离线子图裁剪服务生成精简子图，并结合检索结果和模型回答。
    - 不需要用户/会话 ID。
    - 起始节点 ID 优先从 meta.start_node_id 获取，否则从 query 中解析 (node_id=xxx / start_node_id=xxx / node=xxx)。
    - 会调用本地 8013 端口的裁剪服务。
    """
    meta = meta or {}

    start_node_id = _match_start_node_id(query, meta)

    # 复用检索逻辑：按需检索知识库/图谱/网页
    def make_chunk(content=None, **kwargs):
        return json.dumps({
            "response": content,
            "meta": meta,
            "start_node_id": start_node_id,
            **kwargs
        }, ensure_ascii=False).encode('utf-8') + b"\n"

    def need_retrieve(m):
        # 仅当提供 db_id 时才开启知识库（向量）检索，暂不支持 web/graph
        return bool(m.get("db_id"))

    async def process_prune():
        modified_query = query
        refs = {"knowledge_base": {"results": []}, "graph_base": {"results": []}}

        # 可选：先做向量/图检索
        if need_retrieve(meta):
            yield make_chunk(status="searching")
            try:
                retrieval_result = await coroutine_pool.submit(
                    asyncio.to_thread(retriever, modified_query, [], meta)
                )
                modified_query, kb_refs = retrieval_result
                refs["knowledge_base"] = kb_refs or {"results": []}
            except Exception as exc:
                logger.error(f"Retriever error: {exc}, {traceback.format_exc()}")
                yield make_chunk(status="error", message=f"Retriever error: {exc}")
                return

        # 调用子图裁剪服务
        yield make_chunk(status="subgraph_pruning")
        payload = {
            "question": query,
            "max_edges": meta.get("max_edges"),
            "return_mode": meta.get("return_mode", "graph"),
        }
        if start_node_id:
            payload["start_node_id"] = start_node_id
        try:
            resp = requests.post(SUBGRAPH_SERVICE_URL, json=payload, timeout=30)
            if resp.status_code == 404:
                yield make_chunk(status="error", message="NOT_FOUND: 起始节点不在离线图中")
                return
            if resp.status_code == 500:
                yield make_chunk(status="error", message="MODEL_NOT_LOADED: 子图裁剪模型未加载")
                return
            resp.raise_for_status()
            subgraph = resp.json()
        except requests.RequestException as exc:
            logger.error(f"调用子图裁剪服务失败: {exc}")
            yield make_chunk(status="error", message=f"调用子图裁剪服务失败: {exc}")
            return

        graph_payload = subgraph.get("graph", {}) if isinstance(subgraph, dict) else {}
        graph_nodes = graph_payload.get("nodes", []) if isinstance(graph_payload, dict) else []
        graph_edges = graph_payload.get("edges", []) if isinstance(graph_payload, dict) else []
        node_name_map = {}
        for node in graph_nodes:
            if not isinstance(node, dict):
                continue
            node_id = node.get("id")
            props = node.get("props", {}) if isinstance(node.get("props"), dict) else {}
            node_name = (
                node.get("name")
                or props.get("name")
                or props.get("title")
                or node_id
            )
            if node_id is not None:
                node_name_map[str(node_id)] = node_name

        normalized_edges = []
        for edge in graph_edges:
            if not isinstance(edge, dict):
                continue
            source = edge.get("source")
            target = edge.get("target")
            source_name = edge.get("source_name") or node_name_map.get(str(source), source)
            target_name = edge.get("target_name") or node_name_map.get(str(target), target)
            normalized_edges.append({
                "source_name": source_name,
                "target_name": target_name,
                "type": edge.get("type") or edge.get("label") or edge.get("relation"),
            })

        if graph_nodes and normalized_edges:
            graph_results = {"nodes": graph_nodes, "edges": normalized_edges}
        else:
            graph_results = normalized_edges

        refs["graph_base"] = {"results": graph_results}

        try:
            modified_query = retriever.construct_query(modified_query, refs, meta)
        except Exception as exc:
            logger.error(f"构造查询失败: {exc}, {traceback.format_exc()}")
            yield make_chunk(status="error", message=f"构造查询失败: {exc}")
            return

        yield make_chunk(status="generating", subgraph_meta=subgraph.get("meta"))

        system_prompt = """你是一个基于【知识图谱】与【向量检索结果】进行联合推理的智能助手。

你将收到一个 JSON 对象，包含：
- 用户问题
- 知识图谱的裁剪子图
  - start_node_id
  - nodes（id, labels, props）
  - edges（id, source, target, type, props）
  - meta（kept_edge_count, total_edge_count, compress_ratio）
- 知识库向量检索得到的摘要信息

【核心推理原则（重要）】
1. 推理权重分配为：
- 知识图谱推理占 70%
- 向量检索结果占 30%
即：结论应主要由图中实体与关系路径支撑，向量检索用于补充背景、解释或佐证。

2. 当图谱信息与向量检索信息出现不一致时：
- 以知识图谱中的实体关系与路径证据为优先依据
- 向量检索内容仅作为补充说明或弱证据，不得推翻图谱结论

【图谱推理要求】
- 将 nodes 视为实体，edges 视为实体之间的关系
- 优先关注：
  - 与 start_node_id 存在路径关联的节点与边
  - 与用户问题关键词高度相关的实体与关系
  - 推理时应体现实体之间的关系链，而非孤立节点

【向量检索使用要求】
- 用于补充以下内容：
  - 背景知识
  - 定义、概念解释
  - 图谱中未显式表达但与结论相关的常识性信息
- 不可作为主要因果或关系判断的唯一依据

【空图处理规则】
- 若子图为空或几乎不含有效关系：
  - 仍需基于向量检索结果进行总结性回答
  - 但需明确说明结论主要来源于向量检索，可信度相对有限

【回答要求】
- 使用自然语言给出融合后的结论
- 必要时简要说明推理过程（以关系路径为主）
- 可引用 props 中可读字段（如名称、标题、时间、类型等）
- 不要输出无意义的节点 ID 或边 ID
- 若图谱与向量信息仍不足以支持结论，必须明确说明：
  “根据当前提供的图谱与检索信息，无法确定答案”，不得编造

你的目标是：在图谱主导、向量补充的前提下，给出结构清晰、证据明确、可信度可控的综合结论。"""

        kb_results = refs.get("knowledge_base", {}).get("results", [])
        kb_summary_results = []
        for item in kb_results[:5]:
            if not isinstance(item, dict):
                continue
            entity = item.get("entity", {})
            metadata = entity.get("metadata") if isinstance(entity, dict) else {}
            file_info = item.get("file", {}) if isinstance(item.get("file"), dict) else {}
            kb_summary_results.append({
                "text": entity.get("text") if isinstance(entity, dict) else None,
                "title": metadata.get("title") if isinstance(metadata, dict) else None,
                "filename": file_info.get("filename"),
            })
        kb_summary = {
            "count": len(kb_results),
            "results": kb_summary_results,
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": modified_query},
        ]

        content = ""
        try:
            model_stream = await route_model_predict(messages, meta, stream=True)
            for delta in model_stream:
                content += delta.content or ""
                yield make_chunk(content=delta.content, status="loading")

            refs_summary = {
                "knowledge_base_count": len(refs.get("knowledge_base", {}).get("results", [])),
                "subgraph_edge_count": len((subgraph or {}).get("edges", [])),
            }
            yield make_chunk(
                status="finished",
                refs=refs_summary,
                subgraph=subgraph,
                answer=content,
            )
        except Exception as exc:
            logger.error(f"生成答案失败: {exc}, {traceback.format_exc()}")
            yield make_chunk(status="error", message=f"生成答案失败: {exc}")
            return

    return StreamingResponse(process_prune(), media_type='application/json')


@chat.post("/call")
async def call(query: str = Body(...), meta: dict = Body(None)):
    meta = meta or {}
    
    async def predict_async(query):
        # 使用协程池提交预测任务
        return await route_model_predict(query, meta)

    response = await predict_async(query)
    logger.debug({"query": query, "response": response.content})

    return {
        "response": response.content,
        "expected_model_provider": meta.get("expected_model_provider"),
        "expected_model_name": meta.get("expected_model_name"),
        "actual_model_provider": meta.get("actual_model_provider"),
        "actual_model_name": meta.get("actual_model_name"),
        "degraded": meta.get("degraded"),
        "route_reason": meta.get("route_reason"),
    }

@chat.get("/sessions")
async def list_sessions(
    user_id: int,
    limit: int = 50,
    offset: int = 0
):
    """获取用户的所有会话列表
    
    Args:
        user_id: 用户ID
        limit: 返回数量限制
        offset: 偏移量
        
    Returns:
        会话列表
    """
    try:
        sessions = await chat_session_manager.list_user_sessions(
            user_id=user_id,
            limit=limit,
            offset=offset
        )
        return {
            "success": True,
            "sessions": sessions,
            "total": len(sessions)
        }
    except Exception as e:
        logger.error(f"获取会话列表失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")

@chat.get("/sessions/{thread_id}")
async def get_session(
    thread_id: str,
    user_id: int,
    include_messages: bool = True
):
    """获取指定会话的详细信息
    
    Args:
        thread_id: 会话ID
        user_id: 用户ID
        include_messages: 是否包含消息列表
        
    Returns:
        会话详细信息
    """
    try:
        session = await chat_session_manager.get_session(
            session_id=thread_id,
            user_id=user_id,
            include_messages=include_messages
        )
        if not session:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        return {"success": True, "session": session}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取会话失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")

@chat.put("/sessions/{thread_id}")
async def update_session(
    thread_id: str,
    user_id: int = Body(...),
    title: str = Body(None),
    system_prompt: str = Body(None)
):
    """更新会话信息
    
    Args:
        thread_id: 会话ID
        user_id: 用户ID
        title: 新标题（可选）
        system_prompt: 新系统提示词（可选）
        
    Returns:
        更新结果
    """
    try:
        result = await chat_session_manager.update_session(
            session_id=thread_id,
            user_id=user_id,
            title=title,
            system_prompt=system_prompt
        )
        if not result:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        return {"success": True, "message": "会话更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新会话失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")

@chat.delete("/sessions/{thread_id}")
async def delete_session(
    thread_id: str,
    user_id: int,
    hard_delete: bool = False
):
    """删除指定会话
    
    Args:
        thread_id: 会话ID
        user_id: 用户ID
        hard_delete: 是否物理删除（默认软删除）
        
    Returns:
        删除结果
    """
    try:
        result = await chat_session_manager.delete_session(
            session_id=thread_id,
            user_id=user_id,
            hard_delete=hard_delete
        )
        if not result:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")
        return {"success": True, "message": "会话删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除会话失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")

@chat.delete("/sessions/batch")
async def delete_sessions_batch(
    user_id: int = Body(..., description="用户ID"),
    session_ids: list[str] = Body(..., description="会话ID列表"),
    hard_delete: bool = Body(False, description="是否物理删除（默认软删除）")
):
    """批量删除会话
    
    Args:
        user_id: 用户ID
        session_ids: 会话ID列表
        hard_delete: 是否物理删除（默认软删除）
        
    Returns:
        批量删除结果
    """
    # 验证会话ID列表
    if not session_ids:
        raise HTTPException(status_code=400, detail="会话ID列表不能为空")
    
    # 过滤掉无效的会话ID
    valid_session_ids = [sid for sid in session_ids if sid != "undefined" and sid]
    
    if not valid_session_ids:
        raise HTTPException(status_code=400, detail="没有有效的会话ID")
    
    try:
        result = await chat_session_manager.delete_sessions_batch(
            session_ids=valid_session_ids,
            user_id=user_id,
            hard_delete=hard_delete
        )
        return {
            "success": True,
            "message": f"批量删除完成: 成功 {result['success']}/{result['total']}",
            "details": result
        }
    except Exception as e:
        logger.error(f"批量删除会话失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")

@chat.get("/sessions/{thread_id}/messages")
async def get_session_messages(
    thread_id: str,
    user_id: int,
    limit: int = None
):
    """获取会话的消息历史
    
    Args:
        thread_id: 会话ID
        user_id: 用户ID
        limit: 限制返回消息数量（可选）
        
    Returns:
        消息列表
    """
    try:
        messages = await chat_session_manager.get_history(
            session_id=thread_id,
            user_id=user_id,
            limit=limit
        )
        return {
            "success": True,
            "messages": messages,
            "total": len(messages)
        }
    except Exception as e:
        logger.error(f"获取消息历史失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")

@chat.delete("/sessions/{thread_id}/messages/{message_id}")
async def delete_message(
    thread_id: str,
    message_id: int,
    user_id: int
):
    """删除指定消息
    
    Args:
        thread_id: 会话ID
        message_id: 消息ID
        user_id: 用户ID
        
    Returns:
        删除结果
    """
    try:
        result = await chat_session_manager.delete_message(
            message_id=message_id,
            session_id=thread_id,
            user_id=user_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="消息不存在或无权访问")
        return {"success": True, "message": "消息删除成功"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除消息失败: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")



@chat.get("/models")
async def get_chat_models(model_provider: str):
    """获取指定模型提供商的模型列表（动态）"""
    try:
        # 对于 OpenAI 和 Ollama，返回预定义的模型列表
        if model_provider == "openai":
            return {
                "models": [
                    "gpt-4o-mini",
                    "gpt-3.5-turbo"
                ]
            }
        elif model_provider == "ollama":
            # 尝试从 Ollama 服务获取已下载的模型列表
            try:
                import requests
                ollama_base = os.getenv("OLLAMA_API_BASE", "http://ollama:11434")
                response = requests.get(f"{ollama_base}/api/tags", timeout=5)
                if response.status_code == 200:
                    models_data = response.json()
                    model_names = [m["name"] for m in models_data.get("models", [])]
                    return {"models": model_names}
                else:
                    # 返回推荐模型列表
                    return {
                        "models": [
                            "llama3.1:8b",
                            "qwen2.5:7b",
                            "deepseek-r1:7b"
                        ]
                    }
            except:
                # 如果无法连接 Ollama，返回推荐模型列表
                return {
                    "models": [
                        "llama3.1:8b",
                        "qwen2.5:7b",
                        "deepseek-r1:7b"
                    ]
                }
        elif model_provider == "deepseek":
            return {
                "models": ["deepseek-chat"]
            }
        else:
            # 其他提供商，使用原有逻辑
            model = select_model(model_provider=model_provider)
            return {"models": model.get_models()}
    except Exception as e:
        logger.error(f"Error getting models for {model_provider}: {e}")
        raise HTTPException(status_code=500, detail="获取模型列表失败，请稍后重试")

@chat.post("/models/update")
async def update_chat_models(model_provider: str, model_names: list[str]):
    """更新指定模型提供商的模型列表"""
    config.model_names[model_provider]["models"] = model_names
    config._save_models_to_file()
    return {"models": config.model_names[model_provider]["models"]}



@chat.post("/hybrid-retrieval")
@limiter.limit("20/minute")
async def hybrid_retrieval(
        request: Request,
        query: str = Body(...),
        meta: dict = Body(None),
        history: list[dict] | None = Body(None),
        thread_id: str | None = Body(None),
        response_mode: str = Body("simple")):
    """五阶段混合检索接口 - 自动生成最终答案
    
    Args:
        query: 用户的输入查询文本
        meta: 包含请求元数据的字典，可以包含以下字段：
            - db_id: 数据库ID (必需)
            - use_hybrid_retrieval: 是否启用混合检索 (默认True)
            - vector_top_k: 向量检索返回结果数量 (默认20)
            - vector_distance_threshold: 向量相似度阈值 (默认0.6)
            - graph_hops: 图遍历跳数 (默认2)
            - RERANK_TOP_K: 重排序返回结果数量 (默认5)
            - use_web: 是否使用网络搜索 (默认False)
            - show_retrieval_info: 是否显示检索信息 (默认Flase)
            - system_prompt: 系统提示词 (可选)
            - model_provider: 模型提供商 (可选)
            - model_name: 模型名称 (可选)
        history: 对话历史记录列表
        thread_id: 对话线程ID
        response_mode: 响应模式 ('simple' 或 'full')，默认为 'simple'
        
    Returns:
        五阶段检索结果 + LLM生成的最终答案
    """
    meta = meta or {}
    
    # 强制启用混合检索
    meta["use_hybrid_retrieval"] = True
    
    # 设置默认参数
    defaults = {
        "vector_top_k": 20,
        "vector_distance_threshold": 0.6,
        "graph_hops": 2,
        "RERANK_TOP_K": 10,
        "use_web": False,
        "show_retrieval_info": False,
    }
    
    for key, value in defaults.items():
        if key not in meta:
            meta[key] = value
    
    # 检查必需参数
    if not meta.get("db_id"):
        raise HTTPException(status_code=400, detail="db_id is required for hybrid retrieval")
    
    logger.info(f"开始五阶段混合检索: {query}")
    logger.debug(f"检索参数: {meta}")
    
    try:
        # 使用协程池提交检索任务
        retrieval_result = await coroutine_pool.submit(
            asyncio.to_thread(retriever, query, history or [], meta)
        )
        modified_query, refs = retrieval_result
        
        # 构建详细的返回结果
        result = {
            "status": "success",
            "query": query,
            "modified_query_for_llm": modified_query, # 这是给LLM的完整prompt
            "meta": meta,
            "retrieval_results": {
                "entities": refs.get("entities", []),
                "knowledge_base": {
                    "count": len(refs.get("knowledge_base", {}).get("results", [])),
                    "results": refs.get("knowledge_base", {}).get("results", [])[:5]  # 限制返回数量用于预览
                },
                "graph_base": {
                    "count": len(refs.get("graph_base", {}).get("edges", [])),
                    "results": _limit_graph_results(refs.get("graph_base", {}), 5)
                },
                "web_search": {
                    "count": len(refs.get("web_search", {}).get("results", [])),
                    "results": refs.get("web_search", {}).get("results", [])[:3]  # 限制返回数量
                },
                # 新增：展示重排后的上下文
                "reranked_context": refs.get("reranked_context")
            }
        }
        
        logger.info(f"五阶段混合检索完成: 初始召回 "
                   f"文档{result['retrieval_results']['knowledge_base']['count']}个, "
                   f"图关系{result['retrieval_results']['graph_base']['count']}个. "
                   f"最终用于生成答案的重排后上下文片段数量: {len(refs.get('reranked_context', '').split('[重排结果')) - 1}个")
        
        # 使用LLM生成最终答案
        try:
            logger.info("开始生成最终答案...")
            
            # 选择模型
            # 构建消息列表
            messages = []
            
            # 添加系统提示词
            system_prompt = meta.get("system_prompt", 
                "你是一个专业的威胁情报分析师。请严格基于提供的上下文信息回答问题。"
                "你的回答必须具备溯源性，优先使用得分高的信息。"
                "如果信息之间存在矛盾，请指出矛盾点。"
                "如果提供的上下文不足以回答问题，请直接说明信息不足。"
            )
            messages.append({"role": "system", "content": system_prompt})
            
            # 添加历史对话
            if history:
                for msg in history[-5:]:  # 限制最近5轮对话
                    if isinstance(msg, dict) and "role" in msg and "content" in msg:
                        messages.append(msg)
            
            # 构建包含检索结果的用户消息
            # 核心变更：直接使用retriever返回的、已经包含上下文的`modified_query`
            messages.append({"role": "user", "content": modified_query})
            
            # 使用协程池提交模型预测任务
            model_response = await route_model_predict(messages, meta)
            
            # 添加生成的答案到结果中
            result["generated_answer"] = {
                "content": model_response.content,
                "model_name": meta.get("actual_model_name"),
                "model_provider": meta.get("actual_model_provider"),
                "expected_model_name": meta.get("expected_model_name"),
                "expected_model_provider": meta.get("expected_model_provider"),
                "degraded": meta.get("degraded"),
                "route_reason": meta.get("route_reason"),
            }
            
            logger.info("最终答案生成完成")
            
        except Exception as e:
            logger.error(f"生成答案失败: {e}, {traceback.format_exc()}")
            result["generated_answer"] = {
                "error": f"生成答案失败: {str(e)}",
                "content": None
            }
        
        # 根据响应模式决定返回内容
        if response_mode == "simple":
            # 精简模式：只返回最重要的信息
            simple_result = {
                "status": result.get("status"),
                "query": result.get("query"),
                "generated_answer": result.get("generated_answer")
            }
            # 添加一个摘要，说明检索到了多少信息
            if "retrieval_results" in result:
                simple_result["retrieval_summary"] = (
                    f"召回实体 {len(result['retrieval_results']['entities'])} 个, "
                    f"文档 {result['retrieval_results']['knowledge_base']['count']} 个, "
                    f"图关系 {result['retrieval_results']['graph_base']['count']} 个. "
                    f"Reranker精选了 {len(refs.get('reranked_context', '').split('[重排结果')) - 1} 条信息用于生成答案。"
                )
            return simple_result
        
        # 默认返回完整结果
        return result
        
    except Exception as e:
        logger.error(f"五阶段混合检索失败: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="混合检索失败，请稍后重试")

def _limit_graph_results(graph_results, limit):
    """安全地限制图检索结果数量"""
    if not graph_results:
        return []
    
    # 如果结果是列表，直接切片
    if isinstance(graph_results, list):
        return graph_results[:limit]
    
    # 如果结果是字典，处理不同的结构
    if isinstance(graph_results, dict):
        # 如果包含edges，限制edges数量
        if "edges" in graph_results:
            limited_results = graph_results.copy()
            if isinstance(graph_results["edges"], list):
                limited_results["edges"] = graph_results["edges"][:limit]
            return limited_results
        
        # 如果包含nodes，限制nodes数量
        if "nodes" in graph_results:
            limited_results = graph_results.copy()
            if isinstance(graph_results["nodes"], list):
                limited_results["nodes"] = graph_results["nodes"][:limit]
            return limited_results
        
        # 其他情况，返回原结果
        return graph_results
    
    # 其他类型，返回空列表
    return []
