import asyncio
from typing import List, Dict, Optional, Any

from .. import config, executor
from ..utils import logger
from .entity_extractor import entity_extractor
from .. import knowledge_base

class KnowledgeBaseEntityService:
    """Substantive services of the knowledge base
    
    Provide functionality for extracting entities from knowledge base files
    """
    
    @staticmethod
    async def extract_entities_from_file(db_id: str, 
                                        file_id: str, 
                                        language: str = "chinese",
                                        entity_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """Drawing entities from files in the knowledge base
        
        Args:
            db_id: Knowledge baseID
            file_id: DocumentationID
            language: Ripping Language，Default aschinese
            entity_types: List of entities type to extract，Extract all types for empty
            
        Returns:
            Dictionary containing entities and relationships
        """
        # Validate knowledge base and documents
        validation_result = await KnowledgeBaseEntityService._validate_db_and_file(db_id, file_id)
        if validation_result["status"] == "failed":
            return validation_result
            
        file_info = validation_result["file_info"]
        
        # Text segments to get files
        chunks_result = await KnowledgeBaseEntityService._get_file_chunks(db_id, file_id)
        if chunks_result["status"] == "failed":
            return chunks_result
            
        combined_text = chunks_result["combined_text"]
        
        # Drawing entity
        extraction_result = await entity_extractor.extract_entities(
            text=combined_text,
            language=language,
            entity_types=entity_types
        )
        
        # Merge Results
        return {
            **extraction_result,
            "db_id": db_id,
            "file_id": file_id,
            "file_name": file_info.get("filename", "Unknown")
        }
    
    @staticmethod
    async def _validate_db_and_file(db_id: str, file_id: str) -> Dict[str, Any]:
        """Verify the existence and relevance of the knowledge base and documents
        
        Args:
            db_id: Knowledge baseID
            file_id: DocumentationID
            
        Returns:
            Authentication Results，Include status and file information
        """
        loop = asyncio.get_event_loop()
        
        # Verify the existence of the knowledge base
        db_info = await loop.run_in_executor(
            executor,
            lambda: knowledge_base.get_kb_by_id(db_id)
        )
        
        if not db_info:
            return {"status": "failed", "message": f"The knowledge base does not exist: {db_id}"}
        
        # Verify whether the file exists
        file_info = await loop.run_in_executor(
            executor,
            lambda: knowledge_base.get_file_by_id(file_id)
        )
        
        if not file_info:
            return {"status": "failed", "message": f"File does not exist: {file_id}"}
        
        # Verify whether the document belongs to that knowledge Library
        if file_info.get("database_id") != db_id:
            return {"status": "failed", "message": "File does not belong to the specified knowledge base"}
        
        return {"status": "success", "file_info": file_info}
    
    @staticmethod
    async def _get_file_chunks(db_id: str, file_id: str) -> Dict[str, Any]:
        """FromMilvusText segments to get files
        
        Args:
            db_id: Knowledge baseID
            file_id: DocumentationID
            
        Returns:
            Dictionary containing consolidated text
        """
        loop = asyncio.get_event_loop()
        
        # Query all segments of the file
        chunks = await loop.run_in_executor(
            executor,
            lambda: knowledge_base.client.query(
                collection_name=db_id,
                filter=f"file_id == '{file_id}'",
                output_fields=["text", "start_char_idx"]
            )
        )
        
        if not chunks:
            return {"status": "failed", "message": f"Documentation {file_id} Yes.MilvusNo partition found in"}
        
        # Sort segments according to start char idx
        chunks.sort(key=lambda x: x.get("start_char_idx") or 0)
        
        # Merge all text segments
        chunks_sorted = sorted(chunks, key=lambda x: x.get("start_char_idx") or 0)
        combined_text = " ".join([chunk["text"] for chunk in chunks_sorted]).strip()
        
        return {
            "status": "success", 
            "combined_text": combined_text, 
            "chunks_count": len(chunks)
        }

# Create global instance
kb_entity_service = KnowledgeBaseEntityService()
