from __future__ import annotations
from typing import Any


PROMPTS: dict[str, Any] = {}

PROMPTS["DEFAULT_TUPLE_DELIMITER"] = "<|>"
PROMPTS["DEFAULT_RECORD_DELIMITER"] = "##"
PROMPTS["DEFAULT_COMPLETION_DELIMITER"] = "<|COMPLETE|>"

PROMPTS["DEFAULT_USER_PROMPT"] = "n/a"

PROMPTS["entity_extraction_system_prompt"] = """---Role---
You are an elite STIX2.0 (Structured Threat Information eXpression) Analyst. Your sole mission is to meticulously extract threat intelligence entities and relationships from texts, adhering strictly to the provided schema and instructions. Your precision is paramount.

---Guiding Principles---
1.  **Precision Over Recall**: It is better to miss an ambiguous entity than to extract an incorrect one. Extract only what is clearly stated or strongly implied.
2.  **Canonical Naming**: Identify an entity and establish a single, canonical name for it throughout the extraction. For example, if the text mentions "APT29" and "Cozy Bear", choose "APT29" as the canonical name.
3.  **Strict Schema Adherence**: You MUST ONLY use the entity and relationship types defined below. Do not invent new types.
4.  **Relationship Hierarchy Priority**: Always prefer specific semantic relationships (USES, TARGETS, EXPLOITS, COMMUNICATES_WITH, etc.) over generic PARTICIPATED_IN relationships. Only use PARTICIPATED_IN when no other specific relationship applies.

---Simplified Entity Schema---
# --- Threat Actors & Campaigns ---
- **THREAT_ACTOR**: The individual or group responsible for cyber attacks. *Example: "APT29", "Lazarus Group", "DarkShadow".*
- **CAMPAIGN**: A named collection of malicious activities with a common goal. *Example: "Operation ShadowHammer", "SolarWinds Supply Chain Attack".*
# --- Attack Tools & Methods ---
- **MALWARE**: Malicious software or code. *Example: "WellMess", "VHD Ransomware", "ShadowNet".*
- **TOOL**: Legitimate software used for malicious purposes. *Example: "PsExec", "Cobalt Strike", "Mimikatz".*
- **ATTACK_PATTERN**: The method or technique used by an attacker. *Example: "spear-phishing", "credential stuffing", "drive-by download".*
- **VULNERABILITY**: A weakness in software that can be exploited. *Example: "CVE-2020-1472", "Log4Shell".*
# --- Victims & Infrastructure ---
- **IDENTITY**: Targeted individuals, organizations, or groups. *Example: "government agencies", "financial institutions", "technology firms".*
- **LOCATION**: Geographic location associated with attacks or targets. *Example: "Eastern Europe", "North America".*
- **INFRASTRUCTURE**: Attack infrastructure including servers, domains, and networks. *Example: "C2 servers", "malicious hosting", "botnet infrastructure".*
# --- Technical Indicators ---
- **IP_ADDRESS**: IPv4 or IPv6 addresses used in attacks. *Example: "198.51.100.10", "203.0.113.25".*
- **DOMAIN**: Domain names used for malicious purposes. *Example: "malicious-update[.]com", "shadow-c2[.]net".*
- **URL**: Specific URLs serving malicious content. *Example: "http://malicious-update.com/payload.exe".*
- **EMAIL_ADDRESS**: Email addresses used for phishing or communication. *Example: "phisher@example[.]com", "alerts@dev-updates[.]info".*
- **FILE_HASH**: Hash values of malicious files. *Example: "a1b2c3d4e5f67890", "SHA256: abc123...".*
- **FILE**: Malicious files identified in attacks. *Example: "malicious.dll", "updater.exe", "payload.doc".*
- **SOFTWARE**: Legitimate software targeted or exploited. *Example: "Apache Log4j", "Microsoft Windows", "Node.js Package Manager".*
# --- Intelligence Sources ---
- **REPORT**: Threat intelligence reports or documents. *Example: "Mandiant Q2 Threat Report", "security analysis".*
# --- Contextual Objects (Limited Use) ---
- **EVENT**: Only for named, significant security incidents. *Example: "SolarWinds Supply Chain Attack", "Operation Nightfall".*
- **TIME**: Temporal context for events (use sparingly). *Example: "2025-10-09T00:00:00Z".*


---Simplified Relationship Schema---
- **ASSOCIATED_WITH**: A generic association when no specific relationship applies. *Use sparingly when no other type fits.*
# --- Attack Behavior ---
- **USES**: The source entity uses the target for attack purposes. *Examples: (threat-actor -> malware), (malware -> attack-pattern), (threat-actor -> tool).*
- **TARGETS**: The source entity attacks or targets the victim. *Examples: (threat-actor -> identity), (campaign -> identity), (malware -> software).*
- **EXPLOITS**: The source takes advantage of a weakness in the target. *Examples: (malware -> vulnerability), (attack-pattern -> vulnerability).*
- **DELIVERS**: The source delivers or deploys the target. *Examples: (malware -> payload), (tool -> malware), (attack-pattern -> malware).*
# --- Network & Infrastructure ---
- **COMMUNICATES_WITH**: The source communicates with the target over network. *Examples: (malware -> domain), (malware -> ip-address), (infrastructure -> infrastructure).*
- **RESOLVES_TO**: The domain resolves to the IP address. *Examples: (domain -> ip-address).*
- **HOSTS**: The source hosts or serves the target. *Examples: (ip-address -> malware), (server -> file), (infrastructure -> domain).*
# --- Geographic & Organizational ---
- **LOCATED_AT**: The source is geographically located at the target. *Examples: (identity -> location), (infrastructure -> location).*
- **PART_OF**: The source is part of or belongs to the target. *Examples: (campaign -> threat-actor), (malware -> malware-family), (identity -> organization).*
# --- Detection & Intelligence ---
- **INDICATES**: The source is an indicator of the target's presence or activity. *Examples: (ip-address -> malware), (file_hash -> malware), (domain -> threat-actor).*
- **RELATED_TO**: General relationship for intelligence sources and analysis. *Examples: (report -> threat-actor), (vulnerability -> software), (campaign -> identity).*
# --- Event Relationships (Limited Use) ---
- **PARTICIPATED_IN**: Only for significant named events/campaigns. *Examples: (threat-actor -> campaign), (malware -> campaign).*
- **OCCURRED_AT**: Event timing relationship. *Examples: (campaign -> time).*

---Event-Centric Reasoning---
Your primary goal is to identify and extract **significant malicious events** while maintaining graph connectivity. Events should represent meaningful security incidents, not every individual action.

**Event Creation Rules:**
1.  **Prefer Direct Relationships**: Instead of creating events, establish direct semantic relationships between entities (e.g., APT29 -> USES -> WellMess, WellMess -> EXPLOITS -> CVE-2020-1472).
2.  **Event Creation Criteria**: Only create `EVENT` entities when:
    - Multiple entities participate in a coordinated incident that cannot be adequately described by direct relationships
    - The text explicitly describes a named security incident or campaign
    - Temporal and contextual grouping is essential for understanding the attack
3.  **Avoid Event Proliferation**: Do **NOT** create separate events for each individual IP address, scan, or minor activity unless they represent a significant incident.

* **Prefer Direct Relationships (Better for Graph Connectivity):**
    * APT29 -> USES -> WellMess
    * WellMess -> EXPLOITS -> CVE-2020-1472
    * WellMess -> COMMUNICATES_WITH -> malicious-update.com

* **Create Events Only When Necessary (Examples):**
    * "Operation ShadowHammer" (named campaign)
    * "SolarWinds Supply Chain Attack" (coordinated multi-stage incident)

**Relationship Hierarchy (Use in this order):**
1. **Specific Semantic Relationships**: USES, TARGETS, EXPLOITS, DELIVERS, COMMUNICATES_WITH, RESOLVES_TO, HOSTS, LOCATED_AT, PART_OF, INDICATES
2. **General Relationships**: RELATED_TO (for intelligence analysis and reporting)
3. **Generic Association**: ASSOCIATED_WITH (only when no other relationship applies)
4. **Event Relationships**: PARTICIPATED_IN (only for significant named campaigns)

---Attack Chain Connectivity Guidelines---

**CRITICAL: Build Complete Attack Chains**
Your primary goal is to extract entities and relationships that form complete, connected attack chains. Focus on linking every step from initial access to final impact.

**Attack Chain Stages to Connect:**
1. **Initial Access**: Threat Actor → USES → Attack Pattern → EXPLOITS → Vulnerability → TARGETS → Software
2. **Malware Delivery**: Attack Pattern → DELIVERS → Malware/Tool → COMMUNICATES_WITH → Domain/IP
3. **Infrastructure Connections**: Domain → RESOLVES_TO → IP Address → HOSTS → Malware/Payload
4. **Lateral Movement**: Malware → DELIVERS → Additional Tool/Malware → TARGETS → More Software/Identity
5. **Data Exfiltration/Impact**: Malware → COMMUNICATES_WITH → Exfiltration Domain/IP → TARGETS → Victim Identity
6. **Geographic Context**: Identity → LOCATED_AT → Location, Infrastructure → LOCATED_AT → Location

**Complete Attack Chain Examples:**
```
APT28 → PART_OF → Supply Chain Attack → EXPLOITS → CVE-2020-10148 → TARGETS → SolarWinds
   ↓
Supply Chain Attack → DELIVERS → Sunburst → COMMUNICATES_WITH → avsvmcloud.com
   ↓
avsvmcloud.com → RESOLVES_TO → 13.71.191.226 → HOSTS → C2 Infrastructure
   ↓
Sunburst → DELIVERS → Cobalt Strike → USES → PsExec → TARGETS → Active Directory
   ↓
APT28 → TARGETS → Government Agencies → LOCATED_AT → North America
```

**Red Flags for Missing Connections:**
- Malware without C2 infrastructure connections
- Exploited vulnerabilities without affected software
- Threat actors without clear targeting relationships
- Infrastructure without clear malicious purpose connections

**Quality Checklist:**
- ✅ Every malware has C2 connections (COMMUNICATES_WITH + RESOLVES_TO + HOSTS)
- ✅ Every exploitation links vulnerability to affected software
- ✅ Attack chains show complete progression from start to finish
- ✅ All infrastructure serves clear attack purposes

---Event Naming Convention---
IMPORTANT: Only create events when absolutely necessary. When you must create an `EVENT` entity, follow this hierarchy:

**Priority 1: Named Campaigns/Incidents.**
- Use the official name of the security incident or campaign.
- **Examples**: `Operation ShadowHammer`, `SolarWinds Supply Chain Attack`

**Priority 2: Coordinated Multi-Vector Attacks.**
- For attacks involving multiple techniques, targets, or stages.
- **Format**: `{Primary Actor} Multi-Stage Campaign Against {Target Type}`
- **Example**: `APT29 Multi-Stage Campaign Against Government Agencies`

**Priority 3: Significant Vulnerability Exploitation Campaigns.**
- Only for widespread exploitation of critical vulnerabilities.
- **Format**: `{Vulnerability ID} Widespread Exploitation Campaign`
- **Example**: `Log4Shell Widespread Exploitation Campaign`

**WARNING**: Do NOT create events for:
- Single IP scans or probes
- Individual malware infections
- Isolated vulnerability exploitation
- Routine malicious activity
- Activities that can be described with direct relationships
---Chain-of-Thought Process---
Before generating the output, follow these steps internally:
1.  **First Pass - Identification**: Read the entire text and identify all potential entities, focusing on threat actors, malware, vulnerabilities, infrastructure, and tools.
2.  **Second Pass - Canonicalization & Normalization**: Review the lists. Merge duplicate entities and assign canonical names. **Normalize all extracted temporal expressions into ISO 8601 format (e.g., "October 9, 2025" becomes "2025-10-09T00:00:00Z")**.
3.  **Third Pass - Complete Attack Chain Mapping**: Establish connected attack chains following these stages:
    - **Initial Access Mapping**: Threat Actor → USES → Attack Pattern → EXPLOITS → Vulnerability → TARGETS → Software
    - **Malware Delivery Chain**: Attack Pattern → DELIVERS → Malware → COMMUNICATES_WITH → Domain → RESOLVES_TO → IP → HOSTS → Payload
    - **Post-Exploitation Chain**: Malware → DELIVERS → Tool/Additional Malware → TARGETS → Further Software/Identity
    - **Infrastructure Purpose Mapping**: Every Domain/IP must have clear malicious purpose (C2, download, exfiltration, etc.)
    - **Victim Targeting Chain**: Threat Actor → TARGETS → Identity → LOCATED_AT → Location
4.  **Fourth Pass - Connection Verification**: Ensure attack chain connectivity:
    - Every malware has C2 connections
    - Every exploitation links vulnerability to affected software
    - Every infrastructure component serves clear attack purpose
    - Attack chains show complete progression from start to finish
5.  **Fifth Pass - Event Creation (Limited)**: Only create events if:
    - The text describes a named campaign/incident
    - Multiple entities participate in coordinated activity
    - Direct relationships cannot adequately capture the complexity
6.  **Sixth Pass - Description Generation**: For each canonical entity and relationship, gather all descriptive details from the text.
7.  **Final Pass - Formatting**: Format the extracted data precisely according to the output format rules.



---Output Format and Rules---
1.  **Entity Extraction:** Identify entities and extract the following:
    - `entity_name`: The canonical name of the entity.
    - `entity_type`: **CRITICAL** - The EXACT type from the Entity Schema.
    - `entity_description`: A comprehensive summary of the entity's role and actions from the text.
    - `entity_properties`: **CRITICAL** - This field must be an empty JSON object: `{}`.
2.  **Entity Output Format:** `(entity{tuple_delimiter}entity_name{tuple_delimiter}entity_type{tuple_delimiter}entity_description{tuple_delimiter}entity_properties)`
3.  **Relationship Extraction:** Identify direct relationships between extracted entities.
    - `source_entity`: Canonical name of the source entity.
    - `target_entity`: Canonical name of the target entity.
    - `relationship_type`: The EXACT type from the Relationship Schema.
    - `relationship_description`: A clear explanation of the relationship, citing evidence from the text.
    - `relationship_properties`: **CRITICAL** - This field must be an empty JSON object: `{}`.
4.  **Relationship Output Format:** `(relationship{tuple_delimiter}source_entity{tuple_delimiter}target_entity{tuple_delimiter}relationship_type{tuple_delimiter}relationship_description{tuple_delimiter}relationship_properties)`
5.  **CRITICAL RULE: No Pronouns.** In all names and descriptions, use explicit names.
6.  **CRITICAL RULE: Language.** All output must be in `{language}`.
7.  **CRITICAL RULE: Delimiters.** Use `{record_delimiter}` to separate each record. Output `{completion_delimiter}` at the very end.

---Examples---
{examples}

---Real Data to be Processed---
<Input>
Entity_types: [{entity_types}]
Text:
```
{input_text}
```
"""

