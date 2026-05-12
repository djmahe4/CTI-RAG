import asyncio
import concurrent.futures
import traceback

from .. import config
from .knowledgebase import KnowledgeBase
from .graphbase import GraphDatabase
from ..models.rerank_model import get_reranker # 使用标准 reranker (智谱AI/SiliconFlow/Local)
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
        # 使用标准 reranker (智谱AI / SiliconFlow / Local)
        try:
            self.reranker = get_reranker(config)
            logger.info(f"Reranker 初始化成功: {config.reranker}")
        except Exception as e:
            logger.error(f"Reranker 初始化失败: {e}")
            self.reranker = None

        if config.enable_web_search:
            self.web_searcher = WebSearcher()

    def retrieval(self, query, history, meta):
        refs = {"query": query, "history": history, "meta": meta}
        refs["model_name"] = config.model_name
        
        # 检查是否启用四阶段检索
        if meta.get("use_hybrid_retrieval", False):
            refs.update(self.hybrid_retrieval(query, history, meta))
        else:
            # 原有的检索方式
            refs["entities"] = self.reco_entities(query, history, refs)
            refs["knowledge_base"] = self.query_knowledgebase(query, history, refs)
            refs["graph_base"] = self.query_graph(query, history, refs)
            refs["web_search"] = self.query_web(query, history, refs)

        return refs

    def restart(self):
        """所有需要重启的模型"""
        self._load_models()

    def hybrid_retrieval(self, query, history, meta):
        """五阶段混合检索：向量检索 -> 实体链接 -> 图检索 -> 重排序 -> 上下文融合"""
        logger.info("开始五阶段混合检索")
        
        # 阶段1：向量检索 - 广泛的语义召回
        vector_results = self._vector_retrieval_stage(query, history, meta)
        
        # 阶段2：实体链接 - 从查询和召回文档中提取实体
        seed_entities = self._entity_linking_stage(query, vector_results, meta)
        
        # 阶段3：图检索 - 基于种子实体的邻居发现
        graph_results, graph_context_list = self._graph_retrieval_stage(seed_entities, query, meta)
        
        # 阶段4: 重排序 - 对所有召回的上下文进行智能排序
        reranked_context = self._rerank_stage(query, vector_results, graph_context_list, meta)

        # 阶段5：上下文融合 - 整合重排后的结果
        fused_context = self._context_fusion_stage(reranked_context, query)
        
        return {
            "entities": seed_entities,
            "knowledge_base": vector_results,
            "graph_base": graph_results,
            "reranked_context": reranked_context, # 添加重排后的上下文用于调试
            "fused_context": fused_context,
            "web_search": self.query_web(query, history, {"meta": meta})
        }

    def _vector_retrieval_stage(self, query, history, meta):
        """阶段1：向量检索 - 进行广泛的语义召回"""
        logger.debug("阶段1：向量检索")
        
        db_id = meta.get("db_id")
        if not db_id or not config.enable_knowledge_base:
            return {"results": [], "message": "知识库未启用或未指定"}
        
        # 重写查询以获得更好的语义匹配
        rw_query = self.rewrite_query(query, history, {"meta": meta})
        
        # 使用更大的top_k进行广泛召回
        top_k = meta.get("vector_top_k", 20)  # 默认20个结果
        distance_threshold = meta.get("vector_distance_threshold", 0.7)  # 更宽松的阈值
        
        query_result = self.knowledge_base.query(
            query=rw_query,
            db_id=db_id,
            distance_threshold=distance_threshold,
            rerank_threshold=meta.get("rerankThreshold", 0.1),
            max_query_count=meta.get("maxQueryCount", 20),
            top_k=top_k
        )
        
        logger.debug(f"向量检索返回 {len(query_result['results'])} 个结果")
        return query_result

    def _entity_linking_stage(self, query, vector_results, meta):
        """阶段2：实体链接 - 优化为分块并行处理以降低CPU负载"""
        logger.debug("阶段2：实体链接 (分块并行模式)")
        
        # 1. 收集所有待处理的文本
        texts_to_process = [query]
        if vector_results and vector_results.get("results"):
            doc_limit = meta.get("entity_extraction_doc_limit", 10)
            for result in vector_results["results"][:doc_limit]:
                if isinstance(result, dict) and "entity" in result:
                    texts_to_process.append(result["entity"]["text"])
        
        # 2. 将文本分块 (每块包含查询 + N个文档)
        chunk_size = meta.get("entity_extraction_chunk_size", 4) # 每个块包含查询 + 3个文档
        text_chunks = []
        # 第一个块总是包含查询
        base_chunk = [query]
        # Skip the query itself which is at index 0
        for i in range(1, len(texts_to_process)):
            base_chunk.append(texts_to_process[i])
            if len(base_chunk) >= chunk_size or i == len(texts_to_process) - 1:
                text_chunks.append("\n".join(base_chunk))
                base_chunk = [query] # 为下一个块重置，并带上查询
        
        # Handle case where there are few documents and the loop doesn't run
        if len(base_chunk) > 1 and (len(text_chunks) == 0 or text_chunks[-1] != "\n".join(base_chunk)):
             text_chunks.append("\n".join(base_chunk))

        logger.info(f"实体链接：将 {len(texts_to_process)-1} 个文档分成了 {len(text_chunks)} 个块进行并行处理。")

        # 3. 并行提取实体
        all_entities = set()
        
        async def extract_from_chunk(chunk_text):
            try:
                stix_entities = await self.entity_extractor.extract_entities(text=chunk_text, language="chinese")
                keywords = self._extract_keywords_from_text(chunk_text, query)
                
                chunk_entities = set(keywords)
                if stix_entities:
                    for entity in stix_entities:
                        if isinstance(entity, dict) and "name" in entity:
                            chunk_entities.add(entity["name"])
                return chunk_entities
            except Exception as e:
                logger.warning(f"处理块时实体提取失败: {e}")
                return set()

        async def run_parallel_extraction():
            tasks = [extract_from_chunk(chunk) for chunk in text_chunks]
            results = await asyncio.gather(*tasks)
            for entity_set in results:
                all_entities.update(entity_set)

        try:
            # 在线程池中运行异步并行代码
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: asyncio.run(run_parallel_extraction()))
                future.result()
            
            # 4. 去重和格式化
            unique_entities = list(set([e.strip() for e in all_entities if e.strip() and len(e.strip()) > 1]))
            
            logger.info(f"实体链接成功：从所有块中提取到 {len(unique_entities)} 个唯一实体。")
            return unique_entities
            
        except Exception as e:
            logger.error(f"实体链接并行处理失败: {e}, {traceback.format_exc()}")
            # 回退到简单的关键词提取
            return self._extract_keywords_from_text("\n".join(texts_to_process), query)

    def _extract_keywords_from_text(self, text, query):
        """从文本中提取关键词"""
        try:
            model_provider = config.model_provider
            model_name = config.model_name
            model = select_model(model_provider=model_provider, model_name=model_name)
            
            # 使用关键词提取模板
            keyword_prompt = keywords_template.format(text=text, query=query)
            keywords_response = model.predict(keyword_prompt).content
            
            # 解析关键词
            keywords = [kw.strip() for kw in keywords_response.split("<->") if kw.strip()]
            return keywords
            
        except Exception as e:
            logger.error(f"关键词提取失败: {e}")
            return []

    def _graph_retrieval_stage(self, seed_entities, query, meta):
        """阶段3：图检索 - 基于实体的邻居查询"""
        logger.debug("阶段3：图检索 (邻居查询)")
        
        if not seed_entities or not self.graph_base.is_running():
            return {"results": []}, []

        hops = meta.get("graph_hops", 2)
        all_graph_results = []
        
        try:
            # 对每个种子实体执行邻居查询
            for entity_name in seed_entities:
                # 使用 query_specific_entity 进行多跳查询
                entity_results = self.graph_base.query_specific_entity(
                    entity_name=entity_name,
                    hops=hops
                )
                if entity_results:
                    all_graph_results.extend(entity_results)
            
            # 去重和格式化结果
            unique_results = self._deduplicate_graph_results(all_graph_results)
            formatted_results = self.graph_base.format_query_result_to_graph(unique_results)
            
            # 将图结果转换为文本上下文列表，用于reranker
            graph_context_list = []
            if formatted_results and formatted_results.get("edges"):
                for edge in formatted_results["edges"]:
                    context_str = f"{edge.get('source_name')}的'{edge.get('type')}'是'{edge.get('target_name')}'"
                    graph_context_list.append(context_str)

            logger.debug(f"图检索返回 {len(formatted_results.get('edges', []))} 个关系")
            return formatted_results, graph_context_list

        except Exception as e:
            logger.error(f"图检索阶段失败: {e}, {traceback.format_exc()}")
            return {"results": []}, []

    def _deduplicate_graph_results(self, results):
        """对图检索结果进行去重"""
        seen = set()
        unique_results = []
        
        for result in results:
            # 处理不同的结果格式
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
        """阶段4: 重排序 - 对所有候选上下文进行打分和排序（使用智谱AI Reranker）"""
        logger.info("阶段4: 重排序开始")
        
        if not self.reranker:
            error_msg = "Reranker 未初始化！请检查配置文件和 API Key 是否正确。"
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        # 1. 收集所有候选文档
        candidate_docs = []
        # 从向量检索结果中提取文本
        if vector_results and vector_results.get("results"):
            for res in vector_results["results"]:
                if isinstance(res, dict) and res.get("entity"):
                    candidate_docs.append(res["entity"]["text"])
        
        # 添加图检索结果
        candidate_docs.extend(graph_context_list)
        
        # 去重
        unique_docs = list(dict.fromkeys(candidate_docs))
        
        logger.info(f"收集到 {len(unique_docs)} 个唯一文档准备重排序 (向量: {len(candidate_docs) - len(graph_context_list)}, 图: {len(graph_context_list)})")
        
        # --- 新增：API请求保护逻辑 ---
        # 根据智谱API限制，保护请求不会超限
        reranker_max_docs = meta.get("reranker_max_docs", 100)  # API上限128，我们用100作为安全值
        reranker_max_length = meta.get("reranker_max_length", 30000) # API上限32k，我们用30k作为安全值

        # 1. 硬性限制文档数量
        if len(unique_docs) > reranker_max_docs:
            logger.warning(f"Reranker: 待重排文档数 ({len(unique_docs)}) 超出上限 ({reranker_max_docs})，将进行截断。")
            unique_docs = unique_docs[:reranker_max_docs]

        # 2. 检查并确保总文本长度不超限
        current_length = len(query)
        docs_for_rerank = []
        for doc in unique_docs:
            if current_length + len(doc) > reranker_max_length:
                logger.warning(f"Reranker: 文本总长度达到上限 ({reranker_max_length})，已停止添加更多文档。最终数量: {len(docs_for_rerank)}。")
                break
            docs_for_rerank.append(doc)
            current_length += len(doc)
        
        unique_docs = docs_for_rerank
        logger.info(f"Reranker: 最终将使用 {len(unique_docs)} 个文档进行重排序，总长度约为 {current_length} 字符。")
        # --- 保护逻辑结束 ---

        if not unique_docs:
            logger.warning("没有候选文档需要重排序")
            return ""

        # 2. 调用reranker模型 (使用 compute_score API)
        rerank_top_k = config.RERANK_TOP_K
        logger.info(f"调用 Reranker 模型，top_k={rerank_top_k}")
        
        # reranker.compute_score 接受 [query, [doc1, doc2, ...]] 格式
        sentence_pairs = [query, unique_docs]
        scores = self.reranker.compute_score(sentence_pairs, normalize=True)
        
        if not scores or len(scores) == 0:
            error_msg = f"Reranker 返回空结果！查询='{query[:50]}', 文档数={len(unique_docs)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # 3. 将文档和分数配对并排序
        doc_score_pairs = list(zip(unique_docs, scores))
        sorted_pairs = sorted(doc_score_pairs, key=lambda x: x[1], reverse=True)
        
        # 取 top_k 个结果
        top_pairs = sorted_pairs[:rerank_top_k]
        
        logger.info(f"Reranker 成功返回 {len(scores)} 个分数，选取 top {len(top_pairs)} 个结果")
        context_parts = []
        for i, (doc, score) in enumerate(top_pairs):
            logger.info(f"重排结果 {i+1}: 分数={score:.4f}, 文档长度={len(doc)}")
            context_parts.append(f"[重排结果 {i+1}, 分数: {score:.4f}]: {doc}")
        
        final_context = "\n\n".join(context_parts)
        logger.info(f"重排序完成，最终上下文包含 {len(top_pairs)} 个片段，总长度 {len(final_context)} 字符")
        
        return final_context

    def _context_fusion_stage(self, reranked_context: str, query: str):
        """阶段5：上下文融合 - 基于重排后的结果构建最终上下文"""
        logger.debug("阶段5：上下文融合")
        
        # 在新流程中，上下文已经在rerank阶段格式化好了
        # 这里主要是为了保持结构完整性，并可以添加总结信息
        if not reranked_context:
            return {
                "final_context": "",
                "query": query,
                "summary": "未能根据查询检索到任何相关信息。"
            }
            
        summary = f"基于查询 '{query}', 已对所有召回信息进行重排序并选取了最相关的结果作为上下文。"

        fused_context = {
            "final_context": reranked_context,
            "query": query,
            "summary": summary
        }
        
        logger.debug(f"上下文融合完成: {fused_context['summary']}")
        return fused_context

    def construct_query(self, query, refs, meta):
        logger.debug(f"{refs=}")
        if not refs or len(refs) == 0:
            return query

        # 检查是否显示检索结果信息
        show_retrieval_info = meta.get("show_retrieval_info", True)  # 默认为True，总是传递检索结果
        
        if not show_retrieval_info:
            # 如果不显示检索结果信息，直接返回原始查询
            return query

        # 检查是否使用了新的混合检索流程 (通过reranked_context判断)
        if refs.get("fused_context") and "final_context" in refs["fused_context"]:
            return self._construct_hybrid_query(query, refs, meta)
        else:
            return self._construct_traditional_query(query, refs, meta)

    def _construct_hybrid_query(self, query, refs, meta):
        """构造新版混合检索的查询"""
        fused_context = refs.get("fused_context", {})
        final_context = fused_context.get("final_context", "")
        external_parts = []
        
        if final_context:
            # 新的上下文已经包含了来源和排序信息
            external_parts.extend(["根据以下经过重排序的上下文信息:", final_context])
        
        # 添加网络搜索的结果
        web_res = refs.get("web_search", {}).get("results", [])
        if web_res:
            web_text = "\n".join(f"{r['title']}: {r['content']}" for r in web_res)
            external_parts.extend(["补充的网络搜索信息:", web_text])
        
        # 构造查询
        if external_parts:
            external = "\n\n".join(external_parts)
            query = knowbase_qa_template.format(external=external, query=query)
        
        return query

    def _construct_traditional_query(self, query, refs, meta):
        """构造传统检索的查询"""
        external_parts = []

        # 解析知识库的结果
        kb_res = refs.get("knowledge_base", {}).get("results", [])
        if kb_res:
            kb_text = "\n".join(f"{r['id']}: {r['entity']['text']}" for r in kb_res)
            external_parts.extend(["知识库信息:", kb_text])

        # 解析图数据库的结果
        db_res = refs.get("graph_base", {}).get("results", {})
        logger.debug(f"图数据库结果类型: {type(db_res)}, 内容: {db_res}")
        
        # 处理不同的返回格式
        if isinstance(db_res, dict) and db_res.get("nodes") and len(db_res["nodes"]) > 0:
            db_text = "\n".join(
                [f"{edge['source_name']}和{edge['target_name']}的关系是{edge['type']}" for edge in db_res.get("edges", [])]
            )
            external_parts.extend(["图数据库信息:", db_text])
        elif isinstance(db_res, list) and len(db_res) > 0:
            # 如果返回的是列表格式，直接处理
            db_text = "\n".join(
                [f"{item.get('source_name', '')}和{item.get('target_name', '')}的关系是{item.get('type', '')}" 
                 for item in db_res if isinstance(item, dict)]
            )
            if db_text.strip():
                external_parts.extend(["图数据库信息:", db_text])

        # 解析网络搜索的结果
        web_res = refs.get("web_search", {}).get("results", [])
        if web_res:
            web_text = "\n".join(f"{r['title']}: {r['content']}" for r in web_res)
            external_parts.extend(["网络搜索信息:", web_text])

        # 构造查询
        if external_parts and len(external_parts) > 0:
            external = "\n\n".join(external_parts)
            query = knowbase_qa_template.format(external=external, query=query)

        return query

    def query_classification(self, query):
        """判断是否需要查询
        - 对于完全基于用户给定信息的任务，称之为"足够""sufficient"，不需要检索；
        - 否则，称之为"不足""insufficient"，可能需要检索，
        """
        raise NotImplementedError

    def query_graph(self, query, history, refs):
        """增强的图检索方法，支持多模式搜索"""
        results = []
        if not refs["meta"].get("use_graph") or not config.enable_knowledge_base:
            return {"results": []}
        
        # 获取搜索模式配置
        search_mode = refs["meta"].get("search_mode", "hybrid")  # local, global, hybrid
        top_k = refs["meta"].get("top_k", 10)
        threshold = refs["meta"].get("threshold", 0.7)
        
        # 提取关键词
        entities = refs.get("entities", [])
        keywords = [entity for entity in entities if entity.strip()]
        
        if not keywords:
            return {"results": []}
        
        # 根据模式选择搜索策略
        if search_mode == "local":
            # 基于实体的局部搜索
            results = self._search_entities_and_relations(keywords, top_k, threshold)
        elif search_mode == "global":
            # 基于关系关键词的全局搜索
            results = self._search_relations_and_entities(keywords, top_k, threshold)
        else:  # hybrid
            # 混合搜索：结合实体和关系
            entity_results = self._search_entities_and_relations(keywords, top_k, threshold)
            relation_results = self._search_relations_and_entities(keywords, top_k, threshold)
            results = self._merge_search_results(entity_results, relation_results)
        
        return {"results": self.graph_base.format_query_result_to_graph(results)}

    def _search_entities_and_relations(self, keywords, top_k, threshold):
        """基于实体搜索相关关系"""
        try:
            # 使用批量搜索提高效率
            all_results = self.graph_base.query_nodes_batch(
                keywords, 
                threshold=threshold, 
                max_entities=top_k
            )
        except Exception as e:
            logger.warning(f"批量实体搜索失败: {e}")
            # 回退到单个搜索
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
                    logger.warning(f"实体搜索失败 {keyword}: {e}")
                    continue
        
        # 去重并限制结果数量
        seen = set()
        unique_results = []
        for result in all_results:
            # 处理Neo4j原始结果格式
            if isinstance(result, (list, tuple)) and len(result) >= 3:
                # Neo4j原始格式: [node1, relationships, node2]
                result_key = (str(result[0]), str(result[2]), str(result[1]))
            elif isinstance(result, dict):
                # 字典格式: {'h': ..., 't': ..., 'r': ...}
                result_key = (result.get('h'), result.get('t'), result.get('r'))
            else:
                # 其他格式，跳过
                continue
                
            if result_key not in seen:
                seen.add(result_key)
                unique_results.append(result)
                if len(unique_results) >= top_k:
                    break
        
        return unique_results

    def _search_relations_and_entities(self, keywords, top_k, threshold):
        """基于关系关键词搜索相关实体"""
        all_results = []
        
        for keyword in keywords:
            try:
                # 搜索包含关键词的关系
                relation_results = self.graph_base.query_by_relationship_type(
                    keyword, 
                    hops=2
                )
                all_results.extend(relation_results)
            except Exception as e:
                logger.warning(f"关系搜索失败 {keyword}: {e}")
                continue
        
        # 去重并限制结果数量
        seen = set()
        unique_results = []
        for result in all_results:
            # 处理Neo4j原始结果格式
            if isinstance(result, (list, tuple)) and len(result) >= 3:
                # Neo4j原始格式: [node1, relationships, node2]
                result_key = (str(result[0]), str(result[2]), str(result[1]))
            elif isinstance(result, dict):
                # 字典格式: {'h': ..., 't': ..., 'r': ...}
                result_key = (result.get('h'), result.get('t'), result.get('r'))
            else:
                # 其他格式，跳过
                continue
                
            if result_key not in seen:
                seen.add(result_key)
                unique_results.append(result)
                if len(unique_results) >= top_k:
                    break
        
        return unique_results

    def _merge_search_results(self, entity_results, relation_results):
        """合并实体和关系搜索结果，使用轮询策略"""
        merged_results = []
        seen = set()
        
        # 轮询合并：交替从两个结果集中取结果
        max_len = max(len(entity_results), len(relation_results))
        for i in range(max_len):
            # 先取实体结果
            if i < len(entity_results):
                result = entity_results[i]
                # 处理Neo4j原始结果格式
                if isinstance(result, (list, tuple)) and len(result) >= 3:
                    result_key = (str(result[0]), str(result[2]), str(result[1]))
                elif isinstance(result, dict):
                    result_key = (result.get('h'), result.get('t'), result.get('r'))
                else:
                    continue
                    
                if result_key not in seen:
                    seen.add(result_key)
                    merged_results.append(result)
            
            # 再取关系结果
            if i < len(relation_results):
                result = relation_results[i]
                # 处理Neo4j原始结果格式
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
        """查询知识库"""

        response = {
            "results": [],
            "all_results": [],
            "rw_query": query,
            "message": "",
        }

        meta = refs["meta"]

        db_id = meta.get("db_id")
        if not db_id or not config.enable_knowledge_base:
            response["message"] = "知识库未启用、或未指定知识库、或知识库不存在"
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
        """查询网络"""

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
        """重写查询"""
        model_provider = config.model_provider
        model_name = config.model_name
        model = select_model(model_provider=model_provider, model_name=model_name)
        if refs["meta"].get("mode") == "search":  # 如果是搜索模式，就使用 meta 的配置，否则就使用全局的配置
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
        """识别句子中的实体"""
        query = refs.get("rewritten_query", query)
        model_provider = config.model_provider
        model_name = config.model_name
        model = select_model(model_provider=model_provider, model_name=model_name)

        entities = []
        if refs["meta"].get("use_graph"):
            entity_extraction_prompt = entity_template.format(text=query)
            entities = model.predict(entity_extraction_prompt).content.split("<->")
            #entities = [entity for entity in entities if all(char.isalnum() or char in "汉字" for char in entity)]

        return entities

    def __call__(self, query, history, meta):
        refs = self.retrieval(query, history, meta)
        query = self.construct_query(query, refs, meta)
        return query, refs
