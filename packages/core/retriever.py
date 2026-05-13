import asyncio
import concurrent.futures
import traceback

from .. import config
from .knowledgebase import KnowledgeBase
from .graphbase import GraphDatabase
from ..models.rerank_model import get_reranker # Use standard reranker (Zhipu AI/SiliconFlow/Local)
from ..utils.logging_config import logger
from ..models import select_model
from .operators import HyDEOperator
from ..utils.web_search import WebSearcher
from ..utils.prompts import knowbase_qa_template
from ..utils.prompts import rewritten_query_prompt_template
from ..utils.prompts import entity_extraction_prompt_template as entity_template
from ..utils.prompts import keywords_prompt_template as keywords_template
from .entity_extractor import EntityExtractor


class Retriever:

    def __init__(self):
        self.knowledge_base = KnowledgeBase()
        self.graph_base = GraphDatabase()
        self.entity_extractor = EntityExtractor()
        self._load_models()

    def _load_models(self):
        # Use standard reranker (Zhipu AI / SiliconFlow / Local)
        try:
            self.reranker = get_reranker(config)
            logger.info(f"Reranker initialization successful: {config.reranker}")
        except Exception as e:
            logger.error(f"Reranker Initialization failed: {e}")
            self.reranker = None

        if config.enable_web_search:
            self.web_searcher = WebSearcher()

    def retrieval(self, query, history, meta):
        refs = {"query": query, "history": history, "meta": meta}
        refs["model_name"] = config.model_name
        
        # Check if hybrid retrieval is enabled
        if meta.get("use_hybrid_retrieval", False):
            refs.update(self.hybrid_retrieval(query, history, meta))
        else:
            # Original search method
            refs["entities"] = self.reco_entities(query, history, refs)
            refs["knowledge_base"] = self.query_knowledgebase(query, history, refs)
            refs["graph_base"] = self.query_graph(query, history, refs)
            refs["web_search"] = self.query_web(query, history, refs)

        return refs

    def restart(self):
        """All models to restart"""
        self._load_models()

    def hybrid_retrieval(self, query, history, meta):
        """Five-stage mixed search：Vector Search -> Entity Link -> Figure search -> Reorder -> Context Integration"""
        logger.info("Start a five-stage hybrid search")
        
        # Phase 1: Vector retrieval - extensive semantic recall
        vector_results = self._vector_retrieval_stage(query, history, meta)
        
        # Stage 2: Entity links - extract entities from queries and recall documents
        seed_entities = self._entity_linking_stage(query, vector_results, meta)
        
        # Phase 3: Diagram Retrieval - Seed-based Neighbors
        graph_results, graph_context_list = self._graph_retrieval_stage(seed_entities, query, meta)
        
        # Phase 4: Reorder - Smartly sort all recall contexts
        reranked_context = self._rerank_stage(query, vector_results, graph_context_list, meta)

        # Phase 5: Context integration - Results of the reordering of integration
        fused_context = self._context_fusion_stage(reranked_context, query)
        
        return {
            "entities": seed_entities,
            "knowledge_base": vector_results,
            "graph_base": graph_results,
            "reranked_context": reranked_context, # Add re-ranked context for debugging
            "fused_context": fused_context,
            "web_search": self.query_web(query, history, {"meta": meta})
        }

    def _vector_retrieval_stage(self, query, history, meta):
        """Phase 1: Vector Search - Broad semantic recall"""
        logger.debug("Phase 1: Vector Search")
        
        db_id = meta.get("db_id")
        if not db_id or not config.enable_knowledge_base:
            return {"results": [], "message": "The knowledge base is not enabled or specified"}
        
        # Rewrite queries to obtain better semantic matching
        rw_query = self.rewrite_query(query, history, {"meta": meta})
        
        # Use bigger top k for extensive recall
        top_k = meta.get("vector_top_k", 20)  # Default 20 results
        distance_threshold = meta.get("vector_distance_threshold", 0.7)  # Easier threshold
        
        query_result = self.knowledge_base.query(
            query=rw_query,
            db_id=db_id,
            distance_threshold=distance_threshold,
            rerank_threshold=meta.get("rerankThreshold", 0.1),
            max_query_count=meta.get("maxQueryCount", 20),
            top_k=top_k
        )
        
        logger.debug(f"Vector Retrieval Return {len(query_result['results'])} Results")
        return query_result

    def _entity_linking_stage(self, query, vector_results, meta):
        """Phase 2: Entity Linking - Optimized for chunked parallel processing to reduce CPU load"""
        logger.debug("Phase 2: Entity Linking (Chunked Parallel Mode)")
        
        # 1. Collection of all pending texts
        texts_to_process = [query]
        if vector_results and vector_results.get("results"):
            doc_limit = meta.get("entity_extraction_doc_limit", 10)
            for result in vector_results["results"][:doc_limit]:
                if isinstance(result, dict) and "entity" in result:
                    texts_to_process.append(result["entity"]["text"])
        
        # 2. Split text blocks (each containing + N documents)
        chunk_size = meta.get("entity_extraction_chunk_size", 4) # Each block contains queries + 3 documents
        text_chunks = []
        # The first block always contains queries
        base_chunk = [query]
        # Skip the query itself which is at index 0
        for i in range(1, len(texts_to_process)):
            base_chunk.append(texts_to_process[i])
            if len(base_chunk) >= chunk_size or i == len(texts_to_process) - 1:
                text_chunks.append("\n".join(base_chunk))
                base_chunk = [query] # Reset next block with query
        
        # Handle case where there are few documents and the loop doesn't run
        if len(base_chunk) > 1 and (len(text_chunks) == 0 or text_chunks[-1] != "\n".join(base_chunk)):
             text_chunks.append("\n".join(base_chunk))

        logger.info(f"Entity Linking: Splitting {len(texts_to_process)-1} documents into {len(text_chunks)} chunks for parallel processing.")

        # 3. Parallel entity extraction
        all_entities = set()
        
        async def extract_from_chunk(chunk_text):
            try:
                stix_entities = await self.entity_extractor.extract_entities(text=chunk_text, language="english")
                keywords = self._extract_keywords_from_text(chunk_text, query)
                
                chunk_entities = set(keywords)
                if stix_entities:
                    for entity in stix_entities:
                        if isinstance(entity, dict) and "name" in entity:
                            chunk_entities.add(entity["name"])
                return chunk_entities
            except Exception as e:
                logger.warning(f"Entity extraction failed while processing chunk: {e}")
                return set()

        async def run_parallel_extraction():
            tasks = [extract_from_chunk(chunk) for chunk in text_chunks]
            results = await asyncio.gather(*tasks)
            for entity_set in results:
                all_entities.update(entity_set)

        try:
            # Run parallel extraction in a thread-safe manner
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: asyncio.run(run_parallel_extraction()))
                future.result()
            
            # 4. Deduplication and formatting
            unique_entities = list(set([e.strip() for e in all_entities if e.strip() and len(e.strip()) > 1]))
            
            logger.info(f"Entity linking successful: Extracted {len(unique_entities)} unique entities from all chunks.")
            return unique_entities
            
        except Exception as e:
            logger.error(f"Failed to process entity links in parallel: {e}, {traceback.format_exc()}")
            # Back to simple keyword extraction
            return self._extract_keywords_from_text("\n".join(texts_to_process), query)

    def _extract_keywords_from_text(self, text, query):
        """Extract keywords from text"""
        try:
            model_provider = config.model_provider
            model_name = config.model_name
            model = select_model(model_provider=model_provider, model_name=model_name)
            
            # Extract template with keyword
            keyword_prompt = keywords_template.format(text=text, query=query)
            keywords_response = model.predict(keyword_prompt).content
            
            # Parsing keywords
            keywords = [kw.strip() for kw in keywords_response.split("<->") if kw.strip()]
            return keywords
            
        except Exception as e:
            logger.error(f"keyword extraction failed: {e}")
            return []

    def _graph_retrieval_stage(self, seed_entities, query, meta):
        """Phase 3: Graph Search - Entity-based neighbor query"""
        logger.debug("Phase 3: Graph Search (Neighbor query)")
        
        if not seed_entities or not self.graph_base.is_running():
            return {"results": []}, []

        hops = meta.get("graph_hops", 2)
        all_graph_results = []
        
        try:
            # Query neighbours for each seed entity
            for entity_name in seed_entities:
                # Multiple Jump Query specific intity
                entity_results = self.graph_base.query_specific_entity(
                    entity_name=entity_name,
                    hops=hops
                )
                if entity_results:
                    all_graph_results.extend(entity_results)
            
            # Reshaping and formatting results
            unique_results = self._deduplicate_graph_results(all_graph_results)
            formatted_results = self.graph_base.format_query_result_to_graph(unique_results)
            
            # Convert the results to a text context list for reranker
            graph_context_list = []
            if formatted_results and formatted_results.get("edges"):
                for edge in formatted_results["edges"]:
                    context_str = f"The relationship between {edge.get('source_name')} and {edge.get('target_name')} is {edge.get('type')}."
                    graph_context_list.append(context_str)

            logger.debug(f"Graph Retrieval returned {len(formatted_results.get('edges', []))} relationships")
            return formatted_results, graph_context_list

        except Exception as e:
            logger.error(f"Graph search phase failed: {e}, {traceback.format_exc()}")
            return {"results": []}, []

    def _deduplicate_graph_results(self, results):
        """Deduplicate graph search results"""
        seen = set()
        unique_results = []
        
        for result in results:
            # Deal with different results formats
            if isinstance(result, (list, tuple)) and len(result) >= 3:
                result_key = (str(result[0]), str(result[2]), str(result[1]))
            elif isinstance(result, dict):
                result_key = (result.get('h'), result.get('t'), result.get('r'))
            else:
                continue
                
            if result_key not in seen:
                seen.add(result_key)
                unique_results.append(result)
        
        return unique_results

    def _rerank_stage(self, query: str, vector_results, graph_context_list: list, meta: dict) -> str:
        """Phase 4: Re-ranking - Rate and rank all candidate contexts (using Zhipu AI Reranker)"""
        logger.info("Phase 4: Re-ranking starting")
        
        if not self.reranker:
            error_msg = "Reranker not initialized! Please check the configuration and API Key."
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # 1. Collection of all candidate documents
        candidate_docs = []
        # Extract text from vector search results
        if vector_results and vector_results.get("results"):
            for res in vector_results["results"]:
                if isinstance(res, dict) and res.get("entity"):
                    candidate_docs.append(res["entity"]["text"])
        
        # Add Diagram Search Results
        candidate_docs.extend(graph_context_list)
        
        # Deduplication
        unique_docs = list(dict.fromkeys(candidate_docs))
        
        logger.info(f"Collected {len(unique_docs)} unique documents for re-ranking (Vector: {len(candidate_docs) - len(graph_context_list)}, Graph: {len(graph_context_list)})")
        
        # --- Add: API requests protection logic ---
        # According to the API limit, protection requests are not unlimited.
        reranker_max_docs = meta.get("reranker_max_docs", 100)  # API cap 128. We use 100 as a security value.
        reranker_max_length = meta.get("reranker_max_length", 30000) # API cap 32k. We use 30k as a security value.

        # 1. Hard limit the number of documents
        if len(unique_docs) > reranker_max_docs:
            logger.warning(f"Reranker: Number of documents to be reranked ({len(unique_docs)}) exceeds limit ({reranker_max_docs}), truncating.")
            unique_docs = unique_docs[:reranker_max_docs]

        # 2. Check and ensure that the length of the total text is not excessive
        current_length = len(query)
        docs_for_rerank = []
        for doc in unique_docs:
            if current_length + len(doc) > reranker_max_length:
                logger.warning(f"Reranker: Total text length reaches limit ({reranker_max_length}), stopping document addition. Final count: {len(docs_for_rerank)}.")
                break
            docs_for_rerank.append(doc)
            current_length += len(doc)
        
        unique_docs = docs_for_rerank
        logger.info(f"Reranker: Final number of documents for re-ranking: {len(unique_docs)}, total length approximately {current_length} characters.")
        # --- protection logic end---

        if not unique_docs:
            logger.warning("No candidate document to reorder")
            return ""

        # 2. Call reranker model (using compute score API)
        rerank_top_k = config.RERANK_TOP_K
        logger.info(f"Call Reranker Model，top_k={rerank_top_k}")
        
        # [query, [doc1, doc2,...] Format
        sentence_pairs = [query, unique_docs]
        scores = self.reranker.compute_score(sentence_pairs, normalize=True)
        
        if not scores or len(scores) == 0:
            error_msg = f"Reranker returned empty result! Query='{query[:50]}', doc_count={len(unique_docs)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # 3. Pair documents with scores and sort
        doc_score_pairs = list(zip(unique_docs, scores))
        sorted_pairs = sorted(doc_score_pairs, key=lambda x: x[1], reverse=True)
        
        # Take top k results
        top_pairs = sorted_pairs[:rerank_top_k]
        
        logger.info(f"Reranker successfully returned {len(scores)} scores, selected top {len(top_pairs)} results")
        context_parts = []
        for i, (doc, score) in enumerate(top_pairs):
            logger.info(f"Re-rank Result {i+1}: score={score:.4f}, doc_length={len(doc)}")
            context_parts.append(f"[Re-rank Result {i+1}, Score: {score:.4f}]: {doc}")
        
        final_context = "\n\n".join(context_parts)
        logger.info(f"Re-ranking complete, final context contains {len(top_pairs)} snippets, total length {len(final_context)} characters")
        
        return final_context

    def _context_fusion_stage(self, reranked_context: str, query: str):
        """Phase5：Context Integration - Build final context based on the result of the rearrangement"""
        logger.debug("Phase5：Context Integration")
        
        # In the new process, the context has been formatted at the rerank stage
        # The main purpose here is to maintain structural integrity and to add summary information.
        if not reranked_context:
            return {
                "final_context": "",
                "query": query,
                "summary": "Could not retrieve any relevant information for the query."
            }
            
        summary = f"Based on the query '{query}', all retrieved content was reranked and the most relevant results were selected as context."

        fused_context = {
            "final_context": reranked_context,
            "query": query,
            "summary": summary
        }
        
        logger.debug(f"Context integration complete: {fused_context['summary']}")
        return fused_context

    def construct_query(self, query, refs, meta):
        logger.debug(f"{refs=}")
        if not refs or len(refs) == 0:
            return query

        # Check to show search result information
        show_retrieval_info = meta.get("show_retrieval_info", True)  # Default is True, always transmitting search results
        
        if not show_retrieval_info:
            # If search result information should not be shown, return original query
            return query

        # Check if new hybrid retrieval workflow is used (via reranked_context)
        if refs.get("fused_context") and "final_context" in refs["fused_context"]:
            return self._construct_hybrid_query(query, refs, meta)
        else:
            return self._construct_traditional_query(query, refs, meta)

    def _construct_hybrid_query(self, query, refs, meta):
        """Construct a query for a new mixed search"""
        fused_context = refs.get("fused_context", {})
        final_context = fused_context.get("final_context", "")
        external_parts = []
        
        if final_context:
            # New context already contains source and ranking information
            external_parts.extend(["Based on the following re-ranked context information:", final_context])
        
        # Add results of network search
        web_res = refs.get("web_search", {}).get("results", [])
        if web_res:
            web_text = "\n".join(f"{r['title']}: {r['content']}" for r in web_res)
            external_parts.extend(["Additional web search information:", web_text])
        
        # Construct queries
        if external_parts:
            external = "\n\n".join(external_parts)
            query = knowbase_qa_template.format(external=external, query=query)
        
        return query

    def _construct_traditional_query(self, query, refs, meta):
        """Construct traditional search queries"""
        external_parts = []

        # Results of the analysis of the knowledge base
        kb_res = refs.get("knowledge_base", {}).get("results", [])
        if kb_res:
            kb_text = "\n".join(f"{r['id']}: {r['entity']['text']}" for r in kb_res)
            external_parts.extend(["Knowledge base information:", kb_text])

        # Parse Graph Database results
        db_res = refs.get("graph_base", {}).get("results", {})
        logger.debug(f"Graph database result type: {type(db_res)}, content: {db_res}")
        
        # Handle different return formats
        if isinstance(db_res, dict) and db_res.get("nodes") and len(db_res["nodes"]) > 0:
            db_text = "\n".join(
                [f"The relationship between {edge['source_name']} and {edge['target_name']} is {edge['type']}" for edge in db_res.get("edges", [])]
            )
            external_parts.extend(["Graph database information:", db_text])
        elif isinstance(db_res, list) and len(db_res) > 0:
            # If list format is returned, process directly
            db_text = "\n".join(
                [f"The relationship between {item.get('source_name', '')} and {item.get('target_name', '')} is {item.get('type', '')}" 
                 for item in db_res if isinstance(item, dict)]
            )
            if db_text.strip():
                external_parts.extend(["Graph database information:", db_text])

        # Parse web search results
        web_res = refs.get("web_search", {}).get("results", [])
        if web_res:
            web_text = "\n".join(f"{r['title']}: {r['content']}" for r in web_res)
            external_parts.extend(["Web search information:", web_text])

        # Construct queries
        if external_parts and len(external_parts) > 0:
            external = "\n\n".join(external_parts)
            query = knowbase_qa_template.format(external=external, query=query)

        return query

    def query_classification(self, query):
        """Determine if a query is necessary
        - For tasks fully based on user-provided information, call it "sufficient", no retrieval needed;
        - Otherwise, call it "insufficient", retrieval may be required.
        """
        raise NotImplementedError

    def query_graph(self, query, history, refs):
        """Enhanced Graph retrieval method, supports multi-mode search"""
        results = []
        if not refs["meta"].get("use_graph") or not config.enable_knowledge_base:
            return {"results": []}
        
        # Get Search Mode Configuration
        search_mode = refs["meta"].get("search_mode", "hybrid")  # local, global, hybrid
        top_k = refs["meta"].get("top_k", 10)
        threshold = refs["meta"].get("threshold", 0.7)
        
        # Extract Keywords
        entities = refs.get("entities", [])
        keywords = [entity for entity in entities if entity.strip()]
        
        if not keywords:
            return {"results": []}
        
        # Select search policy according to mode
        if search_mode == "local":
            # Entity-based local searches
            results = self._search_entities_and_relations(keywords, top_k, threshold)
        elif search_mode == "global":
            # Global search based on relationship keywords
            results = self._search_relations_and_entities(keywords, top_k, threshold)
        else:  # hybrid
            # Mixed search: combining entities and relationships
            entity_results = self._search_entities_and_relations(keywords, top_k, threshold)
            relation_results = self._search_relations_and_entities(keywords, top_k, threshold)
            results = self._merge_search_results(entity_results, relation_results)
        
        return {"results": self.graph_base.format_query_result_to_graph(results)}

    def _search_entities_and_relations(self, keywords, top_k, threshold):
        """Search relationships based on entities"""
        try:
            # Use of batch search to improve efficiency
            all_results = self.graph_base.query_nodes_batch(
                keywords, 
                threshold=threshold, 
                max_entities=top_k
            )
        except Exception as e:
            logger.warning(f"Batch Entity Search Failed: {e}")
            # Back to Single Search
            all_results = []
            for keyword in keywords:
                try:
                    entity_results = self.graph_base.query_node(
                        keyword, 
                        threshold=threshold, 
                        max_entities=top_k
                    )
                    all_results.extend(entity_results)
                except Exception as e:
                    logger.warning(f"Entity search failed {keyword}: {e}")
                    continue
        
        # Weight and limit the number of results
        seen = set()
        unique_results = []
        for result in all_results:
            # Process the Neo4j original result format
            if isinstance(result, (list, tuple)) and len(result) >= 3:
                # Neo4j original format: [node1, relationships, node2]
                result_key = (str(result[0]), str(result[2]), str(result[1]))
            elif isinstance(result, dict):
                # Dictionary format: {'h': , 't': , 'r': }
                result_key = (result.get('h'), result.get('t'), result.get('r'))
            else:
                # Other Formats, Skip
                continue
                
            if result_key not in seen:
                seen.add(result_key)
                unique_results.append(result)
                if len(unique_results) >= top_k:
                    break
        
        return unique_results

    def _search_relations_and_entities(self, keywords, top_k, threshold):
        """Search related entities based on relationship keywords"""
        all_results = []
        
        for keyword in keywords:
            try:
                # Other Organiser
                relation_results = self.graph_base.query_by_relationship_type(
                    keyword, 
                    hops=2
                )
                all_results.extend(relation_results)
            except Exception as e:
                logger.warning(f"Relationship search failed {keyword}: {e}")
                continue
        
        # Weight and limit the number of results
        seen = set()
        unique_results = []
        for result in all_results:
            # Process the Neo4j original result format
            if isinstance(result, (list, tuple)) and len(result) >= 3:
                # Neo4j original format: [node1, relationships, node2]
                result_key = (str(result[0]), str(result[2]), str(result[1]))
            elif isinstance(result, dict):
                # Dictionary format: {'h': , 't': , 'r': }
                result_key = (result.get('h'), result.get('t'), result.get('r'))
            else:
                # Other Formats, Skip
                continue
                
            if result_key not in seen:
                seen.add(result_key)
                unique_results.append(result)
                if len(unique_results) >= top_k:
                    break
        
        return unique_results

    def _merge_search_results(self, entity_results, relation_results):
        """Merge entity and relationship search results using a Round-Robin strategy"""
        merged_results = []
        seen = set()
        
        # Rounded Query Merge: Reciprocally obtain results from two results
        max_len = max(len(entity_results), len(relation_results))
        for i in range(max_len):
            # First result of the entity
            if i < len(entity_results):
                result = entity_results[i]
                # Process the Neo4j original result format
                if isinstance(result, (list, tuple)) and len(result) >= 3:
                    result_key = (str(result[0]), str(result[2]), str(result[1]))
                elif isinstance(result, dict):
                    result_key = (result.get('h'), result.get('t'), result.get('r'))
                else:
                    continue
                    
                if result_key not in seen:
                    seen.add(result_key)
                    merged_results.append(result)
            
            # Next, pick from relationship results
            if i < len(relation_results):
                result = relation_results[i]
                # Process the Neo4j original result format
                if isinstance(result, (list, tuple)) and len(result) >= 3:
                    result_key = (str(result[0]), str(result[2]), str(result[1]))
                elif isinstance(result, dict):
                    result_key = (result.get('h'), result.get('t'), result.get('r'))
                else:
                    continue
                    
                if result_key not in seen:
                    seen.add(result_key)
                    merged_results.append(result)
        
        return merged_results

    def query_knowledgebase(self, query, history, refs):
        """Query the knowledge base"""

        response = {
            "results": [],
            "all_results": [],
            "rw_query": query,
            "message": "",
        }

        meta = refs["meta"]

        db_id = meta.get("db_id")
        if not db_id or not config.enable_knowledge_base:
            response["message"] = "Knowledge base not enabled, not specified, or does not exist"
            return response

        rw_query = self.rewrite_query(query, history, refs)

        logger.debug(f"{meta=}")
        query_result = self.knowledge_base.query(query=rw_query,
                                            db_id=db_id,
                                            distance_threshold=meta.get("distanceThreshold", 0.5),
                                            rerank_threshold=meta.get("rerankThreshold", 0.1),
                                            max_query_count=meta.get("maxQueryCount", 20),
                                            top_k=meta.get("topK", 10))

        response["results"] = query_result["results"]
        response["all_results"] = query_result["all_results"]
        response["rw_query"] = rw_query
        response["message"] = query_result["message"]

        return response

    def query_web(self, query, history, refs):
        """Query web search"""

        if not refs["meta"].get("use_web") or not config.enable_web_search:
            return {"results": [], "message": "Web search is disabled"}

        if not hasattr(self, 'web_searcher'):
            logger.warning("Web searcher not initialized")
            return {"results": [], "message": "Web searcher not initialized"}

        try:
            search_results = self.web_searcher.search(query, max_results=5)
            return {"results": search_results}
        except Exception as e:
            logger.error(f"Web search error: {str(e)}")
            return {"results": [], "message": f"Web search error: {str(e)}"}

    def rewrite_query(self, query, history, refs):
        """Rewrite queries"""
        model_provider = config.model_provider
        model_name = config.model_name
        model = select_model(model_provider=model_provider, model_name=model_name)
        if refs["meta"].get("mode") == "search":  # If search mode, use meta configuration, or use global configuration
            rewrite_query_span = refs["meta"].get("use_rewrite_query", "off")
        else:
            rewrite_query_span = config.use_rewrite_query

        if rewrite_query_span == "off":
            rewritten_query = query
        else:
            history_query = [entry["content"] for entry in history if entry["role"] == "user"] if history else ""
            rewritten_query_prompt = rewritten_query_prompt_template.format(history=history_query, query=query)
            rewritten_query = model.predict(rewritten_query_prompt).content

        if rewrite_query_span == "hyde":
            res = HyDEOperator.call(model_callable=model.predict, query=query, context_str=history_query)
            rewritten_query = res.content

        return rewritten_query

    def reco_entities(self, query, history, refs):
        """Recognize entities in the query"""
        query = refs.get("rewritten_query", query)
        model_provider = config.model_provider
        model_name = config.model_name
        model = select_model(model_provider=model_provider, model_name=model_name)

        entities = []
        if refs["meta"].get("use_graph"):
            entity_extraction_prompt = entity_template.format(text=query)
            entities = model.predict(entity_extraction_prompt).content.split("<->")
            # [entity for entity in entities if all (char.isalnum() or char in entity)]

        return entities

    def __call__(self, query, history, meta):
        refs = self.retrieval(query, history, meta)
        query = self.construct_query(query, refs, meta)
        return query, refs