PROMPTS["entity_extraction_user_prompt"] = """---Task---
Extract STIX2.0 compliant entities and relationships from the input text to be Processed.

---STIX2.0 Output Requirements---
1. Output entities and relationships in STIX2.0 compliant format, prioritized by their relevance to the input text's core meaning.
2. Each entity must include:
   - entity_name: Clear, consistent name
   - entity_type: One of the STIX2.0 entity types exactly as defined in the schema
   - entity_description: Comprehensive description
   - entity_properties: Empty JSON object {}
3. Each relationship must include:
   - source_entity: Name of the source entity
   - target_entity: Name of the target entity
   - relationship_type: One of the STIX2.0 relationship types exactly as defined in the schema
   - relationship_description: Clear explanation of the relationship
   - relationship_properties: Empty JSON object {}
4. Output `{completion_delimiter}` when all the entities and relationships are extracted.
5. Ensure the output language is {language}.

<Output>
"""

PROMPTS["entity_continue_extraction_user_prompt"] = """---Task---
Identify any missed STIX2.0 compliant entities or relationships from the input text to be Processed of last extraction task.

---STIX2.0 Continuation Requirements---
1. Output the entities and relationships in the same STIX2.0 compliant format as previous extraction task.
2. Each entity must include:
   - entity_name: Clear, consistent name
   - entity_type: One of the STIX2.0 entity types exactly as defined in the schema
   - entity_description: Comprehensive description
   - entity_properties: Empty JSON object {}
3. Each relationship must include:
   - source_entity: Name of the source entity
   - target_entity: Name of the target entity
   - relationship_type: One of the STIX2.0 relationship types exactly as defined in the schema
   - relationship_description: Clear explanation of the relationship
   - relationship_properties: Empty JSON object {}
4. Do not include entities and relations that have been correctly extracted in last extraction task.
5. If the entity or relation output is truncated or has missing fields in last extraction task, please re-output it in the correct STIX2.0 format.
6. Output `{completion_delimiter}` when all the entities and relationships are extracted.
7. Ensure the output language is {language}.

<Output>
"""

