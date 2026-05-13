import os
import json
import time
import traceback
import shutil
import re

from pymilvus import MilvusClient, MilvusException, DataType

from .. import config
from ..utils import logger, hashstr, QueryPreprocessor
from .indexing import chunk, read_text
from ..manager.kb_db_manager import kb_db_manager
from .migrate_kb_to_sqlite import migrate_json_to_sqlite
from .bm25_retriever import HybridRetriever


class KnowledgeBase:
    EMBED_MODEL_ALIASES = {
        "local/BAAI/bge-m3": "dashscope/text-embedding-v4",
    }

    def __init__(self) -> None:
        self.client = None
        self.work_dir = os.path.join(config.save_dir, "data")

        # Database Manager
        self.db_manager = kb_db_manager

        # Configuration
        self.default_distance_threshold = 0.5
        self.default_rerank_threshold = 0.1
        self.default_max_query_count = 20
        
        # Mixed Retrieval
        self.hybrid_retriever = HybridRetriever(
            vector_weight=0.7,  # Vector search weight
            bm25_weight=0.3      # BM25 weight
        )
        
        # Query Preprocessor
        self.query_preprocessor = QueryPreprocessor(enabled=True)

        # Check for need to move from JSON file to SQLite
        self._check_migration()

        self._load_models()

    @classmethod
    def _normalize_embed_model_name(cls, model_name):
        if not model_name:
            return model_name
        return cls.EMBED_MODEL_ALIASES.get(model_name, model_name)

    @classmethod
    def _is_embed_model_compatible(cls, lhs_model, rhs_model):
        return cls._normalize_embed_model_name(lhs_model) == cls._normalize_embed_model_name(rhs_model)

    def _check_migration(self):
        """Check if migration from JSON file to SQLite is required"""
        json_path = os.path.join(self.work_dir, "database.json")
        if os.path.exists(json_path):
            logger.info("Detected old JSON format knowledge base data. Preparing to migrate to SQLite...")
            try:
                result = migrate_json_to_sqlite()
                if result:
                    logger.info("Knowledge base data successfully migrated to SQLite")
                else:
                    logger.warning("Knowledge base data migration failed or was not required")
            except Exception as e:
                logger.error(f"Error during migration: {e}")

    def _load_models(self):
        """All models to restart"""
        if not config.enable_knowledge_base:
            return

        from ..models.embedding import get_embedding_model
        self.embed_model = get_embedding_model(config)

        if config.enable_reranker:
            from ..models.rerank_model import get_reranker
            self.reranker = get_reranker(config)

        if not self.connect_to_milvus():
            raise ConnectionError("Failed to connect to Milvus")

    def create_database(self, database_name, description, dimension=None, user_id=None):
        """Create a database"""
        dimension = dimension or self.embed_model.get_dimension()
        db_id = f"kb_{hashstr(database_name, with_salt=True)}"

        # Create database records
        db_dict = self.db_manager.create_database(
            db_id=db_id,
            name=database_name,
            description=description,
            embed_model=self.embed_model.embed_model_fullname,
            dimension=dimension,
            user_id=user_id
        )

        # Synchronising folder
        self._ensure_db_folders(db_id)

        # Create a collection in Milvus
        self.add_collection(db_id, dimension)

        return db_dict

    def _ensure_db_folders(self, db_id):
        """Ensure database folder exists"""
        db_folder = os.path.join(self.work_dir, db_id)
        uploads_folder = os.path.join(db_folder, "uploads")
        os.makedirs(db_folder, exist_ok=True)
        os.makedirs(uploads_folder, exist_ok=True)
        return db_folder, uploads_folder

    def get_db_upload_path(self, db_id=None):
        """Path to fetch upload folders，If not specifieddb_idUse default path"""
        _, uploads_folder = self._ensure_db_folders(db_id)
        return uploads_folder

    def get_databases(self):
        assert config.enable_knowledge_base, "Knowledge base not enabled"

        # Get all knowledge from the database Library
        databases = self.db_manager.get_all_databases()

        # Check and update Milvus information
        databases_with_milvus = []
        for db in databases:
            db_copy = db.copy()  # Create a copy of the dictionary to avoid modifying raw data
            # Update Milvus Pool Information
            try:
                milvus_info = self.get_collection_info(db["db_id"])
                db_copy["metadata"] = milvus_info
                # Logger.debug (f "Acquire the knowledge base {db['name']} (ID: {db['db id'}}) Milvus Info Success: {milvus info})
            except Exception as e:
                logger.warning(
                    f"Failed to retrieve Milvus information for knowledge base {db['name']} (ID: {db['db_id']}): {e}")
                # Add default Milvus status
                db_copy.update({
                    "row_count": 0,
                    "status": "Connection failed",
                    "error": str(e)
                })

            # Checking processed files
            processing_files = [f for f_id, f in db_copy.get("files", {}).items()
                                if f["status"] in ["processing", "waiting"]]
            if processing_files:
                logger.info(
                    f"Database {db['name']} Yes. {len(processing_files)} A file is being processed")

            databases_with_milvus.append(db_copy)

        return {"databases": databases_with_milvus}

    def get_database_info(self, db_id):
        # Add log log log ID query
        logger.info(f"Try to access database information，DatabaseID: {db_id}")

        db_dict = self.db_manager.get_database_by_id(db_id)
        if db_dict is None:
            logger.warning(f"Database does not exist，ID: {db_id}")
            # Returns a basic error message instead of a none to avoid a 404 error
            return {
                "db_id": db_id,
                "status": "error",
                "message": "Database does not exist or is not initialized",
                "exists": False
            }
        else:
            db_copy = db_dict.copy()
            try:
                milvus_info = self.get_collection_info(db_id)
                db_copy.update(milvus_info)
                db_copy["exists"] = True
            except Exception as e:
                logger.warning(f"Access to the knowledge base ID: {db_id} Yes.MilvusCan not open message: {e}")
                # Add a default Milvus status
                db_copy.update({
                    "row_count": 0,
                    "status": "Not connected",
                    "error": str(e),
                    "exists": True
                })
            return db_copy

    def get_database_id(self):
        databases = self.db_manager.get_all_databases()
        return [db["db_id"] for db in databases]

    def get_file_info(self, db_id, file_id):
        db = self.db_manager.get_database_by_id(db_id)
        if db is None:
            raise Exception(f"database not found, {db_id}")

        lines = self.client.query(
            collection_name=db_id,
            filter=f"file_id == '{file_id}'",
            output_fields=None
        )
        # Delete vector field
        for line in lines:
            line.pop("vector")

        lines.sort(key=lambda x: x.get("start_char_idx") or 0)
        return {"lines": lines}

    def get_files_list(self, db_id):
        """Can not open message"""
        db = self.db_manager.get_database_by_id(db_id)
        if db is None:
            raise Exception(f"database not found, {db_id}")

        return self.db_manager.get_files_by_database(db_id)

    def get_file_by_id(self, file_id):
        """By DocumentIDGet File Information"""
        return self.db_manager.get_file_by_id(file_id)

    def get_kb_by_id(self, db_id):
        if not config.enable_knowledge_base:
            return None

        return self.db_manager.get_database_by_id(db_id)

    def file_to_chunk(self, files, params=None):
        """Convert files to segments

        This is mainly about converting files to segments.，But not saved to data Library，Only return information after partition，Returning information also contains filesid，Filename，File type，File Path，File Status，File creation time etc.。
        files: list of file path
        params: params for chunking

        return: list of chunk info
        """
        file_infos = {}
        for file in files:
            file_id = "file_" + hashstr(file + str(time.time()))

            file_type = file.split(".")[-1].lower()

            # Convert a relative path (relative to config.save dir) to an absolute path for the frontend
            if os.path.isabs(file):
                abs_file_path = file
            else:
                abs_file_path = os.path.normpath(
                    os.path.join(config.save_dir, file))

            # Harmonize the use of the chunk function for all file types
            nodes = chunk(abs_file_path, params=params)

            # Add file information for each node to metadata
            for node in nodes:
                if not hasattr(node, 'metadata') or node.metadata is None:
                    node.metadata = {}
                
                # Add file information to metadata
                node.metadata.update({
                    "file_id": file_id,
                    "filename": os.path.basename(file),
                    "file_path": file,
                    "file_type": file_type,
                    "file_status": "waiting",
                    "file_created_at": int(time.time()),
                    "source_filename": os.path.basename(file),  # Maintain backward compatibility
                    "source_file_path": file  # Maintain backward compatibility
                })

            file_infos[file_id] = {
                "file_id": file_id,
                "filename": os.path.basename(file),
                "path": file,
                "type": file_type,
                "status": "waiting",
                "created_at": time.time(),
                "nodes": [node.dict() for node in nodes]
            }

        return file_infos

    def url_to_chunk(self, url, params=None):
        """WillurlConvert to Segment，ReadurlContents，and convert to a segment"""
        raise NotImplementedError("Not implemented")

    def add_chunks(self, db_id, file_chunks):
        """Add Segment"""
        db = self.get_kb_by_id(db_id)

        # Check if the database exists
        if db is None:
            logger.error(f"Database does not exist，db_id: {db_id}")
            return {"message": f"Database does not exist，db_id: {db_id}", "status": "failed"}

        # Check if embedded models match
        if not self._is_embed_model_compatible(db["embed_model"], self.embed_model.embed_model_fullname):
            logger.error(
                f"Embed model not match, {db['embed_model']} != {self.embed_model.embed_model_fullname}")
            return {"message": f"Embed model not match, cur: {self.embed_model.embed_model_fullname}, req: {db['embed_model']}", "status": "failed"}

        for file_id, chunk_info in file_chunks.items():
            # Create File Record in Database
            self.db_manager.add_file(
                db_id=db_id,
                file_id=file_id,
                filename=chunk_info["filename"],
                path=chunk_info["path"],
                file_type=chunk_info["type"],
                status="processing"
            )

            try:
                self.add_documents(
                    file_id=file_id,
                    collection_name=db_id,
                    docs=[node["text"] for node in chunk_info["nodes"]],
                    chunk_infos=chunk_info["nodes"])

                # Update file status complete
                self.db_manager.update_file_status(file_id, "done")

            except Exception as e:
                logger.error(
                    f"Failed to add documents to collection {db_id}, {e}, {traceback.format_exc()}")
                # Failed to update file status
                self.db_manager.update_file_status(file_id, "failed")

    def add_files(self, db_id, files, params=None):
        db = self.get_kb_by_id(db_id)

        # Check if the database exists
        if db is None:
            logger.error(f"Database does not exist，db_id: {db_id}")
            return {"message": f"Database does not exist，db_id: {db_id}", "status": "failed"}

        if not self.check_embed_model(db_id):
            logger.error(
                f"Embed model not match, {db['embed_model']} != {self.embed_model.embed_model_fullname}")
            return {"message": f"Embed model not match, cur: {self.embed_model.embed_model_fullname}, req: {db['embed_model']}", "status": "failed"}

        # Preprocessing the files to the queue
        new_files = self.file_to_chunk(files, params=params)

        for file_id, new_file in new_files.items():
            # Create File Record in Database
            self.db_manager.add_file(
                db_id=db_id,
                file_id=file_id,
                filename=new_file["filename"],
                path=new_file["path"],
                file_type=new_file["type"],
                status="processing"
            )

            try:
                self.add_documents(
                    file_id=file_id,
                    collection_name=db_id,
                    docs=[node["text"] for node in new_file["nodes"]],
                    chunk_infos=new_file["nodes"])

                # Update file status complete
                self.db_manager.update_file_status(file_id, "done")

            except Exception as e:
                logger.error(
                    f"Failed to add documents to collection {db_id}, {e}, {traceback.format_exc()}")
                # Failed to update file status
                self.db_manager.update_file_status(file_id, "failed")

    def delete_file(self, db_id, file_id):
        # Remove vector from Milvus
        self.client.delete(collection_name=db_id,
                           filter=f"file_id == '{file_id}'")

        # Remove file records from SQLite
        self.db_manager.delete_file(file_id)

    def delete_database(self, db_id):
        # Remove assembly from Milvus
        self.client.drop_collection(collection_name=db_id)

        # Remove database records from SQLite
        self.db_manager.delete_database(db_id)

        # Delete the corresponding folder for the database
        db_folder = os.path.join(self.work_dir, db_id)
        if os.path.exists(db_folder):
            shutil.rmtree(db_folder)

        return {"message": "Delete successful"}

    def restart(self):
        self._load_models()

    ###################################
    # * Below is the code for retriever #
    ###################################

    def query(self, query, db_id, **kwargs):

        distance_threshold = kwargs.get(
            "distance_threshold", self.default_distance_threshold)
        rerank_threshold = kwargs.get(
            "rerank_threshold", self.default_rerank_threshold)
        max_query_count = kwargs.get(
            "max_query_count", self.default_max_query_count)
        
        # Whether to use mixed search
        use_hybrid_retrieval = kwargs.get("use_hybrid_retrieval", True)
        
        # Whether to use metadata filtering
        use_metadata_filter = kwargs.get("use_metadata_filter", True)

        # Extra filter expression (supports callers to upload custom filters)
        filter_expression = kwargs.get("filter_expression")

        # Vector retrieval (support metadata filter + custom filter expression)
        all_db_result = self.search(
            query,
            db_id,
            limit=max_query_count,
            use_metadata_filter=use_metadata_filter,
            filter_expression=filter_expression,
        )
        all_db_result = [dict(r) for r in all_db_result]

        # Fetch file information and add it to the result
        for res in all_db_result:
            file = self.db_manager.get_file_by_id(res["entity"]["file_id"])
            if file:
                res["file"] = file

        db_result = [r for r in all_db_result if r["distance"]
                     > distance_threshold]

        # Mixed search: combined vector search and BM25
        if use_hybrid_retrieval and len(db_result) > 0:
            try:
                # Prepare BM25 training data.
                documents = [r["entity"]["text"] for r in db_result]
                document_ids = [r["entity"]["file_id"] for r in db_result]
                
                # Training BM25 models
                self.hybrid_retriever.fit_bm25(documents, document_ids)
                
                # Get vector fractions
                vector_scores = [r["distance"] for r in db_result]
                
                # Perform Mixed Search
                hybrid_results = self.hybrid_retriever.hybrid_search(
                    query, db_result, vector_scores, top_k=len(db_result)
                )
                
                # Use mixed search results
                db_result = hybrid_results
                logger.info(f"Mixed search complete，Number of outcomes: {len(db_result)}")
                
            except Exception as e:
                logger.warning(f"Mixed Search Failed，Use vector search: {e}")
                # If mixed search fails, continue using vector search results

        # Reorder (if enabled)
        if config.enable_reranker and len(db_result) > 0 and self.reranker:
            logger.debug(f"Start reordering，Number of original results: {len(db_result)}")
            texts = [r["entity"]["text"] for r in db_result]
            # Fix reranker input format: FlagReranker needs format[[query, text1], [query, text2], ...]
            query_text_pairs = [[query, text] for text in texts]
            rerank_scores = self.reranker.compute_score(
                query_text_pairs, normalize=False)
            for i, r in enumerate(db_result):
                r["rerank_score"] = rerank_scores[i]
            db_result.sort(key=lambda x: x["rerank_score"], reverse=True)
            db_result = [
                _res for _res in db_result if _res["rerank_score"] > rerank_threshold]
            logger.debug(f"Reorder finished，Number of filtered results: {len(db_result)}")
        elif config.enable_reranker and len(db_result) > 0 and not self.reranker:
            logger.warning("Reorder enabled but not initialized by the reorderer")
        elif not config.enable_reranker:
            logger.debug("Reordering not enabled")

        if kwargs.get("top_k", None):
            db_result = db_result[:kwargs["top_k"]]

        return {
            "results": db_result,
            "all_results": all_db_result,
            "message": "Query successful"
        }

    def get_retriever_by_db_id(self, db_id):
        retriever_params = {
            "distance_threshold": self.default_distance_threshold,
            "rerank_threshold": self.default_rerank_threshold,
            "max_query_count": self.default_max_query_count,
            "top_k": 10,
        }

        def retriever(query):
            response = self.query(query, db_id, **retriever_params)
            return response["results"]

        return retriever

    def get_retrievers(self):
        retrievers = {}
        for db in self.db_manager.get_all_databases():
            if self.check_embed_model(db["db_id"]):
                retrievers[db["db_id"]] = {
                    "name": db["name"],
                    "description": db["description"],
                    "retriever": self.get_retriever_by_db_id(db["db_id"]),
                    "embed_model": db["embed_model"],
                }
            else:
                logger.warning((
                    f"Cannot put knowledge base {db['name']} Convert to Tools, Because vector models don't match.，"
                    f"Current Vector Model: {self.embed_model.embed_model_fullname}，"
                    f"Knowledge Base Vector Model: {db['embed_model']}。"
                ))
        return retrievers

    ################################
    # * Below is the code for milvus #
    ################################
    def connect_to_milvus(self):
        """
        Connect to Milvus Services。
        Use standard Milvus Connection。
        """
        try:
            # Get Milvus Configuration
            milvus_config = config.get('milvus', {})
            host = milvus_config.get('host', '127.0.0.1')
            port = milvus_config.get('port', 19530)

            # Use standard connection
            uri = f"http://{host}:{port}"
            self.client = MilvusClient(uri=uri)

            # Test Connection
            self.client.list_collections()
            logger.info(f"Successfully connected to Milvus at {uri}")
            return True
        except MilvusException as e:
            logger.error(f"Failed to connect to Milvus: {e}")
            return False

    def get_collection_names(self):
        return self.client.list_collections()

    def get_collections(self):
        collections_name = self.client.list_collections()
        collections = []
        for collection_name in collections_name:
            collection = self.get_collection_info(collection_name)
            collections.append(collection)

        return collections

    def get_collection_info(self, collection_name):
        """AccessMilvusCan not open message，Deal with possible errors"""
        try:
            collection = self.client.describe_collection(collection_name)
            collection.update(
                self.client.get_collection_stats(collection_name))
            return collection
        except MilvusException as e:
            logger.warning(f"Get in the pool. {collection_name} Can not open message: {e}")
            # Returns a basic structure with false information
            return {
                "name": collection_name,
                "row_count": 0,
                "status": "Error",
                "error_message": str(e)
            }

    def add_collection(self, collection_name, dimension=None):
        if self.client.has_collection(collection_name=collection_name):
            logger.warning(
                f"Collection {collection_name} already exists, drop it")
            self.client.drop_collection(collection_name=collection_name)

        # Define schema (dynamic field + static field) using create schema visible
        schema = self.client.create_schema(
            auto_id=False,
            enable_dynamic_field=True,
        )
        # Main key and vector field
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dimension)
        # Static Assisted Filter Fields
        schema.add_field(field_name="source_filename", datatype=DataType.VARCHAR, max_length=1024)
        schema.add_field(field_name="date_key", datatype=DataType.VARCHAR, max_length=8)
        schema.add_field(field_name="file_type", datatype=DataType.VARCHAR, max_length=16)
        schema.add_field(field_name="file_created_at", datatype=DataType.INT64)

        self.client.create_collection(
            collection_name=collection_name,
            schema=schema,
        )

        # Create Index (if needed)
        try:
            # Check for index
            index_info = self.client.list_indexes(
                collection_name=collection_name)
            if not index_info:
                # Build index using IndexParams for MilvusClit
                index_params = self.client.prepare_index_params()
                index_params.add_index(
                    field_name="vector",
                    index_type="AUTOINDEX",
                    metric_type="COSINE",
                )
                self.client.create_index(
                    collection_name=collection_name,
                    index_params=index_params,
                )
                logger.info(f"Index created for collection {collection_name}")
        except Exception as e:
            logger.warning(
                f"Failed to create index for collection {collection_name}: {e}")

        # Load to memory immediately after creating a collection Medium
        try:
            self.client.load_collection(collection_name=collection_name)
            logger.info(
                f"Collection {collection_name} created and loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load collection {collection_name}: {e}")
            raise

    def ensure_collection_loaded(self, collection_name):
        """Make sure the collection is loaded to memory Medium"""
        try:
            # Check if the collection exists.
            if not self.client.has_collection(collection_name=collection_name):
                logger.error(f"Collection {collection_name} does not exist")
                return False

            # Check for index, create if not
            try:
                index_info = self.client.list_indexes(
                    collection_name=collection_name)
                if not index_info:
                    logger.info(
                        f"Collection {collection_name} has no index, creating one...")
                    # Create vector index
                    index_params = {
                        "index_type": "AUTOINDEX",
                        "metric_type": "COSINE",
                    }
                    self.client.create_index(
                        collection_name=collection_name,
                        field_name="vector",
                        index_params=index_params
                    )
                    logger.info(
                        f"Index created for collection {collection_name}")
            except Exception as index_e:
                logger.warning(
                    f"Failed to check/create index for collection {collection_name}: {index_e}")

            # Try loading the assembly (if loaded, this operation is secure)
            self.client.load_collection(collection_name=collection_name)
            logger.debug(f"Collection {collection_name} is loaded and ready")
            return True

        except Exception as e:
            logger.error(
                f"Failed to ensure collection {collection_name} is loaded: {e}")
            return False

    def add_documents(self, docs, collection_name, chunk_infos=None, file_id=None, **kwargs):
        """Add text after already split"""
        # Checking for Collaction
        import random
        if not self.client.has_collection(collection_name=collection_name):
            logger.error(f"Collection {collection_name} not found, create it")
            # self.add_collection(collection_name)
        else:
            # Ensure assembly loaded
            self.ensure_collection_loaded(collection_name)

        chunk_infos = chunk_infos or [{}] * len(docs)

        vectors = self.embed_model.batch_encode(docs)

        data = []
        for i in range(len(vectors)):
            node_info = chunk_infos[i] if i < len(chunk_infos) else {}
            node_meta = node_info.get("metadata", {}) if isinstance(node_info, dict) else {}

            # Extract static fields from node metadata
            # Rips the unified date key (date key)
            date_key = ""  # Default is an empty string, avoiding Milvus insertion of Noe value
            filename_for_parse = node_meta.get("source_filename") or node_meta.get("filename")
            if filename_for_parse:
                date_match = re.search(r'(\d{8})', filename_for_parse)
                if date_match:
                    date_key = date_match.group(1)
            
            static_source_filename = node_meta.get("source_filename") or node_meta.get("filename") or ""
            static_file_type = node_meta.get("file_type") or ""
            static_file_created_at = node_meta.get("file_created_at")
            if isinstance(static_file_created_at, float):
                static_file_created_at = int(static_file_created_at)

            # Merge all metadata, highest metadata priority in chunk infos
            metadata = {
                "id": int(random.random() * 1e12),
                "vector": vectors[i],
                "text": docs[i],
                "hash": hashstr(docs[i], with_salt=True),
                "file_id": file_id,
                "source_filename": static_source_filename,
                "date_key": date_key,
                "file_type": static_file_type,
                "file_created_at": static_file_created_at if static_file_created_at is not None else int(time.time()),
                **kwargs,      # Basic parameters
                **node_info    # Keep original node information (dynamic field)
            }
            data.append(metadata)

        res = self.client.insert(collection_name=collection_name, data=data)
        return res

    def search(self, query, collection_name, limit=3, use_metadata_filter=True, filter_expression=None):
        """Search Database"""
        query_vectors = self.embed_model.batch_encode([query])
        
        # Extracting metadata filter conditions
        metadata_filter = None
        if use_metadata_filter and hasattr(self, 'query_preprocessor') and self.query_preprocessor.enabled:
            filters = self.query_preprocessor.extract_metadata_filters(query)
            metadata_filter = self.query_preprocessor.build_milvus_filter(filters)
            if metadata_filter:
                logger.info(f"Apply metadata filtering: {metadata_filter}")
        
        # Merge Caller Custom Filter
        final_filter = None
        if metadata_filter and filter_expression:
            final_filter = f"({metadata_filter}) and ({filter_expression})"
        else:
            final_filter = metadata_filter or filter_expression
        
        return self.search_by_vector(query_vectors[0], collection_name, limit, final_filter)

    def search_by_vector(self, vector, collection_name, limit=3, filter_expression=None):
        # Ensure assembly loaded
        if not self.ensure_collection_loaded(collection_name):
            raise Exception(
                f"Collection {collection_name} is not available for search")

        # Build search parameters
        search_params = {
            "collection_name": collection_name,
            "data": [vector],
            "limit": limit,
            "output_fields": ["text", "file_id", "source_filename", "date_key", "file_type", "file_created_at", "vector"]
        }
        
        # Add Filter Condition
        if filter_expression:
            search_params["filter"] = filter_expression
            logger.info(f"Use filter conditions: {filter_expression}")

        res = self.client.search(**search_params)
        return res[0]

    def examples(self, collection_name, limit=20):
        # Ensure assembly loaded
        if not self.ensure_collection_loaded(collection_name):
            raise Exception(
                f"Collection {collection_name} is not available for query")

        res = self.client.query(
            collection_name=collection_name,
            limit=limit,
            output_fields=["id", "text", "vector"],
        )
        return res

    def search_by_id(self, collection_name, id, output_fields=["id", "text", "vector"]):
        # Ensure assembly loaded
        if not self.ensure_collection_loaded(collection_name):
            raise Exception(
                f"Collection {collection_name} is not available for search")

        res = self.client.get(collection_name, id, output_fields=output_fields)
        return res

    def check_embed_model(self, db_id):
        db = self.db_manager.get_database_by_id(db_id)
        if db is None:
            logger.warning(f"Database does not exist，Could not check embedded model match，db_id: {db_id}")
            return False
        return self._is_embed_model_compatible(db["embed_model"], self.embed_model.embed_model_fullname)

    def get_user_knowledge_bases(self, user_id):
        logger.info(f"Get Users {user_id} Knowledge base")
        return self.db_manager.get_user_knowledge_bases(user_id)

    def delete_user_knowledge_bases(self, user_id):
        logger.info(f"Remove User {user_id} Knowledge base")
        databases = self.db_manager.get_user_knowledge_bases(user_id)
        for db in databases:
            self.client.drop_collection(collection_name=db["db_id"])
        return self.db_manager.delete_user_knowledge_bases(user_id)
    
    def delete_user_database(self, user_id: str, db_id: str):
        """By UserIDand databaseIDRemove a single knowledge base"""
        logger.info(f"By User {user_id} and database {db_id} Remove knowledge base")
        # Verify database existence
        db = self.db_manager.get_database_by_id(db_id)
        if db is None:
            return {"message": f"Database does not exist，db_id: {db_id}", "status": "failed"}
        
        # Verify to User
        owner_user_id = db.get("user_id") if isinstance(db, dict) else None
        if owner_user_id and owner_user_id != user_id:
            return {"message": f"Database does not belong to the user，owner: {owner_user_id}", "status": "failed"}
        
        # Remove Milvus Pool
        try:
            if self.client.has_collection(collection_name=db_id):
                self.client.drop_collection(collection_name=db_id)
        except Exception as e:
            logger.warning(f"Remove Pool {db_id} Failed or non-existent: {e}")
        
        # Delete database records
        try:
            self.db_manager.delete_database(db_id)
        except Exception as e:
            logger.error(f"Failed to delete database record: {e}")
            return {"message": f"Failed to delete database record: {e}", "status": "failed"}
        
        # Delete the corresponding folder for the database
        try:
            db_folder = os.path.join(self.work_dir, db_id)
            if os.path.exists(db_folder):
                shutil.rmtree(db_folder)
        except Exception as e:
            logger.warning(f"Failed to delete database folder: {e}")
        
        return {"message": "Delete successful", "status": "success"}
    
    def configure_hybrid_retrieval(self, vector_weight: float = 0.7, bm25_weight: float = 0.3):
        """
        Configure mixed search weights
        
        Args:
            vector_weight: Vector search weight (0-1)
            bm25_weight: BM25Weights (0-1)
        """
        if abs(vector_weight + bm25_weight - 1.0) > 0.01:
            logger.warning(f"Weights are not combined1，Reunify: {vector_weight} + {bm25_weight}")
            total = vector_weight + bm25_weight
            vector_weight = vector_weight / total
            bm25_weight = bm25_weight / total
        
        self.hybrid_retriever.vector_weight = vector_weight
        self.hybrid_retriever.bm25_weight = bm25_weight
        
        logger.info(f"Mixed search weight updated: Vector={vector_weight:.2f}, BM25={bm25_weight:.2f}")
    
    def get_hybrid_retrieval_config(self):
        """Get Mixed Search Configuration"""
        return {
            "vector_weight": self.hybrid_retriever.vector_weight,
            "bm25_weight": self.hybrid_retriever.bm25_weight,
            "bm25_trained": self.hybrid_retriever.is_trained
        }
    
    def enable_query_preprocessing(self):
        """Enable query preprocessing"""
        if hasattr(self, 'query_preprocessor'):
            self.query_preprocessor.enabled = True
            logger.info("Query preprocessing enabled")
            return {"status": "success", "message": "Query preprocessing enabled"}
        else:
            logger.warning("Query preprocessor not initialized")
            return {"status": "error", "message": "Query preprocessor not initialized"}
    
    def disable_query_preprocessing(self):
        """Disable query preprocessing"""
        if hasattr(self, 'query_preprocessor'):
            self.query_preprocessor.enabled = False
            logger.info("Query preprocessing is disabled")
            return {"status": "success", "message": "Query preprocessing is disabled"}
        else:
            logger.warning("Query preprocessor not initialized")
            return {"status": "error", "message": "Query preprocessor not initialized"}
    
    def get_query_preprocessing_status(self):
        """Get Query Preprocessing Function"""
        if hasattr(self, 'query_preprocessor'):
            return {
                "enabled": self.query_preprocessor.enabled,
                "status": "success"
            }
        else:
            return {
                "enabled": False,
                "status": "error",
                "message": "Query preprocessor not initialized"
        }
