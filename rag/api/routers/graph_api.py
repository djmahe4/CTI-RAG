import os
import asyncio
import json
import traceback
from typing import List, Optional, Dict, Any, Union, Literal
from fastapi import APIRouter, Body, HTTPException, File, UploadFile, Form
import os
import json
import redis

from packages.utils import logger, hashstr
from packages import config
from packages import executor, retriever, knowledge_base, graph_base
from packages.core.graph_indexer import graph_indexer
from packages.core.kb_entity_service import kb_entity_service
from packages.core.entity_extractor import entity_extractor
from packages.core.constant import STIX_ENTITY_TYPES


graph = APIRouter(prefix="/graph")




# Use Redis for Enduring Tasks
_REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_TASK_KEY_PREFIX = "threatrag:graph_task:"
_TASK_TTL_SECONDS = 24 * 3600
redis_client = redis.Redis.from_url(_REDIS_URL, decode_responses=True)


def _task_key(task_id: str) -> str:
    return f"{_TASK_KEY_PREFIX}{task_id}"


def save_task(task_id: str, data: dict) -> None:
    redis_client.set(_task_key(task_id), json.dumps(data), ex=_TASK_TTL_SECONDS)


def load_task(task_id: str) -> dict | None:
    raw = redis_client.get(_task_key(task_id))
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def update_task(task_id: str, **fields) -> None:
    cur = load_task(task_id) or {}
    cur.update(fields)
    save_task(task_id, cur)


async def _run_extract_pipeline(task_id: str, tmp_path: str, language: str, entity_types: list[str] | None, kgdb_name: str):
    """Backstage Tasks：Parts -> Entity extraction -> Writing to Diagram Database -> Clear File"""
    update_task(task_id, status="running", progress=10)
    try:
        # 2) Segments (re-use knowledge base logic, not library)
        chunks_info = knowledge_base.file_to_chunk([tmp_path])
        first_key = next(iter(chunks_info.keys()))
        nodes = chunks_info[first_key]["nodes"]
        combined_text = " ".join([n["text"] for n in nodes]).strip()
        update_task(task_id, progress=40)

        # 3) Entity extraction
        extract_res = await entity_extractor.extract_entities(
            text=combined_text,
            language=language,
            entity_types=entity_types
        )
        if extract_res.get("status") != "success":
            update_task(task_id, status="failed", message=extract_res.get("message", "Entity withdrawal failed"))
            return
        entities = extract_res.get("entities", [])
        relationships = extract_res.get("relationships", [])
        update_task(task_id, progress=70)

        # 4) Save to Neo4j (optional)
        if config.enable_knowledge_graph and graph_base.is_running():
            await graph_base.add_entities_and_relationships(
                entities=entities,
                relationships=relationships,
                kgdb_name=kgdb_name
            )

        # Completed
        update_task(task_id, status="success", progress=100, result={
            "entities_count": len(entities),
            "relationships_count": len(relationships)
        })
    except Exception as e:
        logger.error(f"Could not close temporary folder: %s: {e}, {traceback.format_exc()}")
        update_task(task_id, status="failed", message=str(e))
    finally:
        # Clear temporary files
        try:
            os.remove(tmp_path)
        except Exception:
            pass

@graph.post("/start-indexer")
async def start_graph_indexer(interval: Optional[int] = Body(3600), 
                             batch_size: Optional[int] = Body(100),
                             kgdb_name: Optional[str] = Body("neo4j")):
    """Start Diagram Database Indexer"""
    if not config.enable_knowledge_graph:
        return {"message": "Knowledge map not enabled", "status": "failed"}
    
    if not graph_base.is_running():
        return {"message": "Map database not started", "status": "failed"}
    
    # Update indexer configuration
    graph_indexer.interval = interval
    graph_indexer.batch_size = batch_size
    graph_indexer.kgdb_name = kgdb_name
    
    # Start Indexer
    success = graph_indexer.start()
    if success:
        return {"message": f"Figure database indexer started，Scan interval: {interval}sec", "status": "success"}
    else:
        return {"message": "Database indexer startup failed", "status": "failed"}

@graph.post("/stop-indexer")
async def stop_graph_indexer():
    """Stop chart database indexer"""
    graph_indexer.stop()
    return {"message": "Figure database indexer stopped", "status": "success"}