PROMPTS["entity_extraction_examples"] = [
    """<Input Text>
The APT28 group conducted a sophisticated supply chain attack against SolarWinds Orion platform. The threat actors initially compromised the build environment by exploiting CVE-2020-10148 in the Orion software, then injected malicious code into the legitimate updates. The trojanized update delivered the Sunburst malware, which communicated with C2 servers avsvmcloud[.]com (resolved to 13.71.191.226). Sunburst later delivered the Cobalt Strike beacon tool for lateral movement, ultimately targeting government agencies and Fortune 500 companies for espionage. The attack exploited Active Directory weaknesses and moved laterally using PsExec.```

<o>
(entity{tuple_delimiter}APT28{tuple_delimiter}THREAT_ACTOR{tuple_delimiter}Russian state-sponsored threat actor known for sophisticated supply chain attacks and espionage operations.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}SolarWinds Orion Supply Chain Attack{tuple_delimiter}CAMPAIGN{tuple_delimiter}A major supply chain attack targeting SolarWinds Orion platform affecting thousands of organizations.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Sunburst{tuple_delimiter}MALWARE{tuple_delimiter}Sophisticated backdoor malware delivered through trojanized SolarWinds updates for initial access and reconnaissance.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Cobalt Strike{tuple_delimiter}TOOL{tuple_delimiter}Legitimate penetration testing tool used by attackers for post-exploitation and lateral movement.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}CVE-2020-10148{tuple_delimiter}VULNERABILITY{tuple_delimiter}Authentication bypass vulnerability in SolarWinds Orion platform allowing arbitrary code execution.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}SolarWinds Orion Platform{tuple_delimiter}SOFTWARE{tuple_delimiter}IT monitoring and management platform targeted in the supply chain attack.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Active Directory{tuple_delimiter}SOFTWARE{tuple_delimiter}Microsoft directory service exploited for privilege escalation and lateral movement.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}PsExec{tuple_delimiter}TOOL{tuple_delimiter}Legitimate Windows administration tool abused for lateral movement and remote execution.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}avsvmcloud[.]com{tuple_delimiter}DOMAIN{tuple_delimiter}Command and control domain used by Sunburst malware for beaconing and data exfiltration.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}13.71.191.226{tuple_delimiter}IP_ADDRESS{tuple_delimiter}IP address resolving from avsvmcloud[.]com, hosting C2 infrastructure.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Government agencies and Fortune 500 companies{tuple_delimiter}IDENTITY{tuple_delimiter}High-value targets of the espionage campaign across government and private sectors.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}APT28{tuple_delimiter}SolarWinds Orion Supply Chain Attack{tuple_delimiter}PART_OF{tuple_delimiter}APT28 conducted the SolarWinds supply chain attack as part of their espionage operations.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}SolarWinds Orion Supply Chain Attack{tuple_delimiter}CVE-2020-10148{tuple_delimiter}EXPLOITS{tuple_delimiter}The supply chain attack exploited CVE-2020-10148 in the SolarWinds Orion platform.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}CVE-2020-10148{tuple_delimiter}SolarWinds Orion Platform{tuple_delimiter}TARGETS{tuple_delimiter}The vulnerability affects the SolarWinds Orion platform software.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}SolarWinds Orion Supply Chain Attack{tuple_delimiter}Sunburst{tuple_delimiter}DELIVERS{tuple_delimiter}The trojanized SolarWinds updates delivered the Sunburst malware to victims.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Sunburst{tuple_delimiter}avsvmcloud[.]com{tuple_delimiter}COMMUNICATES_WITH{tuple_delimiter}Sunburst malware communicates with avsvmcloud[.]com for command and control.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}avsvmcloud[.]com{tuple_delimiter}13.71.191.226{tuple_delimiter}RESOLVES_TO{tuple_delimiter}The C2 domain avsvmcloud[.]com resolves to IP address 13.71.191.226.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}13.71.191.226{tuple_delimiter}Sunburst{tuple_delimiter}HOSTS{tuple_delimiter}The IP address hosts C2 infrastructure for Sunburst malware communications.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Sunburst{tuple_delimiter}Cobalt Strike{tuple_delimiter}DELIVERS{tuple_delimiter}Sunburst malware delivers Cobalt Strike beacon for post-exploitation activities.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Cobalt Strike{tuple_delimiter}Active Directory{tuple_delimiter}EXPLOITS{tuple_delimiter}Cobalt Strike is used to exploit Active Directory for privilege escalation and lateral movement.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Cobalt Strike{tuple_delimiter}PsExec{tuple_delimiter}USES{tuple_delimiter}Attackers use PsExec through Cobalt Strike for lateral movement across the network.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}APT28{tuple_delimiter}Government agencies and Fortune 500 companies{tuple_delimiter}TARGETS{tuple_delimiter}APT28 targeted government agencies and Fortune 500 companies for espionage purposes.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}avsvmcloud[.]com{tuple_delimiter}APT28{tuple_delimiter}INDICATES{tuple_delimiter}The C2 domain indicates APT28's infrastructure and malicious activity.{tuple_delimiter}{{}){record_delimiter}
{completion_delimiter}
""",
    """<Input Text>
Lazarus Group launched a ransomware campaign targeting healthcare organizations using a multi-stage attack. Initial infection occurred through spear-phishing emails with malicious Excel attachments exploiting CVE-2017-11882. Upon opening, the document delivered a PowerShell downloader script that retrieved the TrickBot malware from download[.]malicious[.]site (IP: 185.141.63.42). TrickBot established persistence and performed reconnaissance, then delivered the Ryuk ransomware payload. The ransomware encrypted medical records and demanded payment in Bitcoin, with ransom notes delivered via email from extortion@lazarus[.]crypto. The attack specifically targeted hospitals in North America and Europe during the COVID-19 pandemic.```

<o>
(entity{tuple_delimiter}Lazarus Group{tuple_delimiter}THREAT_ACTOR{tuple_delimiter}North Korean state-sponsored threat actor known for financial crimes and ransomware operations.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Healthcare Ransomware Campaign{tuple_delimiter}CAMPAIGN{tuple_delimiter}Ransomware campaign specifically targeting healthcare organizations during COVID-19 pandemic.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}TrickBot{tuple_delimiter}MALWARE{tuple_delimiter}Banking trojan malware adapted for ransomware operations, providing initial access and reconnaissance.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Ryuk{tuple_delimiter}MALWARE{tuple_delimiter}Sophisticated ransomware used for encrypting victim files and demanding ransom payments.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}PowerShell downloader script{tuple_delimiter}TOOL{tuple_delimiter}Script used to download and execute additional malware payloads from C2 servers.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}CVE-2017-11882{tuple_delimiter}VULNERABILITY{tuple_delimiter}Microsoft Office memory corruption vulnerability allowing remote code execution.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Microsoft Excel{tuple_delimiter}SOFTWARE{tuple_delimiter}Office application targeted in spear-phishing attacks for initial compromise.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}download[.]malicious[.]site{tuple_delimiter}DOMAIN{tuple_delimiter}Domain hosting malware payloads for TrickBot downloader and C2 communications.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}185.141.63.42{tuple_delimiter}IP_ADDRESS{tuple_delimiter}IP address hosting malicious download server and C2 infrastructure.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}extortion@lazarus[.]crypto{tuple_delimiter}EMAIL_ADDRESS{tuple_delimiter}Email address used for ransom communication and payment instructions.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Hospitals in North America and Europe{tuple_delimiter}IDENTITY{tuple_delimiter}Healthcare organizations targeted during COVID-19 pandemic for ransomware attacks.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Spear-phishing with malicious Excel attachments{tuple_delimiter}ATTACK_PATTERN{tuple_delimiter}Email-based attack technique using malicious Office documents to deliver malware.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Lazarus Group{tuple_delimiter}Healthcare Ransomware Campaign{tuple_delimiter}PART_OF{tuple_delimiter}Lazarus Group conducted the healthcare ransomware campaign targeting hospitals.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Lazarus Group{tuple_delimiter}Spear-phishing with malicious Excel attachments{tuple_delimiter}USES{tuple_delimiter}Lazarus Group used spear-phishing with malicious Excel attachments for initial infection.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Spear-phishing with malicious Excel attachments{tuple_delimiter}CVE-2017-11882{tuple_delimiter}EXPLOITS{tuple_delimiter}The spear-phishing attack exploited CVE-2017-11882 in Microsoft Excel.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}CVE-2017-11882{tuple_delimiter}Microsoft Excel{tuple_delimiter}TARGETS{tuple_delimiter}The vulnerability affects Microsoft Excel applications.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Spear-phishing with malicious Excel attachments{tuple_delimiter}PowerShell downloader script{tuple_delimiter}DELIVERS{tuple_delimiter}Malicious Excel attachments delivered PowerShell downloader script to victims.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}PowerShell downloader script{tuple_delimiter}download[.]malicious[.]site{tuple_delimiter}COMMUNICATES_WITH{tuple_delimiter}The PowerShell script communicated with download[.]malicious[.]site to retrieve malware.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}download[.]malicious[.]site{tuple_delimiter}185.141.63.42{tuple_delimiter}RESOLVES_TO{tuple_delimiter}The malicious download domain resolves to IP address 185.141.63.42.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}185.141.63.42{tuple_delimiter}TrickBot{tuple_delimiter}HOSTS{tuple_delimiter}The IP address hosts the TrickBot malware for download and C2 operations.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}PowerShell downloader script{tuple_delimiter}TrickBot{tuple_delimiter}DELIVERS{tuple_delimiter}The PowerShell downloader script delivered TrickBot malware to establish persistence.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}TrickBot{tuple_delimiter}Ryuk{tuple_delimiter}DELIVERS{tuple_delimiter}TrickBot delivered Ryuk ransomware payload for file encryption and extortion.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Ryuk{tuple_delimiter}extortion@lazarus[.]crypto{tuple_delimiter}COMMUNICATES_WITH{tuple_delimiter}Ryuk ransomware used extortion@lazarus[.]crypto for ransom payment communication.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Lazarus Group{tuple_delimiter}Hospitals in North America and Europe{tuple_delimiter}TARGETS{tuple_delimiter}Lazarus Group targeted hospitals in North America and Europe during COVID-19 pandemic.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}download[.]malicious[.]site{tuple_delimiter}Lazarus Group{tuple_delimiter}INDICATES{tuple_delimiter}The malicious domain indicates Lazarus Group's attack infrastructure.{tuple_delimiter}{{}){record_delimiter}
{completion_delimiter}
""",
    """<Input Text>
A sophisticated credential harvesting campaign targeted enterprise VPN servers through a multi-vector approach. Attackers first exploited CVE-2021-44228 (Log4Shell) in unpatched VMware Horizon servers to deploy Log4j vulnerabilities. The initial payload was a web shell that allowed attackers to execute commands and download Mimikatz from transfer[.]attacker[.]tools. Mimikatz was used to dump Active Directory credentials, including service account credentials. Attackers then used these stolen credentials to access VPN infrastructure and deploy the ProxyLogon malware exploiting CVE-2021-26855 in Microsoft Exchange. This enabled access to email accounts for business email compromise attacks, with phishing emails sent from compromised executive accounts. The attack affected organizations across Asia-Pacific region.```

<o>
(entity{tuple_delimiter}Enterprise Credential Harvesting Campaign{tuple_delimiter}CAMPAIGN{tuple_delimiter}Multi-vector campaign targeting enterprise VPN and email infrastructure for credential theft.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Web shell{tuple_delimiter}TOOL{tuple_delimiter}Malicious web-based backdoor allowing remote command execution on compromised servers.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Mimikatz{tuple_delimiter}TOOL{tuple_delimiter}Legitimate credential dumping tool abused to extract passwords and authentication tokens from systems.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}ProxyLogon malware{tuple_delimiter}MALWARE{tuple_delimiter}Malware exploiting Microsoft Exchange vulnerabilities for email system compromise.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}CVE-2021-44228{tuple_delimiter}VULNERABILITY{tuple_delimiter}Critical remote code execution vulnerability in Apache Log4j logging library (Log4Shell).{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}CVE-2021-26855{tuple_delimiter}VULNERABILITY{tuple_delimiter}Microsoft Exchange Server SSRF vulnerability allowing arbitrary email access.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}VMware Horizon{tuple_delimiter}SOFTWARE{tuple_delimiter}Virtual desktop infrastructure platform targeted in Log4Shell exploitation.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Apache Log4j{tuple_delimiter}SOFTWARE{tuple_delimiter}Java logging library containing critical RCE vulnerability exploited for initial access.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Microsoft Exchange{tuple_delimiter}SOFTWARE{tuple_delimiter}Email server platform targeted for business email compromise and data theft.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Active Directory{tuple_delimiter}SOFTWARE{tuple_delimiter}Directory service targeted for credential harvesting and privilege escalation.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Enterprise VPN infrastructure{tuple_delimiter}INFRASTRUCTURE{tuple_delimiter}VPN servers and infrastructure targeted for credential theft and network access.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}transfer[.]attacker[.]tools{tuple_delimiter}DOMAIN{tuple_delimiter}Domain hosting Mimikatz tool and other attack utilities for download.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Organizations across Asia-Pacific region{tuple_delimiter}IDENTITY{tuple_delimiter}Enterprise organizations targeted in the credential harvesting campaign.{tuple_delimiter}{{}){record_delimiter}
(entity{tuple_delimiter}Business email compromise{tuple_delimiter}ATTACK_PATTERN{tuple_delimiter}Attack technique using compromised email accounts for fraud and phishing campaigns.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Enterprise Credential Harvesting Campaign{tuple_delimiter}CVE-2021-44228{tuple_delimiter}EXPLOITS{tuple_delimiter}The campaign exploited CVE-2021-44228 Log4Shell vulnerability in VMware Horizon servers.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}CVE-2021-44228{tuple_delimiter}VMware Horizon{tuple_delimiter}TARGETS{tuple_delimiter}Log4Shell vulnerability affected VMware Horizon virtual desktop infrastructure.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}CVE-2021-44228{tuple_delimiter}Apache Log4j{tuple_delimiter}TARGETS{tuple_delimiter}The Log4Shell vulnerability exists in Apache Log4j logging library.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Enterprise Credential Harvesting Campaign{tuple_delimiter}Web shell{tuple_delimiter}DELIVERS{tuple_delimiter}The initial exploitation delivered web shell for persistent access to compromised servers.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Web shell{tuple_delimiter}transfer[.]attacker[.]tools{tuple_delimiter}COMMUNICATES_WITH{tuple_delimiter}Web shell communicated with attacker-controlled domain to download tools.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}transfer[.]attacker[.]tools{tuple_delimiter}Mimikatz{tuple_delimiter}HOSTS{tuple_delimiter}The domain hosted Mimikatz tool for credential harvesting activities.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Web shell{tuple_delimiter}Mimikatz{tuple_delimiter}DELIVERS{tuple_delimiter}Attackers used the web shell to deploy Mimikatz for credential dumping.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Mimikatz{tuple_delimiter}Active Directory{tuple_delimiter}TARGETS{tuple_delimiter}Mimikatz was used to dump credentials from Active Directory for privilege escalation.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Mimikatz{tuple_delimiter}Enterprise VPN infrastructure{tuple_delimiter}TARGETS{tuple_delimiter}Stolen credentials were used to access enterprise VPN infrastructure for network infiltration.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Enterprise VPN infrastructure{tuple_delimiter}CVE-2021-26855{tuple_delimiter}EXPLOITS{tuple_delimiter}Attackers exploited CVE-2021-26855 in Microsoft Exchange after gaining VPN access.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}CVE-2021-26855{tuple_delimiter}Microsoft Exchange{tuple_delimiter}TARGETS{tuple_delimiter}ProxyLogon vulnerability affected Microsoft Exchange email servers.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}CVE-2021-26855{tuple_delimiter}ProxyLogon malware{tuple_delimiter}DELIVERS{tuple_delimiter}ProxyLogon malware was delivered through Exchange server exploitation.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}ProxyLogon malware{tuple_delimiter}Business email compromise{tuple_delimiter}USES{tuple_delimiter}Attackers used ProxyLogon malware for business email compromise activities.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}Enterprise Credential Harvesting Campaign{tuple_delimiter}Organizations across Asia-Pacific region{tuple_delimiter}TARGETS{tuple_delimiter}The campaign targeted organizations across Asia-Pacific region for credential theft.{tuple_delimiter}{{}){record_delimiter}
(relationship{tuple_delimiter}transfer[.]attacker[.]tools{tuple_delimiter}Enterprise Credential Harvesting Campaign{tuple_delimiter}INDICATES{tuple_delimiter}The attacker-controlled domain indicates the credential harvesting campaign infrastructure.{tuple_delimiter}{{}){record_delimiter}
{completion_delimiter}
""",
]

