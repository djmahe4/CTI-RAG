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

# Load environment variables
load_dotenv()

# Create rate limiter
limiter = Limiter(key_func=get_remote_address)

# Create router
chat = APIRouter(prefix="/chat")

# Initialize Redis session manager
redis_session = RedisSessionManager(
    redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
    expire_time=int(os.getenv("SESSION_EXPIRE_TIME", "3600"))
)

# Initialize chat session manager (integrating MySQL and Redis)
chat_session_manager = get_chat_session_manager(redis_manager=redis_session)

# Initialize coroutine pool
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
    Only matches IPv4 as start node ID.
    Rules:
    1) If meta.start_node_id is a valid IPv4, return it directly.
    2) Search for IPv4 in the query (including explicit key-value pairs like start_node_id=1.2.3.4, or IPs in natural language).
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
    # Match visible key to format first
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

    # Semantic matching: first IPv4 appearing in the sentence
    if m := re.search(r"((?:\d{1,3}\.){3}\d{1,3})", text):
        ip = m.group(1)
        if _is_ipv4(ip):
            return ip

    return None

@chat.post("/sessions/create")
async def create_new_session(
    user_id: int = Body(..., description="User ID"),
    title: str = Body(None, description="Session title (optional)"),
    system_prompt: str = Body(None, description="System prompt (optional)")
):
    """Create a new chat session
    
    Args:
        user_id: User ID (required)
        title: Session title (optional, automatically generated if not provided)
        system_prompt: System prompt (optional)
        
    Returns:
        Newly created session information, including session_id
    """
    try:
        session_id = await chat_session_manager.create_session(
            user_id=user_id,
            title=title,
            system_prompt=system_prompt
        )
        
        logger.info(f"Session created successfully: session_id={session_id}, user_id={user_id}")
        
        return {
            "success": True,
            "session_id": session_id,
            "message": "Session created successfully"
        }
    except Exception as e:
        logger.error(f"Failed to create session: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session, please try again later")