@graph.get("/indexer-status")
async def get_graph_indexer_status():
    """Retrieving chart database indexer status"""
    return graph_indexer.get_status()

@graph.post("/run-indexer-now")
async def run_graph_indexer_now(batch_size: Optional[int] = Body(None), 
                               kgdb_name: Optional[str] = Body(None)):
    """Run an index immediately"""
    if not config.enable_knowledge_graph:
        return {"message": "Knowledge map not enabled", "status": "failed"}
    
    if not graph_base.is_running():
        return {"message": "Map database not started", "status": "failed"}
    
    # Temporary update of batch size and database name (if available)
    original_batch_size = graph_indexer.batch_size
    original_kgdb_name = graph_indexer.kgdb_name
    
    if batch_size is not None:
        graph_indexer.batch_size = batch_size
    if kgdb_name is not None:
        graph_indexer.kgdb_name = kgdb_name
    
    try:
        # Run Index
        indexed_count = graph_indexer._index_nodes()
        return {
            "message": f"Index completed，Total {indexed_count} Add embedded vector to each node", 
            "status": "success",
            "indexed_count": indexed_count
        }
    finally:
        # Restore original configuration
        graph_indexer.batch_size = original_batch_size
        graph_indexer.kgdb_name = original_kgdb_name


@graph.get("/info")
async def get_graph_info():
    graph_info = graph_base.get_graph_info()
    if graph_info is None:
        raise HTTPException(status_code=400, detail="Error Retrieving Figure Database")
    return graph_info

@graph.post("/index-nodes")
async def index_nodes(data: dict = Body(default={})):
    if not graph_base.is_running():
        raise HTTPException(status_code=400, detail="Map database not started")

    # Fetch parameters or use default values
    kgdb_name = data.get('kgdb_name', 'neo4j')

    # Call for the GramphDatabase add embeding to nodes method
    count = graph_base.add_embedding_to_nodes(kgdb_name=kgdb_name)

    return {"status": "success", "message": f"Successfully{count}Add embedded vector to each node", "indexed_count": count}

@graph.get("/node")
async def get_graph_node(entity_name: str):
    result = graph_base.query_node(entity_name=entity_name)
    return {"result": graph_base.format_query_result_to_graph(result), "message": "success"}

@graph.get("/nodes")
async def get_graph_nodes(kgdb_name: str, num: int):
    if not config.enable_knowledge_graph:
        raise HTTPException(status_code=400, detail="Knowledge graph is not enabled")

    logger.debug(f"Get graph nodes in {kgdb_name} with {num} nodes")
    result = graph_base.get_sample_nodes(kgdb_name, num)
    return {"result": graph_base.format_general_results(result), "message": "success"}