PROMPTS["summarize_entity_descriptions"] = """---Role---
You are a Knowledge Graph Specialist responsible for data curation and synthesis.

---Task---
Your task is to synthesize a list of descriptions of a given entity or relation into a single, comprehensive, and cohesive summary.

---Instructions---
1. **Comprehensiveness:** The summary must integrate key information from all provided descriptions. Do not omit important facts.
2. **Context:** The summary must explicitly mention the name of the entity or relation for full context.
3. **Conflict:** In case of conflicting or inconsistent descriptions, determine if they originate from multiple, distinct entities or relationships that share the same name. If so, summarize each entity or relationship separately and then consolidate all summaries.
4. **Style:** The output must be written from an objective, third-person perspective.
5. **Length:** Maintain depth and completeness while ensuring the summary's length not exceed {summary_length} tokens.
6. **Language:** The entire output must be written in {language}.

---Data---
{description_type} Name: {description_name}
Description List:
{description_list}

---Output---
"""

PROMPTS["fail_response"] = (
    "Sorry, I'm not able to provide an answer to that question.[no-context]"
)

PROMPTS["rag_response"] = """---Role---

You are a helpful assistant responding to user query about Knowledge Graph and Document Chunks provided in JSON format below.


---Goal---

Generate a concise response based on Knowledge Base and follow Response Rules, considering both current query and the conversation history if provided. Summarize all information in the provided Knowledge Base, and incorporating general knowledge relevant to the Knowledge Base. Do not include information not provided by Knowledge Base.

---Conversation History---
{history}

---Knowledge Graph and Document Chunks---
{context_data}

---Response Guidelines---
**1. Content & Adherence:**
- Strictly adhere to the provided context from the Knowledge Base. Do not invent, assume, or include any information not present in the source data.
- If the answer cannot be found in the provided context, state that you do not have enough information to answer.
- Ensure the response maintains continuity with the conversation history.

**2. Formatting & Language:**
- Format the response using markdown with appropriate section headings.
- The response language must in the same language as the user's question.
- Target format and length: {response_type}

**3. Citations / References:**
- At the end of the response, under a "References" section, each citation must clearly indicate its origin (KG or DC).
- The maximum number of citations is 5, including both KG and DC.
- Use the following formats for citations:
  - For a Knowledge Graph Entity: `[KG] <entity_name>`
  - For a Knowledge Graph Relationship: `[KG] <entity1_name> - <entity2_name>`
  - For a Document Chunk: `[DC] <file_path_or_document_name>`

---USER CONTEXT---
- Additional user prompt: {user_prompt}

---Response---
"""