@chat.post("/stream")
@limiter.limit("30/minute")
async def chat_post(
        request: Request,
        query: str = Body(..., description="User input query text"),
        user_id: int = Body(..., description="User ID (required)"),
        thread_id: str = Body(None, description="Session ID (optional, automatically created if not provided)"),
        meta: dict = Body(None, description="Request metadata")):
    """Chat within a session (streaming response)
    
    Args:
        query: User input query text (required)
        user_id: User ID (required)
        thread_id: Session ID (optional)
            - If provided: use existing session
            - If not provided: automatically create a new session
        meta: Dictionary containing request metadata, which can include:
            - title: Session title (used only when auto-creating)
            - system_prompt: System prompt (used only when auto-creating)
            - use_web: Whether to use web search
            - use_graph: Whether to use knowledge graph
            - db_id: Database ID
            - history_round: Limit on conversation history rounds
            - search_mode: Graph search mode (local/global/hybrid, default hybrid)
            - top_k: Limit on search results count (default 10)
            - threshold: Similarity threshold (default 0.7)
            - model_provider: Model provider (optional, e.g., "deepseek", "custom", etc.)
            - model_name: Model name (optional)
            
    Returns:
        StreamingResponse: Returns a streaming response
        
    Note:
        Recommended to use POST /chat/sessions/create first for better control
    """
    meta = meta or {}
    
    # Automatically create a new session if thread_id is not provided
    if not thread_id:
        try:
            thread_id = await chat_session_manager.create_session(
                user_id=user_id,
                title=meta.get("title"),
                system_prompt=meta.get("system_prompt")
            )
            logger.info(f"Automatically created new session: thread_id={thread_id}, user_id={user_id}")
        except Exception as e:
            logger.error(f"Failed to create session: {e}")
            raise HTTPException(status_code=500, detail="Failed to create session, please try again later")
    else:
        # Verify if a session exists and the user has access
        session = await chat_session_manager.get_session(
            session_id=thread_id,
            user_id=user_id,
            include_messages=False
        )
        
        if not session:
            logger.warning(f"Session does not exist or user has no access: thread_id={thread_id}, user_id={user_id}")
            raise HTTPException(
                status_code=404,
                detail="Session does not exist or no access"
            )
    
    # Retrieve history from database (Redis first, then MySQL)
    try:
        history = await chat_session_manager.get_history(
            session_id=thread_id,
            user_id=user_id
        )
        logger.debug(f"Retrieved session history: thread_id={thread_id}, message count={len(history)}")
    except Exception as e:
        logger.error(f"Failed to fetch session history: {e}")
        history = []
    
    # Initialize history manager
    history_manager = HistoryManager(history, system_prompt=meta.get("system_prompt"))
    logger.debug(f"Received query: {query} with meta: {meta}")
    
    # Ensure meta contains show_retrieval_info parameter, default to True
    if "show_retrieval_info" not in meta:
        meta["show_retrieval_info"] = True

    def make_chunk(content=None, **kwargs):
        return json.dumps({
            "response": content,
            "meta": meta,
            "thread_id": thread_id,  # returns theread id to client
            **kwargs
        }, ensure_ascii=False).encode('utf-8') + b"\n"

    def need_retrieve(meta):
        return meta.get("use_web") or meta.get("use_graph") or meta.get("db_id")

    async def process_chat():
        modified_query = query
        refs = None

        # Processing knowledge base retrieval
        if meta and need_retrieve(meta):
            yield make_chunk(status="searching")

            try:
                # Submit search tasks using a co-ordinated pool
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
        history_manager.add_user(query)  # Note: original query used here
        
        # Save user message to database (MySQL and Redis)
        try:
            await chat_session_manager.add_message(
                session_id=thread_id,
                role="user",
                content=query,
                user_id=user_id
            )
        except Exception as e:
            logger.error(f"Failed to save user message: {e}")

        content = ""
        reasoning_content = ""
        try:
            # Use a coroutine pool to submit model prediction tasks
            model_stream = await route_model_predict(messages, meta, stream=True)
            
            for delta in model_stream:
                if not delta.content and hasattr(delta, 'reasoning_content'):
                    reasoning_content += delta.reasoning_content or ""
                    chunk = make_chunk(reasoning_content=reasoning_content, status="reasoning")
                    yield chunk
                    continue

                # Special handling for ERNIE Bot (Wenxin Yiyan)
                if hasattr(delta, 'is_full') and delta.is_full:
                    content = delta.content
                else:
                    content += delta.content or ""

                chunk = make_chunk(content=delta.content, status="loading")
                yield chunk

            logger.debug(f"Final response: {content}")
            logger.debug(f"Final reasoning response: {reasoning_content}")
            
            # Save assistant reply back to database (both MySQL and Redis)
            try:
                await chat_session_manager.add_message(
                    session_id=thread_id,
                    role="assistant",
                    content=content,
                    user_id=user_id
                )
            except Exception as e:
                logger.error(f"Failed to save assistant reply: {e}")
                
            # Only refs summary information returned to avoid output of large amounts of data
            refs_summary = None
            if refs:
                refs_summary = {
                    "knowledge_base_count": len(refs.get("knowledge_base", {}).get("results", [])),
                    "graph_base_count": len(refs.get("graph_base", {}).get("results", [])),
                    "web_search_count": len(refs.get("web_search", {}).get("results", [])),
                    "entities": refs.get("entities", [])[:5]  # Only returned to the top five entities
                }
            
            yield make_chunk(status="finished",
                            history=history_manager.update_ai(content),
                            refs=refs_summary)
        except Exception as e:
            logger.error(f"Model error: {e}, {traceback.format_exc()}")
            yield make_chunk(message=f"Model error: {e}", status="error")
            return

    # Use StreamingResponse to return async generator
    return StreamingResponse(process_chat(), media_type='application/json')