@graph.post("/delete-all")
async def delete_all_nodes_and_relationships(kgdb_name: str = Body("neo4j")):
    """Hazardous operation：Remove all nodes and relationships in the chart database"""
    if not config.enable_knowledge_graph:
        return {"status": "failed", "message": "Knowledge map not enabled"}
    if not graph_base.is_running():
        return {"status": "failed", "message": "Map database not started"}
    try:
        graph_base.delete_entity(entity_name=None, kgdb_name=kgdb_name)
        return {"status": "success", "message": f"Database {kgdb_name} All nodes and relationships have been deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@graph.post("/add-by-jsonl")
async def add_graph_entity(file_path: str = Body(...), kgdb_name: Optional[str] = Body(None)):
    if not config.enable_knowledge_graph:
        return {"message": "Knowledge map not enabled", "status": "failed"}

    if not file_path.endswith('.jsonl'):
        return {"message": "File format error，Please uploadjsonlDocumentation", "status": "failed"}

    try:
        await graph_base.jsonl_file_add_entity(file_path, kgdb_name)
        return {"message": "Entity Add Success", "status": "success"}
    except Exception as e:
        logger.error(f"Add Entity Failed: {e}, {traceback.format_exc()}")
        return {"message": f"Add Entity Failed: {e}", "status": "failed"}

@graph.post("/extract-entities-from-file")
async def extract_entities_from_file(
    file: UploadFile = File(...),
    language: str = Form("chinese"),
    entity_types: Optional[str] = Form(None),  # Comma-separated or JSON array string, empty to extract all STIX types
    kgdb_name: str = Form("neo4j")
):
    """Receive frontend upload files，Parts-Entity extraction-Save ToNeo4jWaterline interfaces"""
    try:
        # 1) Preservation of provisional documents
        basename, ext = os.path.splitext(file.filename or "uploaded.txt")
        tmp_dir = os.path.join(config.save_dir, "data", "tmp_uploads")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f"{basename}{ext}")
        with open(tmp_path, "wb") as f_out:
            f_out.write(await file.read())

        # 2) Segments (parts logic for reuse of knowledge base but not library)
        chunks_info = knowledge_base.file_to_chunk([tmp_path])
        # Take one.
        first_key = next(iter(chunks_info.keys()))
        nodes = chunks_info[first_key]["nodes"]
        combined_text = " ".join([n["text"] for n in nodes]).strip()

        # 3) Parsing Entity Type Parameters
        types_list: Optional[List[str]] = None
        if entity_types and entity_types.strip():
            try:
                # Compatible JSON array string
                parsed = json.loads(entity_types)
                if isinstance(parsed, list):
                    types_list = [str(t) for t in parsed]
            except Exception:
                # Comma-compatible separation
                types_list = [t.strip() for t in entity_types.split(",") if t.strip()]
        
        # Use all available STIX entities if no designated entity type
        if not types_list:
            types_list = list(STIX_ENTITY_TYPES.keys())

        # 4) Entity withdrawals
        extract_res = await entity_extractor.extract_entities(
            text=combined_text,
            language=language,
            entity_types=types_list
        )
        if extract_res.get("status") != "success":
            return {"message": extract_res.get("message", "Entity withdrawal failed"), "status": "failed"}

        entities = extract_res.get("entities", [])
        relationships = extract_res.get("relationships", [])

        # 5) Save to Neo4j
        if not config.enable_knowledge_graph:
            return {"message": "Knowledge map not enabled", "status": "failed"}
        if not graph_base.is_running():
            return {"message": "Map database not started，Could not initialise Bonobo", "status": "failed"}

        await graph_base.add_entities_and_relationships(
            entities=entities,
            relationships=relationships,
            kgdb_name=kgdb_name
        )

        # 6) Clean-up of temporary documents
        try:
            os.remove(tmp_path)
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Entity extraction completed and saved toNeo4j ({kgdb_name})",
            "entities_count": len(entities),
            "relationships_count": len(relationships)
        }
    except Exception as e:
        logger.error(f"Entity withdrawal failed: {e}, {traceback.format_exc()}")
        return {"message": f"Entity withdrawal failed: {e}", "status": "failed"}


@graph.post("/extract-entities-task")
async def submit_extract_entities_task(
    file: UploadFile = File(...),
    language: str = Form("chinese"),
    entity_types: Optional[str] = Form(None),
    kgdb_name: str = Form("neo4j"),
):
    """Drawing tasks from submitting entities，Return Now task_id，Backstage processing"""
    try:
        # Save temporary files
        basename, ext = os.path.splitext(file.filename or "uploaded.txt")
        tmp_dir = os.path.join(config.save_dir, "data", "tmp_uploads")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_path = os.path.join(tmp_dir, f"{basename}{ext}")
        with open(tmp_path, "wb") as f_out:
            f_out.write(await file.read())

        # Parsing entity type parameters
        types_list: Optional[list[str]] = None
        if entity_types and entity_types.strip():
            try:
                parsed = json.loads(entity_types)
                if isinstance(parsed, list):
                    types_list = [str(t) for t in parsed]
            except Exception:
                types_list = [t.strip() for t in entity_types.split(",") if t.strip()]

        # Create Task
        import uuid
        task_id = str(uuid.uuid4())
        save_task(task_id, {"status": "pending", "progress": 0, "message": "queued"})

        # Step on backstage.
        asyncio.create_task(_run_extract_pipeline(task_id, tmp_path, language, types_list, kgdb_name))

        return {"task_id": task_id, "status": "queued"}
    except Exception as e:
        logger.error(f"Failed to extract task from submitting entity: {e}, {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@graph.get("/extract-entities-task/status")
async def get_extract_entities_task_status(task_id: str):
    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    return {"task_id": task_id, **task}


@graph.get("/extract-entities-task/result")
async def get_extract_entities_task_result(task_id: str):
    task = load_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.get("status") not in ("success", "failed"):
        return {"task_id": task_id, **task}
    return {"task_id": task_id, **task}