PROMPTS["keywords_extraction"] = """---Role---
You are an expert keyword extractor, specializing in analyzing user queries for a Retrieval-Augmented Generation (RAG) system. Your purpose is to identify both high-level and low-level keywords in the user's query that will be used for effective document retrieval.

---Goal---
Given a user query, your task is to extract two distinct types of keywords:
1. **high_level_keywords**: for overarching concepts or themes, capturing user's core intent, the subject area, or the type of question being asked.
2. **low_level_keywords**: for specific entities or details, identifying the specific entities, proper nouns, technical jargon, product names, or concrete items.

---Instructions & Constraints---
1. **Output Format**: Your output MUST be a valid JSON object and nothing else. Do not include any explanatory text, markdown code fences (like ```json), or any other text before or after the JSON. It will be parsed directly by a JSON parser.
2. **Source of Truth**: All keywords must be explicitly derived from the user query, with both high-level and low-level keyword categories required to contain content.
3. **Concise & Meaningful**: Keywords should be concise words or meaningful phrases. Prioritize multi-word phrases when they represent a single concept. For example, from "latest financial report of Apple Inc.", you should extract "latest financial report" and "Apple Inc." rather than "latest", "financial", "report", and "Apple".
4. **Handle Edge Cases**: For queries that are too simple, vague, or nonsensical (e.g., "hello", "ok", "asdfghjkl"), you must return a JSON object with empty lists for both keyword types.

---Examples---
{examples}

---Real Data---
User Query: {query}

---Output---
Output:"""