@chat.post("/temporary")
@limiter.limit("60/minute")
async def temporary_chat(
        request: Request,
        query: str = Body(..., description="User input query text"),
        meta: dict = Body(None, description="Request metadata")):
    """
    Perform one-off temporary chat (streaming response) without database I/O or history.
    Mainly for functional testing and experiments.

    Args:
        query: User input query text (Required)
        meta: Dictionary containing request metadata, consistent with /chat/stream interface
            
    Returns:
        StreamingResponse: Returns a streaming response
    """
    meta = meta or {}
    # Hard-encoded list
    history = []

    # Initialization history manager (using empty temporary history)
    history_manager = HistoryManager(history, system_prompt=meta.get("system_prompt"))
    logger.debug(f"Temporary chat received query: {query} with meta: {meta}")
    
    # Ensure meta contains show retrieval info parameters, by default True
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
                # Submit search tasks using a co-ordinated pool
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
            # Use a co-ordinated pool to submit model prediction tasks
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
    query: str = Body(..., description="User input query text, must include start node identifier"),
    meta: dict | None = Body(None, description="Request metadata (optional, supports start_node_id, max_edges, return_mode)"),
):
    """
    Generate pruned subgraph based on offline subgraph pruning service, and combine retrieval results for model response.
    - No user/session ID required.
    - Start node ID is prioritized from meta.start_node_id, otherwise parsed from query (node_id=xxx / start_node_id=xxx / node=xxx).
    - Calls local pruning service on port 8013.
    """
    meta = meta or {}

    start_node_id = _match_start_node_id(query, meta)

    # Reuse retrieval logic: retrieve from knowledge base/graph/web as needed
    def make_chunk(content=None, **kwargs):
        return json.dumps({
            "response": content,
            "meta": meta,
            "start_node_id": start_node_id,
            **kwargs
        }, ensure_ascii=False).encode('utf-8') + b"\n"

    def need_retrieve(m):
        # Enable vector search only when db_id is provided. Web/graph not supported here.
        return bool(m.get("db_id"))

    async def process_prune():
        modified_query = query
        refs = {"knowledge_base": {"results": []}, "graph_base": {"results": []}}

        # Optional: Vector/chart search first
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

        # Call subgraph pruning service
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
                yield make_chunk(status="error", message="NOT_FOUND: Start node not in offline graph")
                return
            if resp.status_code == 500:
                yield make_chunk(status="error", message="MODEL_NOT_LOADED: Subgraph pruning model not loaded")
                return
            resp.raise_for_status()
            subgraph = resp.json()
        except requests.RequestException as exc:
            logger.error(f"Failed to call subgraph pruning service: {exc}")
            yield make_chunk(status="error", message=f"Failed to call subgraph pruning service: {exc}")
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
            logger.error(f"Failed to construct query: {exc}, {traceback.format_exc()}")
            yield make_chunk(status="error", message=f"Failed to construct query: {exc}")
            return

        yield make_chunk(status="generating", subgraph_meta=subgraph.get("meta"))

        system_prompt = """You are an intelligent assistant performing joint reasoning based on [Knowledge Graph] and [Vector Retrieval results].

You will receive a JSON object containing:
- User question
- Pruned subgraph from the Knowledge Graph
  - start_node_id
  - nodes (id, labels, props)
  - edges (id, source, target, type, props)
  - meta (kept_edge_count, total_edge_count, compress_ratio)
- Summary information from Knowledge Base vector retrieval

[Core Reasoning Principles (Important)]
1. Reasoning weight allocation:
- Knowledge Graph reasoning: 70%
- Vector Retrieval results: 30%
Conclusion should be primarily supported by entities and relationship paths in the graph, with vector retrieval used for supplementary background, explanation, or corroboration.

2. When discrepancies occur between graph and vector information:
- Prioritize entity relationships and path evidence in the Knowledge Graph.
- Vector retrieval content serves only as supplementary explanation or weak evidence and must not override graph conclusions.

[Graph Reasoning Requirements]
- Treat nodes as entities and edges as relationships between them.
- Focus on:
  - Nodes and edges path-linked to the start_node_id.
  - Entities and relationships highly relevant to user question keywords.
  - Reasoning should reflect relationship chains between entities, not isolated nodes.

[Vector Retrieval Usage]
- Used to supplement:
  - Background knowledge.
  - Definitions and concept explanations.
  - Commonsense information not explicitly expressed in the graph but relevant to the conclusion.
- Cannot be the sole basis for primary causal or relationship judgments.

[Empty Graph Rules]
- If the subgraph is empty or lacks valid relationships:
  - Still provide a summary answer based on vector retrieval results.
  - Clearly state that the conclusion primarily stems from vector retrieval, and credibility is relatively limited.

[Answer Requirements]
- Provide a synthesized conclusion in natural language.
- Briefly explain the reasoning process (primarily relationship paths) when necessary.
- Readable fields in props (e.g., name, title, time, type) can be cited.
- Do not output meaningless node IDs or edge IDs.
- If graph and vector information remains insufficient to support a conclusion, explicitly state:
  "Based on the provided graph and retrieval information, the answer cannot be determined." Do not hallucinate.

Your goal: Provide a clear, evidence-based, and credible synthesis dominated by graph reasoning and supplemented by vector information."""

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
            logger.error(f"Failed to generate answer: {exc}, {traceback.format_exc()}")
            yield make_chunk(status="error", message=f"Failed to generate answer: {exc}")
            return

    return StreamingResponse(process_prune(), media_type='application/json')


