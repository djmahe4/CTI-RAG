# ==============================================================================
# Revised Entity Types (Reference STIX 2.1 Core Objects)
# ==============================================================================
STIX_ENTITY_TYPES = {
    # Threat Actors & Campaigns
    "THREAT_ACTOR": "threat-actor",          # Threat Actor (substitutes ATTACK_ORGANIZATION)
    "INTRUSION_SET": "intrusion-set",        # Intrusion Set
    "CAMPAIGN": "campaign",                  # Campaign (New)

    # TTPs & Malware
    "ATTACK_PATTERN": "attack-pattern",      # Attack Pattern (TTPs, critical)
    "MALWARE": "malware",                    # Malware
    "TOOL": "tool",                          # Tool (Legitimate or malicious software used in attacks)
    "PAYLOAD": "payload",                    # Payload

    # Vulnerabilities & Indicators
    "VULNERABILITY": "vulnerability",        # Vulnerability (CVE is an instance)
    "INDICATOR": "indicator",                # Indicator (e.g., "IP 1.2.3.4 is C2 server")

    # Response & Information
    "COURSE_OF_ACTION": "course-of-action",  # Course of Action (New)
    "IDENTITY": "identity",                  # Identity Information
    "LOCATION": "location",                  # Location (New)
    "REPORT": "report",                      # Report (New, used to group related intelligence)

    # Cyber Observables (SCOs)
    "ARTIFACT": "artifact",                  # Binary objects like files and payloads
    "FILE": "file",                          # File
    "FILE_HASH": "file-hash",                # File Hash (New for unified management of MD5, SHA, etc.)
    "IP_ADDRESS": "ipv4-addr",               # IP Address (STIX standard ipv4-addr/ipv6-addr)
    "DOMAIN": "domain-name",                 # Domain Name
    "SOFTWARE": "software",                  # Software (OS, middleware, etc.)
}

# ==============================================================================
# Revised Relationship Types (Reference STIX 2.1 Core Relationships)
# ==============================================================================
REVISED_STIX_RELATIONSHIPS = {
    # Core Common Relationships
    "RELATED_TO": "related-to",              # General relationship between two objects
    
    # Attribution & Subordination
    "ATTRIBUTED_TO": "attributed-to",        # Attribution (e.g., Intrusion Set to Threat Actor)
    "PART_OF": "part-of",                    # Part-of relationship (New)
    "DERIVED_FROM": "derived-from",          # Origin relationship (e.g., Indicator from Observed Data)
    
    # Behavior & Capability Relationships
    "USES": "uses",                          # Usage (e.g., Threat Actor uses Malware/Tool/Attack Pattern)
    "TARGETS": "targets",                    # Targeting (e.g., Intrusion Set targets Identity/Location)
    "EXPLOITS": "exploits",                  # Exploitation (e.g., Malware exploits Vulnerability)
    "DELIVERS": "delivers",                  # Delivery (e.g., Malware delivers another Malware)
    
    # Indication & Positioning Relationships
    "INDICATES": "indicates",                # Indication (e.g., Indicator indicates Malware/Intrusion Set)
    "LOCATED_AT": "located-at",              # Location positioning (e.g., Identity located at Location)
    
    # Network & Host Relationships
    "COMMUNICATES_WITH": "communicates-with",# Communication (e.g., Malware communicates with IP Address)
    "CONNECTS_TO": "connects-to",            # Connection (e.g., IP Address connects to IP Address)
    "RESOLVES_TO": "resolves-to",            # Resolution (e.g., Domain resolves to IP Address)
    "HOSTS": "hosts",                        # Hosting (e.g., Server hosts Malware)
    
    # Containment Relationships
    "CONTAINS": "contains",                  # Inclusion (e.g., Report/Object contains Observable)
    "HAS_WEAKNESS": "has-weakness",          # Weakness (e.g., Software has weakness)
}

# STIX 2.0 Entity Property Keywords (Common Properties)
STIX_COMMON_PROPERTIES = {
    "ID": "id",  # Unique identifier (e.g., attack-pattern--xxxx)
    "TYPE": "type",  # Entity type (corresponds to STIX_ENTITY_TYPES)
    "NAME": "name",  # Entity name
    "DESCRIPTION": "description",  # Entity description
}

# Entity Extraction Constants
ENTITY_EXTRACTION = {
    "MIN_CONFIDENCE": 0.7,  # Minimum confidence threshold for entity extraction
    "MAX_ENTITIES_PER_DOC": 100,  # Maximum number of entities to extract per document
    "STIX_ENTITY_PATTERNS": {
        # Regex patterns for STIX entities (aiding NLP extraction)
        "VULNERABILITY": r"CVE-\d{4}-\d{4,7}",  # CVE vulnerability pattern
        "FILE": r"[a-zA-Z0-9_]+\.(exe|dll|docx|pdf)",  # Common filename pattern
    }
}