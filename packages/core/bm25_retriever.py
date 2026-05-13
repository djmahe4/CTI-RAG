"""
BM25 Retrieval implementation.
Combines vector search and BM25 algorithms for hybrid search.
"""
from typing import List, Dict, Any
import numpy as np
from ..utils import logger
from ..utils.bm25 import create_bm25, AbstractBM25


class HybridRetriever:
    """Hybrid Retrieval: Combines vector search and BM25."""
    
    def __init__(self, vector_weight: float = 0.7, bm25_weight: float = 0.3, language: str = 'english'):
        """
        Initialize Hybrid Retrieval.
        
        Args:
            vector_weight: Weight for vector search results.
            bm25_weight: Weight for BM25 search results.
            language: Language used for BM25 processing ('english' or 'chinese').
        """
        self.vector_weight = vector_weight
        self.bm25_weight = bm25_weight
        self.language = language
        self.bm25: AbstractBM25 = None
        self.doc_id_map: Dict[int, str] = {}
        self.is_trained = False
        
        # Ensure weights sum to 1.0
        total_weight = vector_weight + bm25_weight
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(f"Weights do not sum to 1.0, normalizing: {vector_weight} + {bm25_weight}")
            self.vector_weight = vector_weight / total_weight
            self.bm25_weight = bm25_weight / total_weight
    
    def fit_bm25(self, documents: List[str], document_ids: List[str]):
        """
        Train the BM25 model.
        
        Args:
            documents: List of document texts.
            document_ids: List of document IDs (one-to-one mapping with documents).
        """
        if not documents or not document_ids or len(documents) != len(document_ids):
             logger.warning("BM25 training failed: Documents or IDs are empty, or count mismatch.")
             self.is_trained = False
             return

        self.bm25 = create_bm25(documents, language=self.language)
        self.doc_id_map = {i: doc_id for i, doc_id in enumerate(document_ids)}
        self.is_trained = True
        logger.info(f"BM25 model training complete. Language: {self.language}, Document count: {len(documents)}")
    
    def hybrid_search(self, query: str, vector_results: List[Dict], vector_scores: List[float], top_k: int = 10) -> List[Dict]:
        """
        Perform hybrid search (Vector + BM25).
        
        Args:
            query: User query text.
            vector_results: Results from vector search.
            vector_scores: Scores from vector search.
            top_k: Number of results to return.
            
        Returns:
            List of hybrid search results sorted by combined score.
        """
        if not self.is_trained or self.bm25 is None:
            logger.warning("BM25 model not trained, using vector search only.")
            # Normalize and sort based on vector scores only
            for i, result in enumerate(vector_results):
                result['hybrid_score'] = vector_scores[i] if i < len(vector_scores) else 0.0
            vector_results.sort(key=lambda x: x.get('hybrid_score', 0.0), reverse=True)
            return vector_results[:top_k]
        
        # Get BM25 scores for all documents in corpus
        # BM25 search returns [(doc_index, score), ...]
        bm25_results_indexed = self.bm25.search(query, top_k=len(self.bm25.corpus))
        
        # Convert BM25 indices to doc_ids and store in a dictionary
        bm25_scores_dict = {
            self.doc_id_map.get(doc_index): score 
            for doc_index, score in bm25_results_indexed 
            if doc_index in self.doc_id_map
        }
        
        # Normalize BM25 scores (Min-Max scaling)
        max_bm25_score = max(bm25_scores_dict.values()) if bm25_scores_dict else 1.0
        if max_bm25_score > 0:
            for doc_id in bm25_scores_dict:
                bm25_scores_dict[doc_id] /= max_bm25_score

        # Calculate hybrid scores
        hybrid_results = []
        for i, result in enumerate(vector_results):
            # Ensure entity and file_id exist in the result
            if "entity" not in result or "file_id" not in result["entity"]:
                continue
            doc_id = result["entity"]["file_id"]
            
            vector_score = vector_scores[i] if i < len(vector_scores) else 0.0
            bm25_score = bm25_scores_dict.get(doc_id, 0.0)
            
            # Weighted combination
            hybrid_score = (self.vector_weight * vector_score + 
                          self.bm25_weight * bm25_score)
            
            res_copy = result.copy()
            res_copy["hybrid_score"] = hybrid_score
            res_copy["vector_score"] = vector_score
            res_copy["bm25_score"] = bm25_score
            
            hybrid_results.append(res_copy)
        
        # Sort by combined hybrid score
        hybrid_results.sort(key=lambda x: x["hybrid_score"], reverse=True)
        
        logger.info(f"Hybrid search complete. Vector weight: {self.vector_weight:.2f}, BM25 weight: {self.bm25_weight:.2f}")
        return hybrid_results[:top_k]
    
    def get_config(self) -> Dict[str, Any]:
        """Retrieve the current retriever configuration."""
        return {
            "vector_weight": self.vector_weight,
            "bm25_weight": self.bm25_weight,
            "language": self.language,
            "is_trained": self.is_trained,
            "document_count": self.bm25.doc_count if self.is_trained and self.bm25 else 0
        }
