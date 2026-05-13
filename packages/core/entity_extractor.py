import json
import asyncio
import os
import traceback
import uuid
from typing import List, Dict, Optional, Tuple, Any

from .. import config
from ..core.constant import STIX_ENTITY_TYPES
from ..utils import logger
from ..models.chat_model import CustomModel
from .prompt import PROMPTS
from dotenv import load_dotenv

load_dotenv()


class EntityExtractor:
    """STIX Entity Extractor
    
    Extracts STIX entities and relationships from text in a structured format.
    """
    
    def __init__(self, model_config: Optional[Dict] = None):
        """Initialize the entity extractor.
        
        Args:
            model_config: Model configuration including name, api_base, and api_key.
        """
        self.model_config = model_config or {
            "name": os.getenv("MODEL_NAME"),
            "api_base": os.getenv("DASHSCOPE_BASE_URL"),
            "api_key": os.getenv("DASHSCOPE_API_KEY")
        }
        logger.info(f"Entity extraction model configuration: {self.model_config}")
        self.model = CustomModel(self.model_config)
        
        # Load prompt templates
        self.system_prompt_template = PROMPTS["entity_extraction_system_prompt"]
        self.user_prompt_template = PROMPTS["entity_extraction_user_prompt"]
        self.examples = PROMPTS["entity_extraction_examples"]
        
        # Define delimiters
        self.tuple_delimiter = PROMPTS["DEFAULT_TUPLE_DELIMITER"]
        self.record_delimiter = PROMPTS["DEFAULT_RECORD_DELIMITER"]
        self.completion_delimiter = PROMPTS["DEFAULT_COMPLETION_DELIMITER"]
    
    def prepare_prompt(self, 
                       text: str, 
                       language: str = "english",
                       entity_types: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """Prepare prompts for entity extraction.
        
        Args:
            text: Input text for extraction.
            language: Target language for extraction (default is 'english').
            entity_types: List of STIX entity types to extract (extracts all if empty).
        
        Returns:
            List of formatted message dictionaries (system and user roles).
        """
        # Set entity type filter
        entity_types_str = ",".join(entity_types or list(STIX_ENTITY_TYPES.keys()))
        
        # Build system prompt from template
        system_prompt = self.system_prompt_template
        
        # Replace placeholders
        system_prompt = system_prompt.replace("{examples}", "\n".join(self.examples))
        system_prompt = system_prompt.replace("{entity_types}", entity_types_str)
        system_prompt = system_prompt.replace("{input_text}", text)
        system_prompt = system_prompt.replace("{language}", language)
        system_prompt = system_prompt.replace("{tuple_delimiter}", self.tuple_delimiter)
        system_prompt = system_prompt.replace("{record_delimiter}", self.record_delimiter)
        system_prompt = system_prompt.replace("{completion_delimiter}", self.completion_delimiter)
        
        # Build user prompt from template
        user_prompt = self.user_prompt_template
        user_prompt = user_prompt.replace("{completion_delimiter}", self.completion_delimiter)
        user_prompt = user_prompt.replace("{language}", language)
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
    
    async def extract_entities(self, 
                              text: str, 
                              language: str = "english",
                              entity_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """Extract STIX entities and relationships from text and parse results.
        
        Args:
            text: Input text for extraction.
            language: Target language for extraction (default is 'english').
            entity_types: List of STIX entity types to extract (extracts all if empty).
        
        Returns:
            Dictionary containing extracted entities and relationships.
        """
        try:
            messages = self.prepare_prompt(text, language, entity_types)
            response = self.model.predict(messages)
            content = response.content if hasattr(response, 'content') else str(response)
            
            entities, relationships = self.parse_result(content)
            
            return {
                "status": "success",
                "entities": entities,
                "relationships": relationships,
                "entities_count": len(entities),
                "relationships_count": len(relationships),
                "raw_content": content
            }
            
        except Exception as e:
            logger.error(f"Entity extraction failed: {e}, {traceback.format_exc()}")
            return {
                "status": "failed",
                "message": f"Entity extraction failed: {str(e)}",
                "entities": [],
                "relationships": [],
                "entities_count": 0,
                "relationships_count": 0
            }

    def parse_result(self, result_text: str) -> Tuple[List[Dict], List[Dict]]:
        """Parsing LLM result text returned, extracting entities and relationships
        
        Args:
            result_text: LLM result text returned
            
        Returns:
            Tuple containing entities and relationships (entities, relationships)
        """
        entities = []
        relationships = []
        
        logger.info(f"Start parsing results, Separator: record='{self.record_delimiter}', tuple='{self.tuple_delimiter}'")
        lines = result_text.split(self.record_delimiter)
        logger.info(f"Number of result lines: {len(lines)}")
        
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or line == self.completion_delimiter:
                continue
                
            parts = line.split(self.tuple_delimiter)
            
            try:
                if parts[0].startswith("(entity"):
                    # Format: (entity, name, type, description, properties)
                    if len(parts) >= 4:
                        # Clean prefix if needed
                        name = parts[1].strip()
                        raw_type = parts[2].strip()
                        description = parts[3].strip()
                        
                        stix_type = self._validate_and_convert_stix_type(raw_type)
                        stix_id = f"{stix_type}--{str(uuid.uuid4())}"

                        entity = {
                            "id": stix_id,
                            "type": stix_type,
                            "name": name,
                            "description": description
                        }
                        
                        # Parse properties if available
                        if len(parts) >= 5:
                            try:
                                props = parts[4].strip()
                                if props.endswith(")"): props = props[:-1]
                                entity["properties"] = json.loads(props) if props else {}
                            except:
                                entity["properties"] = {}
                        else:
                            entity["properties"] = {}

                        entities.append(entity)
                        
                elif parts[0].startswith("(relationship"):
                    # Format: (relationship, source, target, type, description, properties)
                    if len(parts) >= 6:
                        source = parts[1].strip()
                        target = parts[2].strip()
                        rel_type = parts[3].strip()
                        description = parts[4].strip()
                        
                        rel_id = f"relationship--{str(uuid.uuid4())}"
                        
                        rel = {
                            "id": rel_id,
                            "type": "relationship",
                            "source_ref": source,
                            "target_ref": target,
                            "relationship_type": rel_type.lower(),
                            "description": description
                        }
                        
                        try:
                            props = parts[5].strip()
                            if props.endswith(")"): props = props[:-1]
                            rel["properties"] = json.loads(props) if props else {}
                        except:
                            rel["properties"] = {}
                            
                        relationships.append(rel)
            except Exception as e:
                logger.error(f"Parsing error: {e}, Content: {line}")
        
        return entities, relationships
    
    def _validate_and_convert_stix_type(self, entity_type: str) -> str:
        """Validate and convert entity type to STIX standard format.
        
        Args:
            entity_type: Original entity type string.
            
        Returns:
            Standardized STIX entity type.
        """
        if not entity_type or not isinstance(entity_type, str):
            return "other"
        
        entity_type = entity_type.strip().upper()
        
        # Direct match in constants
        if entity_type in STIX_ENTITY_TYPES:
            return STIX_ENTITY_TYPES[entity_type]
        
        # Check against values
        for key, value in STIX_ENTITY_TYPES.items():
            if entity_type == value.upper():
                return value
        
        # Fuzzy matching for common variations
        type_mapping = {
            "MALWARE": "malware",
            "THREAT_ACTOR": "threat-actor", 
            "THREATACTOR": "threat-actor",
            "ATTACK_PATTERN": "attack-pattern",
            "ATTACKPATTERN": "attack-pattern",
            "INDICATOR": "indicator",
            "VULNERABILITY": "vulnerability",
            "CVE": "vulnerability",
            "FILE": "file",
            "PROCESS": "process",
            "NETWORK_TRAFFIC": "network-traffic",
            "EMAIL_MESSAGE": "email-message",
            "USER_ACCOUNT": "user-account",
            "SOFTWARE": "software",
            "REPORT": "report",
            "CAMPAIGN": "campaign",
            "INTRUSION_SET": "intrusion-set",
            "COURSE_OF_ACTION": "course-of-action",
            "COA": "course-of-action",
            "DIRECTORY": "directory",
            "REGISTRY_KEY": "registry-key",
            "IP": "network-traffic",
            "IP_ADDRESS": "network-traffic",
            "URL": "network-traffic",
            "DOMAIN": "network-traffic",
            "HASH": "file",
        }
        
        for key, value in type_mapping.items():
            if key in entity_type or entity_type in key:
                return value
        
        logger.warning(f"Unidentified entity type: {entity_type}, defaulting to 'other'")
        return "other"

# Create global instance
entity_extractor = EntityExtractor()
