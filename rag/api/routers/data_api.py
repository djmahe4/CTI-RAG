import os
import asyncio
import traceback
from typing import List, Optional
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Body, Form, Query
import shutil
import uuid
import json
from fastapi.responses import JSONResponse
from rag.cache.redis_session import RedisSessionManager

from packages.utils import logger, hashstr
from packages import config
from packages import executor, retriever, knowledge_base, graph_base
from packages.core.graph_indexer import graph_indexer

data = APIRouter(prefix="/data")

# Task status in Redis
_redis_task_manager = RedisSessionManager(
    redis_url=os.getenv("REDIS_URL", "redis:6379"),
    expire_time=int(os.getenv("TASK_EXPIRE_TIME", "86400"))  # Keep task status 1 day
)


@data.get("/")
async def get_databases():
    try:
        database = knowledge_base.get_databases()
    except Exception as e:
        logger.error(f"Failed to fetch database list {e}, {traceback.format_exc()}")
        return {"message": "Failed to fetch database list，Please try again later.", "databases": []}
    return database


@data.post("/")
async def create_database(
    database_name: str = Body(...),
    description: str = Body(...),
    dimension: Optional[int] = Body(None),
    user_id: str = Body(...)  # Add user id parameter
):
    logger.debug(f"Create database {database_name}")
    try:
        database_info = knowledge_base.create_database(
            database_name,
            description,
            dimension=dimension,
            user_id=user_id
        )
    except Exception as e:
        logger.error(f"Failed to create database {e}, {traceback.format_exc()}")
        return {"message": "Failed to create database，Please try again later.", "status": "failed"}
    return database_info


@data.delete("/")
async def delete_database(db_id):
    logger.debug(f"Delete database {db_id}")
    knowledge_base.delete_database(db_id)
    return {"message": "Delete successful"}


@data.post("/query-test")
async def query_test(query: str = Body(...), meta: dict = Body(...)):
    logger.debug(f"Query test in {meta}: {query}")
    result = retriever.query_knowledgebase(
        query, history=None, refs={"meta": meta})
    return result


@data.post("/file-to-chunk")
async def file_to_chunk(files: List[str] = Body(...), params: dict = Body(...)):
    logger.debug(f"File to chunk: {files}")
    result = knowledge_base.file_to_chunk(files, params=params)
    return result


@data.post("/add-by-file")
async def create_document_by_file(db_id: str = Body(...), files: List[str] = Body(...)):
    logger.debug(f"Add document in {db_id} by file: {files}")
    try:
        # Time-consuming operation using a thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            executor,  # Use the same thread pool as chat router
            lambda: knowledge_base.add_files(db_id, files)
        )
        return {"message": "File Add Completed", "status": "success"}
    except Exception as e:
        logger.error(f"Failed to add file: {e}, {traceback.format_exc()}")
        return {"message": "Failed to add file，Please try again later.", "status": "failed"}


@data.post("/add-by-chunks")
async def add_by_chunks(db_id: str = Body(...), file_chunks: dict = Body(...)):
    """Renumber the breakout library as a walker：Return Now200 + task_id，Backstage in line."""
    task_id = str(uuid.uuid4())
    redis = await _redis_task_manager._get_redis()
    await redis.set(
        f"task:{task_id}",
        json.dumps({"status": "queued", "message": None}),
        ex=_redis_task_manager.expire_time
    )

    async def _worker():
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                executor,
                lambda: knowledge_base.add_chunks(db_id, file_chunks)
            )
            await redis.set(
                f"task:{task_id}",
                json.dumps({"status": "success", "message": "Block Add Completed"}),
                ex=_redis_task_manager.expire_time
            )
        except Exception as e:
            logger.error(f"Failed to add segment: {e}, {traceback.format_exc()}")
            await redis.set(
                f"task:{task_id}",
                json.dumps({"status": "failed", "message": str(e)}),
                ex=_redis_task_manager.expire_time
            )

    # Backstage.
    asyncio.create_task(_worker())

    return JSONResponse(status_code=200, content={"task_id": task_id, "status": "queued"})


@data.get("/task-status")
async def get_task_status(task_id: str):
    redis = await _redis_task_manager._get_redis()
    data = await redis.get(f"task:{task_id}")
    if not data:
        return {"task_id": task_id, "status": "not_found"}
    task = json.loads(data)
    return {"task_id": task_id, **task}


@data.get("/info")
async def get_database_info(db_id: str):
    # logger.debug(f"Get database {db_id} info")
    database = knowledge_base.get_database_info(db_id)
    return database


@data.delete("/document")
async def delete_document(db_id: str = Body(...), file_id: str = Body(...)):
    logger.debug(f"DELETE document {file_id} info in {db_id}")
    knowledge_base.delete_file(db_id, file_id)
    return {"message": "Delete successful"}