@chat.post("/call")
async def call(query: str = Body(...), meta: dict = Body(None)):
    meta = meta or {}
    
    async def predict_async(query):
        # Submission of forecast tasks using a co-ordinated pool
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
    """Get list of all sessions for a user
    
    Args:
        user_id: User ID
        limit: Result limit
        offset: Offset
        
    Returns:
        Session list
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
        logger.error(f"Failed to retrieve session list: {e}")
        raise HTTPException(status_code=500, detail="Internal server error, please try again later")

@chat.get("/sessions/{thread_id}")
async def get_session(
    thread_id: str,
    user_id: int,
    include_messages: bool = True
):
    """Get details of a specific session
    
    Args:
        thread_id: Session ID
        user_id: User ID
        include_messages: Whether to include message list
        
    Returns:
        Session details
    """
    try:
        session = await chat_session_manager.get_session(
            session_id=thread_id,
            user_id=user_id,
            include_messages=include_messages
        )
        if not session:
            raise HTTPException(status_code=404, detail="Session does not exist or no access")
        return {"success": True, "session": session}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retrieve session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error, please try again later")

@chat.put("/sessions/{thread_id}")
async def update_session(
    thread_id: str,
    user_id: int = Body(...),
    title: str = Body(None),
    system_prompt: str = Body(None)
):
    """Update session information
    
    Args:
        thread_id: Session ID
        user_id: User ID
        title: New title (optional)
        system_prompt: New system prompt (optional)
        
    Returns:
        Update result
    """
    try:
        result = await chat_session_manager.update_session(
            session_id=thread_id,
            user_id=user_id,
            title=title,
            system_prompt=system_prompt
        )
        if not result:
            raise HTTPException(status_code=404, detail="Session does not exist or no access")
        return {"success": True, "message": "Session updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error, please try again later")

@chat.delete("/sessions/{thread_id}")
async def delete_session(
    thread_id: str,
    user_id: int,
    hard_delete: bool = False
):
    """Delete specific session
    
    Args:
        thread_id: Session ID
        user_id: User ID
        hard_delete: Whether to delete physically (default soft delete)
        
    Returns:
        Delete result
    """
    try:
        result = await chat_session_manager.delete_session(
            session_id=thread_id,
            user_id=user_id,
            hard_delete=hard_delete
        )
        if not result:
            raise HTTPException(status_code=404, detail="Session does not exist or no access")
        return {"success": True, "message": "Session deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete session: {e}")
        raise HTTPException(status_code=500, detail="Internal server error, please try again later")

@chat.delete("/sessions/batch")
async def delete_sessions_batch(
    user_id: int = Body(..., description="UserID"),
    session_ids: list[str] = Body(..., description="SessionIDList"),
    hard_delete: bool = Body(False, description="Whether to physically delete（Default Soft Delete）")
):
    """Batch delete sessions
    
    Args:
        user_id: User ID
        session_ids: Session ID list
        hard_delete: Whether to delete physically (default soft delete)
        
    Returns:
        Batch delete result
    """
    # Validate session ID list
    if not session_ids:
        raise HTTPException(status_code=400, detail="Session ID list cannot be empty")
    
    # Filter out invalid session IDs
    valid_session_ids = [sid for sid in session_ids if sid != "undefined" and sid]
    
    if not valid_session_ids:
        raise HTTPException(status_code=400, detail="No valid session IDs")
    
    try:
        result = await chat_session_manager.delete_sessions_batch(
            session_ids=valid_session_ids,
            user_id=user_id,
            hard_delete=hard_delete
        )
        return {
            "success": True,
            "message": f"Batch delete completed: Success {result['success']}/{result['total']}",
            "details": result
        }
    except Exception as e:
        logger.error(f"Failed to batch delete sessions: {e}")
        raise HTTPException(status_code=500, detail="Internal server error, please try again later")

@chat.get("/sessions/{thread_id}/messages")
async def get_session_messages(
    thread_id: str,
    user_id: int,
    limit: int = None
):
    """Get message history for a session
    
    Args:
        thread_id: Session ID
        user_id: User ID
        limit: Limit message count (optional)
        
    Returns:
        Message list
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
        logger.error(f"Failed to retrieve message history: {e}")
        raise HTTPException(status_code=500, detail="Internal server error, please try again later")