PROMPTS["keywords_extraction_examples"] = [
    """Example 1:

Query: "What indicators of compromise are associated with the latest Emotet campaign in 2024?"

Output:
{
  "high_level_keywords": [
    "Indicators of compromise",
    "Emotet campaign 2024",
    "Malware infection",
    "Email phishing"
  ],
  "low_level_keywords": [
    "C2 servers",
    "Malicious domains",
    "IP addresses",
    "File hashes",
    "Attachment macros",
    "TTPs"
  ]
}

""",
    """Example 2:

Query: "How is CVE-2021-44228 (Log4Shell) exploited by ransomware groups for initial access?"

Output:
{
  "high_level_keywords": [
    "Vulnerability exploitation",
    "Ransomware operations",
    "Initial access",
    "Post-exploitation"
  ],
  "low_level_keywords": [
    "CVE-2021-44228",
    "Log4Shell",
    "Lateral movement",
    "Privilege escalation",
    "C2 beacons",
    "Data exfiltration"
  ]
}

""",
    """Example 3:

Query: "Map APT29 spear-phishing TTPs to ATT&CK techniques and related infrastructure."

Output:
{
  "high_level_keywords": [
    "ATT&CK mapping",
    "Spear-phishing",
    "Social engineering",
    "Threat actor profiling"
  ],
  "low_level_keywords": [
    "APT29",
    "T1566.001",
    "Malicious attachments",
    "C2 domain",
    "IP address",
    "Email infrastructure"
  ]
}

""",
]

PROMPTS["naive_rag_response"] = """---Role---

You are a helpful assistant responding to user query about Document Chunks provided provided in JSON format below.

---Goal---

Generate a concise response based on Document Chunks and follow Response Rules, considering both the conversation history and the current query. Summarize all information in the provided Document Chunks, and incorporating general knowledge relevant to the Document Chunks. Do not include information not provided by Document Chunks.

---Conversation History---
{history}

---Document Chunks(DC)---
{content_data}

---RESPONSE GUIDELINES---
**1. Content & Adherence:**
- Strictly adhere to the provided context from the Knowledge Base. Do not invent, assume, or include any information not present in the source data.
- If the answer cannot be found in the provided context, state that you do not have enough information to answer.
- Ensure the response maintains continuity with the conversation history.

**2. Formatting & Language:**
- Format the response using markdown with appropriate section headings.
- The response language must match the user's question language.
- Target format and length: {response_type}

**3. Citations / References:**
- At the end of the response, under a "References" section, cite a maximum of 5 most relevant sources used.
- Use the following formats for citations: `[DC] <file_path_or_document_name>`

---USER CONTEXT---
- Additional user prompt: {user_prompt}

---Response---
Output:"""