@data.get("/document")
async def get_document_info(db_id: str, file_id: str, page: int = 1, page_size: int = 10):
    logger.debug(f"GET document {file_id} info in {db_id}")

    try:
        # Basic data
        info = knowledge_base.get_file_info(db_id, file_id)

        # Page Break Parameter Verification
        page = max(1, int(page or 1))
        page_size = max(1, min(500, int(page_size or 10)))

        all_lines = info.get("lines", []) if isinstance(info, dict) else []
        total = len(all_lines)
        start = (page - 1) * page_size
        end = start + page_size
        paged_lines = all_lines[start:end]

        total_pages = (total + page_size - 1) // page_size if page_size else 1

        info = {
            "message": "success",
            "db_id": db_id,
            "file_id": file_id,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "lines": paged_lines,
        }
    except Exception as e:
        logger.error(
            f"Failed to get file info, {e}, {db_id=}, {file_id=}, {traceback.format_exc()}")
        info = {"message": "Failed to get file info", "status": "failed"}

    return info


@data.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db_id: Optional[str] = Query(None)
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No selected file")

    # Document type white list authentication
    ALLOWED_EXTENSIONS = {'.txt', '.pdf', '.docx', '.doc', '.md', '.csv', '.json', '.xml', '.html', '.htm'}
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

    basename, ext = os.path.splitext(file.filename)
    ext = ext.lower()

    # Verify File Extension
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}。Type of support: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Verify file size (by reading previous bytes of content)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File size exceeding limit: {MAX_FILE_SIZE // (1024*1024)}MB"
        )

    # Validation of document contents (detection of malicious document headers)
    malicious_headers = [b'<script', b'<?php', b'<!DOCTYPE html', b'\x00\x00']
    for header in malicious_headers:
        if content[:len(header)] == header:
            raise HTTPException(
                status_code=400,
                detail="Malicious document detected"
            )

    # Reset File Pointer
    await file.seek(0)

    # Get upload path according to db id, use default path if db id is None
    if db_id:
        upload_dir = knowledge_base.get_db_upload_path(db_id)
    else:
        upload_dir = os.path.join(config.save_dir, "data", "uploads")

    basename, ext = os.path.splitext(file.filename)
    filename = f"{basename}_{hashstr(basename, 4, with_salt=True)}{ext}".lower(
    )
    file_path = os.path.join(upload_dir, filename)
    os.makedirs(upload_dir, exist_ok=True)

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # Return file path, but use relative instead of absolute path to increase security
    relative_path = os.path.relpath(
        file_path, config.save_dir) if config.save_dir in file_path else filename
    return {"message": "File successfully uploaded", "file_path": relative_path, "db_id": db_id}


@data.get("/files")
async def get_files_list(db_id: str):
    """Get a list of all files in the specified database"""
    logger.debug(f"GET files list in database {db_id}")

    try:
        # Get File List
        files = knowledge_base.get_files_list(db_id)

        return {
            "message": "Fetching file list successfully",
            "status": "success",
            "db_id": db_id,
            "files": files,
            "total_count": len(files)
        }
    except Exception as e:
        logger.error(f"Failed to fetch file list: {e}, {traceback.format_exc()}")
        return {"message": "Failed to fetch file list，Please try again later.", "status": "failed", "files": []}


@data.delete("/file")
async def delete_file_by_id(db_id: str = Body(...), file_id: str = Body(...)):
    """Remove the specified file from the specified database"""
    logger.debug(f"DELETE file {file_id} from database {db_id}")

    try:
        # Check the database first.
        db = knowledge_base.get_kb_by_id(db_id)
        if db is None:
            return {"message": f"Database does not exist，db_id: {db_id}", "status": "failed"}

        # Get file information from file id
        file_info = knowledge_base.get_file_by_id(file_id)
        if file_info is None:
            return {"message": f"File does not exist，file_id: {file_id}", "status": "failed"}

        # Verify whether the file belongs to the specified data Library
        file_db_id = file_info.get("database_id")
        if file_db_id != db_id:
            return {
                "message": f"File does not belong to the specified database。File belongs to database: {file_db_id}，Database requested: {db_id}",
                "status": "failed"
            }

        # Execute Delete Operation
        knowledge_base.delete_file(db_id, file_id)

        return {
            "message": "File deleted successfully",
            "status": "success",
            "file_id": file_id,
            "db_id": db_id,
            "filename": file_info.get("filename", "Unknown")
        }
    except Exception as e:
        logger.error(f"Failed to delete file: {e}, {traceback.format_exc()}")
        return {"message": "Failed to delete file，Please try again later.", "status": "failed"}

# Search the knowledge base by user ID


@data.get("/user-knowledge-bases")
async def get_user_knowledge_bases(user_id: str):
    try:
        knowledge_bases = knowledge_base.get_user_knowledge_bases(user_id)
        return knowledge_bases
    except Exception as e:
        logger.error(f"Failed to acquire user knowledge base: {e}, {traceback.format_exc()}")
        return {"message": "Failed to acquire user knowledge base，Please try again later.", "status": "failed"}

# Delete the knowledge base from user ID


@data.delete("/user-knowledge-bases")
async def delete_user_knowledge_bases(user_id: str, db_id: str):
    """By UserIDand databaseIDRemove a single knowledge base"""
    try:
        result = knowledge_base.delete_user_database(user_id, db_id)
        return result
    except Exception as e:
        logger.error(f"Failed to remove user knowledge base: {e}, {traceback.format_exc()}")
        return {"message": "Failed to remove user knowledge base，Please try again later.", "status": "failed"}