@chat.delete("/sessions/{thread_id}/messages/{message_id}")
async def delete_message(
    thread_id: str,
    message_id: int,
    user_id: int
):
    """Delete specific message
    
    Args:
        thread_id: Session ID
        message_id: Message ID
        user_id: User ID
        
    Returns:
        Delete result
    """
    try:
        result = await chat_session_manager.delete_message(
            message_id=message_id,
            session_id=thread_id,
            user_id=user_id
        )
        if not result:
            raise HTTPException(status_code=404, detail="Message does not exist or no access")
        return {"success": True, "message": "Message deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")
        raise HTTPException(status_code=500, detail="Internal server error, please try again later")



@chat.get("/models")
async def get_chat_models(model_provider: str):
    """Get model list for specific provider (dynamic)"""
    try:
        # Return predefined model list for OpenAI and Ollama
        if model_provider == "openai":
            return {
                "models": [
                    "gpt-4o-mini",
                    "gpt-3.5-turbo"
                ]
            }
        elif model_provider == "ollama":
            # Attempt to get downloaded models from Ollama service
            try:
                import requests
                ollama_base = os.getenv("OLLAMA_API_BASE", "http://ollama:11434")
                response = requests.get(f"{ollama_base}/api/tags", timeout=5)
                if response.status_code == 200:
                    models_data = response.json()
                    model_names = [m["name"] for m in models_data.get("models", [])]
                    return {"models": model_names}
                else:
                    # Return recommended models
                    return {
                        "models": [
                            "llama3.1:8b",
                            "qwen2.5:7b",
                            "deepseek-r1:7b"
                        ]
                    }
            except:
                # Return recommended models if Ollama connection fails
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
            # Use existing logic for other providers
            model = select_model(model_provider=model_provider)
            return {"models": model.get_models()}
    except Exception as e:
        logger.error(f"Error getting models for {model_provider}: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve model list, please try again later")

