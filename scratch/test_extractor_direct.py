import asyncio
import os
import sys
from unittest.mock import MagicMock, AsyncMock

# Add project root to path
sys.path.append(os.getcwd())

from packages.core.entity_extractor import EntityExtractor

async def test_entity_extractor():
    # Initialize extractor
    # We need to mock the model before it gets initialized or replace it
    extractor = EntityExtractor()
    
    # Mock result text that the LLM would return
    # Based on the prompt in entity_extractor.py: "entity"DELIMITER"name"DELIMITER"type"DELIMITER"description"
    # and "relationship"DELIMITER"source"DELIMITER"target"DELIMITER"type"DELIMITER"description"
    # with record delimiter "####"
    mock_llm_response = (
        'entity' + extractor.tuple_delimiter + 'APT29' + extractor.tuple_delimiter + 'ORGANIZATION' + extractor.tuple_delimiter + 'A Russian-linked threat actor group.' + extractor.record_delimiter +
        'entity' + extractor.tuple_delimiter + 'Cozy Bear' + extractor.tuple_delimiter + 'ALIAS' + extractor.tuple_delimiter + 'Another name for APT29.' + extractor.record_delimiter +
        'entity' + extractor.tuple_delimiter + 'DiplomaticBackdoor' + extractor.tuple_delimiter + 'MALWARE' + extractor.tuple_delimiter + 'A new malware used in 2024 campaigns.' + extractor.record_delimiter +
        'relationship' + extractor.tuple_delimiter + 'APT29' + extractor.tuple_delimiter + 'Cozy Bear' + extractor.tuple_delimiter + 'AKA' + extractor.tuple_delimiter + 'APT29 is also known as Cozy Bear.' + extractor.record_delimiter +
        'relationship' + extractor.tuple_delimiter + 'APT29' + extractor.tuple_delimiter + 'DiplomaticBackdoor' + extractor.tuple_delimiter + 'USES' + extractor.tuple_delimiter + 'APT29 uses DiplomaticBackdoor malware.'
    )
    
    # Mock the model's generate method
    extractor.model = MagicMock()
    extractor.model.generate = AsyncMock(return_value=mock_llm_response)
    
    test_text = """
    The APT29 group, also known as Cozy Bear, targeted several European government agencies in 2024. 
    They used a new malware called 'DiplomaticBackdoor' which communicated with the domain 'gov-update.net'.
    The malware was delivered via spear-phishing emails exploiting CVE-2023-38831 in WinRAR.
    """
    
    print("Starting entity extraction (MOCKED)...")
    result = await extractor.extract_entities(test_text)
    
    if result["status"] == "success":
        print(f"\nSuccessfully extracted {result['entities_count']} entities and {result['relationships_count']} relationships.")
        
        print("\nEntities:")
        for entity in result["entities"]:
            print(f"- {entity['name']} ({entity['type']}): {entity['description']}")
            
        print("\nRelationships:")
        for rel in result["relationships"]:
            print(f"- {rel['source_ref']} --[{rel['relationship_type']}]--> {rel['target_ref']}")
            
        # Verify specific counts
        assert result['entities_count'] == 3
        assert result['relationships_count'] == 2
        print("\nTest passed: Extraction counts and data structure are correct.")
    else:
        print(f"\nExtraction failed: {result.get('message')}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(test_entity_extractor())
