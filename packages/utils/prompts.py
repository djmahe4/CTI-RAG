from datetime import datetime


def get_system_prompt():
    return f"""Current Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
You are a professional threat intelligence analysis assistant, specializing in helping users analyze network security threats, malware, attack patterns, and related issues.
Your responsibilities:
1. Answer user questions based on the provided knowledge base information.
2. Provide accurate and professional threat intelligence analysis.
3. If no relevant information is found in the knowledge base, state so clearly.
4. Always maintain a professional and objective attitude.
Please provide detailed and accurate answers based on the user's question and the provided context."""


knowbase_qa_template = """
Please answer the question using the queried information. When answering, avoid excessive bullet-point lists.
<References>:
{external}
</References>
<Question>
{query}
</Question>"
"""

rewritten_query_prompt_template = """
<Instruction>Optimize and rewrite the question based on the provided historical information. The returned question must strictly comply with the following content and format requirements. No prohibited content is allowed.<Instruction>
<Prohibited>1. Absolutely do not fabricate irrelevant content. If it cannot be rewritten or needs no rewriting, return the original question.
2. Return only the question; do not return any other content.
3. Any content you receive is for rewriting purposes; do not answer the question itself.<Prohibited>
<Content Requirements>1. Clarity: The sentence should be clear and avoid vague expressions.
2. Keyword Richness: Use relevant keywords and terminology to help the system better understand the query intent.
3. Conciseness: Avoid long sentences; use concise phrases where possible.
4. Question Form: Using a question form better guides the system to provide an answer.
5. Historical Information Usage: Only select historical information relevant to the current query. If there is no relevant content in history, do not use it, ensuring the query is targeted.
6. Absolutely do not fabricate content.<Content Requirements>
<Format Requirements>Return only the generated sentence. No other text or processing explanations allowed.<Format Requirements>
<History>{history}</History>
<Question>{query}</Question>
"""

rewritten_query_prompt_template2 = """
You are a query assistant. Please rewrite the latest question based on the conversation history into multiple relevant search queries to match reference materials from the knowledge base.
<History>{history}</History>
<Question>{query}</Question>
"""

entity_extraction_prompt_template = """
<Instruction>Perform Named Entity Recognition (NER) on the following text. Return the identified entities and their types.<Instruction>
<Prohibited>1. Absolutely do not fabricate irrelevant content. If no entities exist, return empty content without additional text.
2. Any content you receive is for NER purposes; do not answer the content at any time.<Prohibited>
<Content Requirements>1. Identify all named entities.
2. Do not provide explanations for entities.
3. Return only the entities; do not return any other content.
4. Separate returned entities with commas.<Content Requirements>
<Text>{text}</Text>
"""

keywords_prompt_template = """
You are a query assistant. Please extract keywords from the following text and return them.
Keywords are used to retrieve useful information from the Knowledge Graph, so they must have clear meanings. Use keywords that effectively index relevant entities/relationships in the graph.
Separate entities with <->. Example: Keyword1<->Keyword2<->Keyword3
Do not change the language of the keywords.
<Text>{text}</Text>
"""

HYDE_PROMPT_TEMPLATE = (
    "Please write a passage to answer the question\n"
    "Try to include as many key details as possible.\n"
    "\n"
    "\n"
    "{context_str}\n"
    "\n"
    "{query}\n"
    "\n"
    'Passage:\n'
)

cypher_generation_template = """
Task: Generate a Cypher query based on the provided Graph Database Schema and user question.
**1. Graph Database Schema:**
The following are the node labels, relationship types, and properties you can use. You must strictly follow this schema to build the query.
{schema}
**2. Instructions:**
- **Only use labels, relationships, and properties that exist in the Schema**. Do not fabricate non-existent names.
- Generate an **accurate** Cypher query based on the user question and entities found in relevant documents.
- The goal of the query is to find entities and relationship paths most relevant to the question.
- Prioritize using `MATCH` statements for pattern matching.
- For entity name matching, use `WHERE n.name IN [...]` or `WHERE n.name = '...'` for higher efficiency.
- The query should return paths or specific nodes/relationships that reveal connections between entities.
- **Do not** use any comments in the final Cypher statement.
- If a meaningful query cannot be generated based on the question, return an empty string.
**3. Context Information:**
- **User Question:** "{question}"
- **Entities found in relevant documents:** [{entities}]
**4. Query Examples:**
- **Question:** "What is the type of IP address '1.2.3.4'?"
  - **Cypher:** `MATCH (n:Entity {{name: '1.2.3.4'}}) RETURN n.type AS type`
- **Question:** "What is the connection between 'APT41' and 'malware-uuid-123'?"
  - **Cypher:** `MATCH p = (a:Entity)-[*..3]-(b:Entity) WHERE a.name = 'APT41' AND b.name = 'malware-uuid-123' RETURN p LIMIT 5`
- **Question:** "Which attack groups exploited the 'Log4Shell' vulnerability?"
  - **Cypher:** `MATCH p = (group:Entity)-[:USES]->(tool:Entity)-[:EXPLOITS]->(vuln:Entity {name: 'Log4Shell'}) WHERE group.type = 'Intrusion Set' RETURN p LIMIT 5`
**5. Cypher Query:**
Please generate the Cypher query statement below. Return only the query itself, without any additional explanations or formatting.
```cypher
"""