@chat.post("/models/update")
async def update_chat_models(model_provider: str, model_names: list[str]):
    """Update model list for specific provider"""
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
    """Five-stage hybrid retrieval interface - automatically generate final answer
    
    Args:
        query: User input query text
        meta: Metadata dictionary including:
            - db_id: Database ID (required)
            - use_hybrid_retrieval: Enable hybrid retrieval (default True)
            - vector_top_k: Vector retrieval result count (default 20)
            - vector_distance_threshold: Vector distance threshold (default 0.6)
            - graph_hops: Graph hops (default 2)
            - RERANK_TOP_K: Rerank result count (default 5)
            - use_web: Use web search (default False)
            - show_retrieval_info: Show retrieval info (default False)
            - system_prompt: System prompt (optional)
            - model_provider: Model provider (optional)
            - model_name: Model name (optional)
        history: Conversation history list
        thread_id: Thread ID
        response_mode: Response mode ('simple' or 'full'), default 'simple'
        
    Returns:
        Five-stage retrieval results + LLM final answer
    """
    meta = meta or {}
    
    # Force enable hybrid retrieval
    meta["use_hybrid_retrieval"] = True
    
    # Set default parameters
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
    
    # Check required parameters
    if not meta.get("db_id"):
        raise HTTPException(status_code=400, detail="db_id is required for hybrid retrieval")
    
    logger.info(f"Starting five-stage hybrid retrieval: {query}")
    logger.debug(f"Retrieval parameters: {meta}")
    
    try:
        # Submit retrieval task using coroutine pool
        retrieval_result = await coroutine_pool.submit(
            asyncio.to_thread(retriever, query, history or [], meta)
        )
        modified_query, refs = retrieval_result
        
        # Build detailed response
        result = {
            "status": "success",
            "query": query,
            "modified_query_for_llm": modified_query, # This is the full prompt for LLM
            "meta": meta,
            "retrieval_results": {
                "entities": refs.get("entities", []),
                "knowledge_base": {
                    "count": len(refs.get("knowledge_base", {}).get("results", [])),
                    "results": refs.get("knowledge_base", {}).get("results", [])[:5]  # Limit count for preview
                },
                "graph_base": {
                    "count": len(refs.get("graph_base", {}).get("edges", [])),
                    "results": _limit_graph_results(refs.get("graph_base", {}), 5)
                },
                "web_search": {
                    "count": len(refs.get("web_search", {}).get("results", [])),
                    "results": refs.get("web_search", {}).get("results", [])[:3]  # Limit count
                },
                # NEW: Show reranked context
                "reranked_context": refs.get("reranked_context")
            }
        }
        
        logger.info(f"Five-stage hybrid retrieval completed: Initial recall "
                   f"Documents: {result['retrieval_results']['knowledge_base']['count']}, "
                   f"Graph relationships: {result['retrieval_results']['graph_base']['count']}. "
                   f"Final context snippets for answer: {len(refs.get('reranked_context', '').split('[Rerank result')) - 1}")
        
        # Generate final answer using LLM
        try:
            logger.info("Generating final answer...")
            
            # Select model
            # Build message list
            messages = []
            
            # Add system prompt
            system_prompt = meta.get("system_prompt", 
                "You are a professional Threat Intelligence Analyst. Please answer the question strictly based on the provided context."
                "Your answer must be traceable, prioritizing high-scoring information."
                "If there are contradictions between information sources, please point them out."
                "If the provided context is insufficient to answer the question, please state that explicitly."
            )
            messages.append({"role": "system", "content": system_prompt})
            
            # Add history
            if history:
                for msg in history[-5:]:  # Limit to last 5 rounds
                    if isinstance(msg, dict) and "role" in msg and "content" in msg:
                        messages.append(msg)
            
            # Build user message with retrieval results
            # CORE CHANGE: Use modified_query containing context from retriever
            messages.append({"role": "user", "content": modified_query})
            
            # Submit model prediction task using coroutine pool
            model_response = await route_model_predict(messages, meta)
            
            # Add generated answer to result
            result["generated_answer"] = {
                "content": model_response.content,
                "model_name": meta.get("actual_model_name"),
                "model_provider": meta.get("actual_model_provider"),
                "expected_model_name": meta.get("expected_model_name"),
                "expected_model_provider": meta.get("expected_model_provider"),
                "degraded": meta.get("degraded"),
                "route_reason": meta.get("route_reason"),
            }
            
            logger.info("Final answer generation completed")
            
        except Exception as e:
            logger.error(f"Failed to generate answer: {e}, {traceback.format_exc()}")
            result["generated_answer"] = {
                "error": f"Failed to generate answer: {str(e)}",
                "content": None
            }
        
        # Decide return content based on response mode
        if response_mode == "simple":
            # Simple mode: return most important info
            simple_result = {
                "status": result.get("status"),
                "query": result.get("query"),
                "generated_answer": result.get("generated_answer")
            }
            # Add summary of retrieval info
            if "retrieval_results" in result:
                simple_result["retrieval_summary"] = (
                    f"Recalled entities: {len(result['retrieval_results']['entities'])}, "
                    f"Documents: {result['retrieval_results']['knowledge_base']['count']}, "
                    f"Graph relationships: {result['retrieval_results']['graph_base']['count']}. "
                    f"Reranker selected {len(refs.get('reranked_context', '').split('[Rerank result')) - 1} snippets."
                )
            return simple_result
        
        # Default to full result
        return result
        
    except Exception as e:
        logger.error(f"Five-stage hybrid search failed: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail="Mixed Search Failed，Please try again later.")

def _limit_graph_results(graph_results, limit):
    """Securely limit the number of search results"""
    if not graph_results:
        return []
    
    # If the result is a list, just slice it.
    if isinstance(graph_results, list):
        return graph_results[:limit]
    
    # If the result is a dictionary, deal with different structures.
    if isinstance(graph_results, dict):
        # If you include eds, limit the number of eds.
        if "edges" in graph_results:
            limited_results = graph_results.copy()
            if isinstance(graph_results["edges"], list):
                limited_results["edges"] = graph_results["edges"][:limit]
            return limited_results
        
        # If nodes are included, limit the number of nodes
        if "nodes" in graph_results:
            limited_results = graph_results.copy()
            if isinstance(graph_results["nodes"], list):
                limited_results["nodes"] = graph_results["nodes"][:limit]
            return limited_results
        
        # Otherwise, return to the original result.
        return graph_results
    
    # Other types, return empty list
    return []
