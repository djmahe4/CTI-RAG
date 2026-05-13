import os
import json
import time
from pathlib import Path
import traceback

from .. import config
from ..utils import logger
from ..manager.kb_db_manager import kb_db_manager

def migrate_json_to_sqlite():
    """WillJSONFile data migration toSQLiteDatabase"""
    # Original JSON file path
    json_path = os.path.join(config.save_dir, "data", "database.json")

    if not os.path.exists(json_path):
        logger.info(f"Original not foundJSONDocumentation: {json_path}，No need to move.")
        return False

    try:
        # Read JSON files
        with open(json_path, "r", encoding='utf-8') as f:
            data = json.load(f)

        if not data or "databases" not in data or not data["databases"]:
            logger.info("JSONNo database information in file，No need to move.")
            return False

        # Start Migration
        logger.info(f"Start migration of knowledge base data，Total {len(data['databases'])} Database")

        # Walk through all databases
        for db_info in data["databases"]:
            db_id = db_info["db_id"]
            name = db_info["name"]
            description = db_info["description"]
            embed_model = db_info.get("embed_model")
            dimension = db_info.get("dimension")
            metadata = db_info.get("metadata", {})

            logger.info(f"Processing database: {name} (ID: {db_id}), metadataType: {type(metadata)}")

            # Check if the database exists
            existing_db = kb_db_manager.get_database_by_id(db_id)
            if existing_db:
                logger.info(f"Database {name} (ID: {db_id}) Exists，Skip creation")
                continue

            # Create Database
            db = kb_db_manager.create_database(
                db_id=db_id,
                name=name,
                description=description,
                embed_model=embed_model,
                dimension=dimension,
                metadata=metadata  # Enter metadata here and be stored correctly in kb db manager as meta info
            )

            # Processing of documents
            files = db_info.get("files", {})
            if isinstance(files, list):
                files = {f["file_id"]: f for f in files}

            for file_id, file_info in files.items():
                # Add File
                kb_db_manager.add_file(
                    db_id=db_id,
                    file_id=file_id,
                    filename=file_info["filename"],
                    path=file_info["path"],
                    file_type=file_info["type"],
                    status=file_info["status"]
                )

                # Process Nodes
                nodes = file_info.get("nodes", [])
                for node in nodes:
                    node_metadata = node.get("metadata", {})
                    if node_metadata is None:
                        node_metadata = {}
                    logger.debug(f"NodesmetadataType: {type(node_metadata)}")

                    kb_db_manager.add_node(
                        file_id=file_id,
                        text=node["text"],
                        hash_value=node.get("hash"),
                        start_char_idx=node.get("start_char_idx"),
                        end_char_idx=node.get("end_char_idx"),
                        metadata=node_metadata  # Can not initialise the Ximian Evolution shell.
                    )

            logger.info(f"Database {name} (ID: {db_id}) Migration complete.，Total {len(files)} File")

        # Backup Original JSON File
        backup_path = json_path + f".bak.{int(time.time())}"
        os.rename(json_path, backup_path)
        logger.info(f"Migration complete.，OriginalJSONFile Backup As: {backup_path}")

        return True

    except Exception as e:
        logger.error(f"Error during migration: {e}")
        logger.error(traceback.format_exc())
        return False

if __name__ == "__main__":
    migrate_json_to_sqlite()