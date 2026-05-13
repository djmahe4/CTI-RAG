import os
import json
import warnings
import traceback
import re

from neo4j import GraphDatabase as GD

from .. import config
from ..utils import logger
from ..models import select_model

warnings.filterwarnings("ignore", category=UserWarning)


UIE_MODEL = None

class GraphDatabase:
    def __init__(self):
        self.driver = None
        self.files = []
        self.status = "closed"
        self.kgdb_name = "neo4j"
        self.embed_model_name = None
        self.work_dir = os.path.join(config.save_dir, "knowledge_graph", self.kgdb_name)
        os.makedirs(self.work_dir, exist_ok=True)

        # Try loading saved graph database information
        if not self.load_graph_info():
            logger.info(f"No saved graph database information found; creating a new configuration.")

        self.start()

    def start(self):
        if not config.enable_knowledge_graph or not config.enable_knowledge_base:
            return
        uri = os.environ.get("NEO4J_URL", "bolt://localhost:7688")
        username = os.environ.get("NEO4J_USERNAME", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "12345678")
        logger.info(f"Connecting to Neo4j at {uri} with database {self.kgdb_name}")
        try:
            # Neo4j connection URL should not contain database names
            self.driver = GD.driver(uri, auth=(username, password))

            # Test Connection
            with self.driver.session(database=self.kgdb_name) as session:
                session.run("RETURN 1")

            self.status = "open"
            logger.info(f"Connected to Neo4j at {uri} with database {self.kgdb_name}")
            # Save graph database info after successful connection
            self.save_graph_info(self.kgdb_name)
        except Exception as e:
            logger.error(f"Failed to connect to Neo4j: {e}")
            logger.error(f"Connection details: URI={uri}, Database={self.kgdb_name}, Username={username}")
            config.enable_knowledge_graph = False

    def close(self):
        """Close database connection."""
        self.driver.close()

    def is_running(self):
        """Check if the graph database is running."""
        if not config.enable_knowledge_graph or not config.enable_knowledge_base:
            return False
        else:
            return self.status == "open"

    def get_sample_nodes(self, kgdb_name='neo4j', num=50):
        """Get sample node information from the specified database."""
        self.use_database(kgdb_name)
        def query(tx, num):
            result = tx.run("MATCH (n)-[r]->(m) RETURN n, r, m LIMIT $num", num=int(num))
            return result.values()

        with self.driver.session(database=self.kgdb_name) as session:
            return session.execute_read(query, num)

    def create_graph_database(self, kgdb_name):
        """Create a new database; if it already exists, return the existing database name."""
        # Connect to the system database to manage databases
        with self.driver.session(database="system") as session:
            existing_databases = session.run("SHOW DATABASES")
            existing_db_names = [db['name'] for db in existing_databases]

            if kgdb_name in existing_db_names:
                print(f"Database '{kgdb_name}' already exists.")
                return kgdb_name

            session.run(f"CREATE DATABASE {kgdb_name}")
            print(f"Database '{kgdb_name}' created successfully.")
            return kgdb_name  # Return the created database name

    def use_database(self, kgdb_name="neo4j"):
        """Switch to the specified database."""
        assert kgdb_name == self.kgdb_name, f"Input database name '{kgdb_name}' does not match current instance database name '{self.kgdb_name}'."
        if self.status == "closed":
            self.start()

    def txt_add_entity(self, triples, kgdb_name='neo4j'):
        """Add entity triples."""
        self.use_database(kgdb_name)
        def create(tx, triples):
            for triple in triples:
                h = triple['h']
                t = triple['t']
                r = triple['r']
                query = (
                    "MERGE (a:Entity {name: $h}) "
                    "MERGE (b:Entity {name: $t}) "
                    "MERGE (a)-[:" + r.replace(" ", "_") + "]->(b)"
                )
                tx.run(query, h=h, t=t)

        with self.driver.session(database=self.kgdb_name) as session:
            session.execute_write(create, triples)

    async def txt_add_vector_entity(self, triples, kgdb_name='neo4j'):
        """Add entity triples with vector embeddings."""
        def _index_exists(tx, index_name):
            """Check if the index exists."""
            result = tx.run("SHOW INDEXES")
            for record in result:
                if record["name"] == index_name:
                    return True
            return False

        def _create_graph(tx, data):
            """Add triples to the graph."""
            for entry in data:
                # Check if it's an entity type relationship
                if entry['r'] == 'IS_TYPE':
                    # Add type property to entity nodes
                    tx.run("""
                    MERGE (h:Entity {name: $h})
                    SET h.type = $t
                    MERGE (t:Entity {name: $t})
                    MERGE (h)-[r:RELATION {type: $r}]->(t)
                    """, h=entry['h'], t=entry['t'], r=entry['r'])
                else:
                    # Regular relationship
                    tx.run("""
                    MERGE (h:Entity {name: $h})
                    MERGE (t:Entity {name: $t})
                    MERGE (h)-[r:RELATION {type: $r}]->(t)
                    """, h=entry['h'], t=entry['t'], r=entry['r'])

        def _create_vector_index(tx, dim):
            """Create a vector index."""
            index_name = "entityEmbeddings"
            if not _index_exists(tx, index_name):
                tx.run(f"""
                CREATE VECTOR INDEX {index_name}
                FOR (n: Entity) ON (n.embedding)
                OPTIONS {{indexConfig: {{
                `vector.dimensions`: {dim},
                `vector.similarity_function`: 'cosine'
                }} }};
                """)

        def _get_nodes_without_embedding(tx, entity_names):
            """Get nodes lacking embeddings."""
            # Build parameter dictionary for batch processing
            params = {f"param{i}": name for i, name in enumerate(entity_names)}

            # Build query parameter placeholders
            param_placeholders = ", ".join([f"${key}" for key in params.keys()])

            # Execute query
            result = tx.run(f"""
            MATCH (n:Entity)
            WHERE n.name IN [{param_placeholders}] AND n.embedding IS NULL
            RETURN n.name AS name
            """, **params)

            return [record["name"] for record in result]

        def _batch_set_embeddings(tx, entity_embedding_pairs):
            """Batch update entity embeddings."""
            for entity_name, embedding in entity_embedding_pairs:
                tx.run("""
                MATCH (e:Entity {name: $name})
                CALL db.create.setNodeVectorProperty(e, 'embedding', $embedding)
                """, name=entity_name, embedding=embedding)

        # Check if the model name matches
        cur_embed_info = config.embed_model_names[config.embed_model]
        self.embed_model_name = self.embed_model_name or cur_embed_info.get('name')
        assert self.embed_model_name == cur_embed_info.get('name') or self.embed_model_name is None, \
            f"embed_model_name={self.embed_model_name}, expected {cur_embed_info.get('name')}"

        try:
            self.use_database(kgdb_name)
            logger.info(f"Starting to add {len(triples)} triples to Neo4j database: {kgdb_name}")
            
            with self.driver.session(database=self.kgdb_name) as session:
                logger.info(f"Adding entities to {kgdb_name}")
                session.execute_write(_create_graph, triples)
                logger.info(f"Creating vector index for {kgdb_name} using {config.embed_model}")
                session.execute_write(_create_vector_index, cur_embed_info['dimension'])

                # Collect and deduplicate entity names
                all_entities = []
                for entry in triples:
                    if entry['h'] not in all_entities:
                        all_entities.append(entry['h'])
                    if entry['t'] not in all_entities:
                        all_entities.append(entry['t'])

                # Filter nodes without embeddings
                nodes_without_embedding = session.execute_read(_get_nodes_without_embedding, all_entities)
                if not nodes_without_embedding:
                    logger.info(f"All entities already have embeddings; no recalculation needed.")
                    return

                logger.info(f"Recalculating embeddings for {len(nodes_without_embedding)}/{len(all_entities)} entities.")

                # Batch process embeddings
                max_batch_size = 1024  
                total_entities = len(nodes_without_embedding)

                for i in range(0, total_entities, max_batch_size):
                    batch_entities = nodes_without_embedding[i:i+max_batch_size]
                    logger.debug(f"Processing entity batch {i//max_batch_size + 1}/{(total_entities-1)//max_batch_size + 1} ({len(batch_entities)} entities)")

                    # Batch fetch embeddings
                    batch_embeddings = await self.aget_embedding(batch_entities)

                    # Pair entities with embeddings
                    entity_embedding_pairs = list(zip(batch_entities, batch_embeddings))

                    # Batch update database
                    session.execute_write(_batch_set_embeddings, entity_embedding_pairs)

                # Save graph metadata after update
                self.save_graph_info()
        except Exception as e:
            logger.error(f"Failed to add entities to Neo4j: {e}, {traceback.format_exc()}")
            raise e

    async def jsonl_file_add_entity(self, file_path, kgdb_name='neo4j'):
        """Add entities from a JSONL file."""
        self.status = "processing"
        kgdb_name = kgdb_name or 'neo4j'
        self.use_database(kgdb_name)
        logger.info(f"Start adding entity to {kgdb_name} with {file_path}")

        def read_triples(file_path):
            with open(file_path, 'r', encoding='utf-8') as file:
                for line in file:
                    if line.strip():
                        yield json.loads(line.strip())

        triples = list(read_triples(file_path))

        await self.txt_add_vector_entity(triples, kgdb_name)

        self.status = "open"
        # Update and save graph database info
        self.save_graph_info()
        return kgdb_name

    async def add_entities_and_relationships(self, entities, relationships, kgdb_name='neo4j'):
        """Add entities and relationships to Neo4j (direct property writing).
        
        Args:
            entities: [{id, type, name, description}]
            relationships: [{source, target, type, description}]
            kgdb_name: Graph database name
        Returns:
            tuple: (Count of entities added, Count of relationships added)
        """
        try:
            self.status = "processing"
            self.use_database(kgdb_name)
            logger.info(f"Adding entities and relationships to {kgdb_name}")
            logger.info(f"Number of entities: {len(entities)}, Number of relationships: {len(relationships)}")

            def _upsert_entities(tx, entity_list):
                for e in entity_list:
                    name = e.get("name")
                    etype = e.get("type", "UNKNOWN")
                    desc = e.get("description", "")
                    if not name:
                        continue
                    tx.run(
                        """
                        MERGE (n:Entity {name: $name})
                        SET n.type = $type,
                            n.description = $description
                        """,
                        name=name, type=etype, description=desc
                    )

            def _create_relationships(tx, rel_list):
                for rel in rel_list:
                    src = rel.get("source") or rel.get("source_ref")
                    tgt = rel.get("target") or rel.get("target_ref")
                    # Use relationship_type if available, fallback to type, default to RELATED_TO
                    rtype = rel.get("relationship_type") or rel.get("type") or "RELATED_TO"
                    if not (src and tgt):
                        continue
                    tx.run(
                        """
                        MATCH (s:Entity {name: $src}), (t:Entity {name: $tgt})
                        MERGE (s)-[r:RELATION {type: $rtype, relationship_type: $rtype}]->(t)
                        """,
                        src=src, tgt=tgt, rtype=rtype
                    )

            def _index_exists(tx, index_name):
                result = tx.run("SHOW INDEXES")
                for record in result:
                    if record["name"] == index_name:
                        return True
                return False

            def _create_vector_index(tx, dim):
                index_name = "entityEmbeddings"
                if not _index_exists(tx, index_name):
                    tx.run(f"""
                    CREATE VECTOR INDEX {index_name}
                    FOR (n: Entity) ON (n.embedding)
                    OPTIONS {{indexConfig: {{
                    `vector.dimensions`: {dim},
                    `vector.similarity_function`: 'cosine'
                    }} }};
                    """)

            def _get_nodes_without_embedding(tx, entity_names):
                params = {f"param{i}": name for i, name in enumerate(entity_names)}
                param_placeholders = ", ".join([f"${key}" for key in params.keys()])
                result = tx.run(f"""
                MATCH (n:Entity)
                WHERE n.name IN [{param_placeholders}] AND n.embedding IS NULL
                RETURN n.name AS name
                """, **params)
                return [record["name"] for record in result]

            def _batch_set_embeddings(tx, entity_embedding_pairs):
                for entity_name, embedding in entity_embedding_pairs:
                    tx.run(
                        """
                        MATCH (e:Entity {name: $name})
                        CALL db.create.setNodeVectorProperty(e, 'embedding', $embedding)
                        """,
                        name=entity_name, embedding=embedding
                    )

            # 1) Writing entity (attributes: type/description)
            with self.driver.session(database=self.kgdb_name) as session:
                session.execute_write(_upsert_entities, entities)

            # 2) Writing relations
            with self.driver.session(database=self.kgdb_name) as session:
                session.execute_write(_create_relationships, relationships)

            # 3) Create vector index and fill embedding
            cur_embed_info = config.embed_model_names[config.embed_model]
            with self.driver.session(database=self.kgdb_name) as session:
                session.execute_write(_create_vector_index, cur_embed_info['dimension'])

                all_entity_names = list({e.get("name") for e in entities if e.get("name")})
                nodes_without_embedding = session.execute_read(_get_nodes_without_embedding, all_entity_names)

            if nodes_without_embedding:
                logger.info(f"Recalculating embeddings for {len(nodes_without_embedding)}/{len(all_entity_names)} entities.")
                max_batch_size = 1024
                total = len(nodes_without_embedding)
                for i in range(0, total, max_batch_size):
                    batch_entities = nodes_without_embedding[i:i+max_batch_size]
                    batch_embeddings = await self.aget_embedding(batch_entities)
                    pairs = list(zip(batch_entities, batch_embeddings))
                    with self.driver.session(database=self.kgdb_name) as session:
                        session.execute_write(_batch_set_embeddings, pairs)
            else:
                logger.info("All entities already have embeddings; no recalculation needed.")

            self.status = "open"
            self.save_graph_info()
            return len(entities), len(relationships)
        except Exception as e:
            logger.error(f"Add entity and relationships to Neo4j failed: {e}, {traceback.format_exc()}")
            self.status = "open"
            raise e

    def delete_entity(self, entity_name=None, kgdb_name="neo4j"):
        """Delete triples for specific entities from the database. If entity_name is empty, delete all entities."""
        self.use_database(kgdb_name)
        with self.driver.session(database=self.kgdb_name) as session:
            if entity_name:
                session.execute_write(self._delete_specific_entity, entity_name)
            else:
                session.execute_write(self._delete_all_entities)

    def _delete_specific_entity(self, tx, entity_name):
        query = """
        MATCH (n {name: $entity_name})
        DETACH DELETE n
        """
        tx.run(query, entity_name=entity_name)

    def _delete_all_entities(self, tx):
        query = """
        MATCH (n)
        DETACH DELETE n
        """
        tx.run(query)

    def query_node(self, entity_name, threshold=0.7, kgdb_name='neo4j', hops=2, max_entities=10, **kwargs):
        """Query nodes similar to the entity_name using vector search and then retrieve their neighborhoods."""
        if not self.is_running():
            raise Exception("Graph database not started")

        self.use_database(kgdb_name)
        def _index_exists(tx, index_name):
            """Check if the index exists."""
            result = tx.run("SHOW INDEXES")
            for record in result:
                if record["name"] == index_name:
                    return True
            return False

        def query(tx, text):
            # First check if the index exists.
            if not _index_exists(tx, "entityEmbeddings"):
                raise Exception("Vector index does not exist; create an index first.")

            embedding = self.get_embedding(text)
            result = tx.run("""
            CALL db.index.vector.queryNodes('entityEmbeddings', 10, $embedding)
            YIELD node AS similarEntity, score
            RETURN similarEntity.name AS name, score
            """, embedding=embedding)
            return result.values()

        try:
            with self.driver.session(database=self.kgdb_name) as session:
                results = session.execute_read(query, entity_name)
        except Exception as e:
            if "Vector index does not exist" in str(e):
                logger.error(f"Vector index does not exist; create an index first: {e}")
                return []
            raise e

        # Filter entities with points above the threshold
        qualified_entities = [result[0] for result in results[:max_entities] if result[1] > threshold]
        logger.debug(f"Graph Query Entities: {entity_name}, {qualified_entities=}")

        # Query each eligible entity
        all_query_results = []
        for entity in qualified_entities:
            query_result = self.query_specific_entity(entity_name=entity, hops=hops, kgdb_name=kgdb_name)
            all_query_results.extend(query_result)

        return all_query_results

    def query_nodes_batch(self, entity_names, threshold=0.7, kgdb_name='neo4j', hops=2, max_entities=10):
        """Batch queries for multiple entities"""
        all_results = []
        for entity_name in entity_names:
            try:
                results = self.query_node(entity_name, threshold, kgdb_name, hops, max_entities)
                all_results.extend(results)
            except Exception as e:
                logger.warning(f"Batch query entity failed {entity_name}: {e}")
                continue
        return all_results

    def query_specific_entity(self, entity_name, kgdb_name='neo4j', hops=2, limit=100):
        """Query triples for the designated entity (undirected relationships)."""
        if not entity_name:
            logger.warning("Entity name is empty")
            return []

        self.use_database(kgdb_name)

        def query(tx, entity_name, hops, limit):
            try:
                query_str = f"""
                MATCH (n {{name: $entity_name}})-[r*1..{hops}]-(m)
                RETURN n AS n, r, m AS m, n.type AS n_type, m.type AS m_type
                LIMIT $limit
                """
                result = tx.run(query_str, entity_name=entity_name, limit=limit)

                if not result:
                    logger.info(f"No relevant information found for entity {entity_name}")
                    return []

                values = result.values()
                # Handle embedding properties safely
                values = clean_triples_embedding(values)
                return values

            except Exception as e:
                logger.error(f"Query entities {entity_name} Failed: {str(e)}")
                return []

        try:
            with self.driver.session(database=self.kgdb_name) as session:
                return session.execute_read(query, entity_name, hops, limit)
        except Exception as e:
            logger.error(f"Database session error: {str(e)}")
            return []

    def query_all_nodes_and_relationships(self, kgdb_name='neo4j', hops = 2):
        """Query all triples in the graph database."""
        self.use_database(kgdb_name)
        def query(tx, hops):
            result = tx.run(f"""
            MATCH (n)-[r*1..{hops}]->(m)
            RETURN n AS n, r, m AS m
            """)
            values = result.values()
            values = clean_triples_embedding(values)
            return values

        with self.driver.session(database=self.kgdb_name) as session:
            return session.execute_read(query, hops)

    def query_by_relationship_type(self, relationship_type, kgdb_name='neo4j', hops = 2):
        """Query triples of a specific relationship type."""
        self.use_database(kgdb_name)
        def query(tx, relationship_type, hops):
            result = tx.run(f"""
            MATCH (n)-[r:`{relationship_type}`*1..{hops}]->(m)
            RETURN n AS n, r, m AS m
            """)
            values = result.values()
            values = clean_triples_embedding(values)
            return values

        with self.driver.session(database=self.kgdb_name) as session:
            return session.execute_read(query, relationship_type, hops)

    def query_entity_like(self, keyword, kgdb_name='neo4j', hops = 2):
        """Fuzzy query NEVER USE"""
        self.use_database(kgdb_name)
        def query(tx, keyword, hops):
            result = tx.run(f"""
            MATCH (n:Entity)
            WHERE n.name CONTAINS $keyword
            MATCH (n)-[r*1..{hops}]->(m)
            RETURN n AS n, r, m AS m
            """, keyword=keyword)
            values = result.values()
            values = clean_triples_embedding(values)
            return values

        with self.driver.session(database=self.kgdb_name) as session:
            return session.execute_read(query, keyword, hops)

    def query_node_info(self, node_name, kgdb_name='neo4j', hops = 2):
        """Retrieve neighborhood information for a specific node."""
        self.use_database(kgdb_name)  # Switch to specified database
        def query(tx, node_name, hops):
            result = tx.run(f"""
            MATCH (n {{name: $node_name}})
            OPTIONAL MATCH (n)-[r*1..{hops}]->(m)
            RETURN n AS n, r, m AS m
            """, node_name=node_name)
            values = result.values()
            values = clean_triples_embedding(values)
            return values

        with self.driver.session(database=self.kgdb_name) as session:
            return session.execute_read(query, node_name, hops)

    async def aget_embedding(self, text):
        # Import global knowledge base instance
        from .. import knowledge_base
        if isinstance(text, list):
            outputs = await knowledge_base.embed_model.abatch_encode(text, batch_size=40)
            return outputs
        else:
            outputs = await knowledge_base.embed_model.aencode(text)
            return outputs

    def get_embedding(self, text):
        # Import global knowledge base instance
        from .. import knowledge_base
        if isinstance(text, list):
            outputs = knowledge_base.embed_model.batch_encode(text, batch_size=40)
            return outputs
        else:
            outputs = knowledge_base.embed_model.encode([text])[0]
            return outputs

    def set_embedding(self, tx, entity_name, embedding):
        tx.run("""
        MATCH (e:Entity {name: $name})
        CALL db.create.setNodeVectorProperty(e, 'embedding', $embedding)
        """, name=entity_name, embedding=embedding)

    def get_graph_info(self, graph_name="neo4j"):
        self.use_database(graph_name)
        def query(tx):
            entity_count = tx.run("MATCH (n) RETURN count(n) AS count").single()["count"]
            relationship_count = tx.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]
            # Get all labels
            labels = tx.run("CALL db.labels() YIELD label RETURN collect(label) AS labels").single()["labels"]

            return {
                "graph_name": graph_name,
                "entity_count": entity_count,
                "relationship_count": relationship_count,
                "triples_count": triples_count,
                "labels": labels,
                "status": self.status,
                "embed_model_name": self.embed_model_name,
                "unindexed_node_count": self.query_nodes_without_embedding(graph_name)
            }

        try:
            if self.status == "open" and self.driver and self.is_running():
                # Access to database information
                with self.driver.session(database=self.kgdb_name) as session:
                    graph_info = session.execute_read(query)

                    # Add Timetamp
                    from datetime import datetime
                    graph_info["last_updated"] = datetime.now().isoformat()
                    return graph_info

        except Exception as e:
            logger.error(f"Failed to get graph database information: {e}, {traceback.format_exc()}")
            return None

    def save_graph_info(self, graph_name="neo4j"):
        """
        Save basic information from the graph database to the work directory as a JSON file.
        Information included: Database Name, Status, Embedding Model Name, etc.
        """
        try:
            graph_info = self.get_graph_info(graph_name)
            if graph_info is None:
                logger.error(f"Graph database information is empty; cannot save.")
                return False

            info_file_path = os.path.join(self.work_dir, "graph_info.json")
            with open(info_file_path, 'w', encoding='utf-8') as f:
                json.dump(graph_info, f, ensure_ascii=False, indent=2)

            # logger.info (f "Database information saved to: {info file path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save graph database information: {e}")
            return False

    def query_nodes_without_embedding(self, kgdb_name='neo4j'):
        """Query nodes lacking embeddings.

        Returns:
            list: List of node names without embeddings.
        """
        self.use_database(kgdb_name)

        def query(tx):
            result = tx.run("""
            MATCH (n:Entity)
            WHERE n.embedding IS NULL
            RETURN n.name AS name
            """)
            return [record["name"] for record in result]

        with self.driver.session(database=self.kgdb_name) as session:
            return session.execute_read(query)

    def load_graph_info(self):
        """
        Load basic information for the graph database from a JSON file in the work directory.
        Returns True if successful, False otherwise.
        """
        try:
            info_file_path = os.path.join(self.work_dir, "graph_info.json")
            if not os.path.exists(info_file_path):
                logger.warning(f"Graph database information file does not exist: {info_file_path}")
                return False

            with open(info_file_path, 'r', encoding='utf-8') as f:
                graph_info = json.load(f)

            # Update Object Properties
            if graph_info.get("embed_model_name"):
                self.embed_model_name = graph_info["embed_model_name"]

            # If necessary, load more information
            # Note: Self.kgdb name is not updated here because it was set at the time of initialization

            logger.info(f"Database information loaded. Last updated: {graph_info.get('last_updated')}")
            return True
        except Exception as e:
            logger.error(f"Failed to load graph database information: {e}")
            return False

    def add_embedding_to_nodes(self, node_names=None, kgdb_name='neo4j'):
        """Add embeddings to nodes.

        Args:
            node_names (list, optional): List of node names to embed. If None, embed all nodes lacking embeddings.
            kgdb_name (str, optional): Graph database name. Defaults to 'neo4j'.

        Returns:
            int: Count of successfully embedded nodes.
        """
        self.use_database(kgdb_name)

        # If node names are None, fetch all nodes without embedded vectors
        if node_names is None:
            node_names = self.query_nodes_without_embedding(kgdb_name)

        count = 0
        with self.driver.session(database=self.kgdb_name) as session:
            for node_name in node_names:
                try:
                    embedding = self.get_embedding(node_name)
                    session.execute_write(self.set_embedding, node_name, embedding)
                    count += 1
                except Exception as e:
                    logger.error(f"Failed to add embedding to node '{node_name}': {e}")

        return count


    def _extract_relationship_info(self, relationship, source_name=None, target_name=None, node_dict=None):
        """
        Extract relationship information and return formatted nodes and side information
        """
        rel_id = relationship.element_id
        nodes = relationship.nodes
        if len(nodes) != 2:
            return None, None

        source, target = nodes
        source_id = source.element_id
        target_id = target.element_id

        source_name = node_dict[source_id]["name"] if source_name is None else source_name
        target_name = node_dict[target_id]["name"] if target_name is None else target_name

        relationship_type = relationship._properties.get("type", "unknown")
        if relationship_type == "unknown":
            relationship_type = relationship.type

        edge_info = {
            "id": rel_id,
            "type": relationship_type,
            "source_id": source_id,
            "target_id": target_id,
            "source_name": source_name,
            "target_name": target_name,
        }

        node_info = [
            {"id": source_id, "name": source_name},
            {"id": target_id, "name": target_name},
        ]

        return node_info, edge_info

    def format_general_results(self, results):
        formatted_results = {"nodes": [], "edges": []}

        for item in results:
            relationship = item[1]
            source_name = item[0]._properties.get("name", "unknown")
            target_name = item[2]._properties.get("name", "unknown") if len(item) > 2 else "unknown"

            node_info, edge_info = self._extract_relationship_info(relationship, source_name, target_name)
            if node_info is None or edge_info is None:
                continue

            for node in node_info:
                if node["id"] not in [n["id"] for n in formatted_results["nodes"]]:
                    formatted_results["nodes"].append(node)

            formatted_results["edges"].append(edge_info)

        return formatted_results

    def query(self, cypher_query: str, kgdb_name: str = 'neo4j'):
        """
        Execute Cypher query and return raw results.
        """
        self.use_database(kgdb_name)
        
        def _execute_query(tx, query):
            result = tx.run(query)
            # Convert results to lists compatible with existing formats
            # The Neo4j driver returns an iterative device for a Record object
            return [list(record.values()) for record in result]

        try:
            with self.driver.session(database=self.kgdb_name) as session:
                return session.execute_read(_execute_query, cypher_query)
        except Exception as e:
            logger.error(f"Execution of Cypher query failed: {cypher_query} - Error: {e}")
            raise

    def get_schema_str(self, kgdb_name: str = 'neo4j') -> str:
        """
        Get graph database schema formatted as a string.
        """
        self.use_database(kgdb_name)

        def _get_schema(tx):
            # Fetch all node labels and their properties
            nodes_schema = {}
            labels_result = tx.run("CALL db.labels()")
            for record in labels_result:
                label = record["label"]
                properties_result = tx.run(f"MATCH (n:`{label}`) UNWIND keys(n) AS key RETURN collect(distinct key) AS properties")
                properties = properties_result.single()["properties"]
                nodes_schema[label] = properties
            
            # Get All Relationship Types and their Properties
            relationships_schema = {}
            rel_types_result = tx.run("CALL db.relationshipTypes()")
            for record in rel_types_result:
                rel_type = record["relationshipType"]
                properties_result = tx.run(f"MATCH ()-[r:`{rel_type}`]->() UNWIND keys(r) AS key RETURN collect(distinct key) AS properties")
                properties = properties_result.single()["properties"]
                relationships_schema[rel_type] = properties
            
            return nodes_schema, relationships_schema

        try:
            with self.driver.session(database=self.kgdb_name) as session:
                nodes, rels = session.execute_read(_get_schema)
                
                # Format into string
                schema_str = "Node labels and properties:\n"
                for label, props in nodes.items():
                    schema_str += f"- Label: `{label}`, Properties: {props}\n"
                
                schema_str += "\nRelationship types and properties:\n"
                for rel_type, props in rels.items():
                    schema_str += f"- Type: `{rel_type}`, Properties: {props}\n"
                
                return schema_str
        except Exception as e:
            logger.error(f"Failed to get graph schema: {e}")
            return "Error: Could not retrieve graph schema."
    
    def generate_cypher_query(self, query: str, entities: list, graph_schema: str) -> str:
        """
        Use LLM based on user question, entities, and graph schema to generate a Cypher query.
        """
        from ..utils.prompts import cypher_generation_template as template
        
        model = select_model()
        
        prompt = template.format(
            schema=graph_schema,
            question=query,
            entities=", ".join([f"'{e}'" for e in entities])
        )
        
        try:
            response = model.predict(prompt).content
            # Extract Cypher from the Markdown code block returned by LLM
            cypher_match = re.search(r"```(cypher)?\n(.*?)```", response, re.DOTALL)
            if cypher_match:
                return cypher_match.group(2).strip()
            else:
                # If no code blocks, return the value directly (do some basic cleaning)
                return response.strip().replace("```", "")
        except Exception as e:
            logger.error(f"LLM Cypher generation failed: {e}")
            return ""

    def format_query_result_to_graph(self, query_results):
        """Convert retrieval results to {"nodes": [], "edges": []} format.

        Example:
        {
            "nodes": [
                {
                    "id": "node_id_1",
                    "name": "Lazarus Group",
                    "type": "Threat Actor"
                },
                ...
            ],
            "edges": [
                {
                    "id": "rel_id_1",
                    "type": "USES",
                    "source_id": "node_id_1",
                    "target_id": "node_id_2",
                    "source_name": "Lazarus Group",
                    "target_name": "Mimikatz"
                },
                ...
            ]
        }
        """
        formatted_results = {"nodes": [], "edges": []}
        node_dict = {}
        edge_dict = {}

        for item in query_results:
            # Check Data Format
            if len(item) < 2 or not isinstance(item[1], list):
                continue

            # Process node information, including type field
            node_dict[item[0].element_id] = dict(
                id=item[0].element_id, 
                name=item[0]._properties.get("name", "Unknown"),
                type=item[0]._properties.get("type", "unknown")
            )
            node_dict[item[2].element_id] = dict(
                id=item[2].element_id, 
                name=item[2]._properties.get("name", "Unknown"),
                type=item[2]._properties.get("type", "unknown")
            )

            # Deal with each relationship in the relationship list
            for i, relationship in enumerate(item[1]):
                try:
                    # Extract Relationship Information
                    node_info, edge_info = self._extract_relationship_info(relationship, node_dict=node_dict)
                    if node_info is None or edge_info is None:
                        continue

                    # Add Side
                    edge_dict[edge_info["id"]] = edge_info
                except Exception as e:
                    logger.error(f"Error handling relationships: {e}, Relations: {relationship}, {traceback.format_exc()}")
                    continue

        # Convert node dictionary to list
        formatted_results["nodes"] = list(node_dict.values())
        formatted_results["edges"] = list(edge_dict.values())


        return formatted_results

def clean_triples_embedding(triples):
    for item in triples:
        if hasattr(item[0], '_properties'):
            item[0]._properties['embedding'] = None
        if hasattr(item[2], '_properties'):
            item[2]._properties['embedding'] = None
    return triples


# Instantiate global graph database
graph_base = GraphDatabase()
