"""
Database migration system
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from src.utils import logger


class DatabaseMigrator:
    """Database Migration"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.backup_dir = os.path.join(os.path.dirname(db_path), "backups")
        self.migration_version_key = "migration_version"

    def ensure_backup_dir(self):
        """Ensure that a backup directory exists"""
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)

    def backup_database(self) -> str:
        """Backup database files"""
        if not os.path.exists(self.db_path):
            logger.info("Database file does not exist，No backup required")
            return ""

        self.ensure_backup_dir()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"server_backup_{timestamp}.db"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"Database backuped to: {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Database backup failed: {e}")
            raise

    def get_current_version(self) -> int:
        """Get the current database version"""
        if not os.path.exists(self.db_path):
            return 0

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Check if the version table exists
            cursor.execute("""
                                   SELECT name FROM sqlite_master
                                   WHERE type='table' AND name='migration_versions'            """)

            if not cursor.fetchone():
                # Version table does not exist, check if old version data Library
                cursor.execute("""
                    SELECT name FROM sqlite_master
                    WHERE type='table' AND name='users'
                """)
                if cursor.fetchone():
                    # User table exists but the version table does not exist, indicating that it is an old version
                    return 0
                else:
                    # New database
                    return 0

            # Get Current Version
            cursor.execute("SELECT version FROM migration_versions ORDER BY version DESC LIMIT 1")
            result = cursor.fetchone()
            return result[0] if result else 0

        except Exception as e:
            logger.error(f"Failed to get database version: {e}")
            return 0
        finally:
            if "conn" in locals():
                conn.close()

    def set_version(self, version: int):
        """Setup Database Version"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Create Version Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS migration_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version INTEGER NOT NULL,
                    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    description TEXT
                )
            """)

            # Insert Version Record
            cursor.execute(
                """
                INSERT INTO migration_versions (version, description)
                VALUES (?, ?)
            """,
                (version, f"Migration to version {version}"),
            )

            conn.commit()
            logger.info(f"Database version set to: {version}")

        except Exception as e:
            logger.error(f"Failed to set database version: {e}")
            raise
        finally:
            if "conn" in locals():
                conn.close()

    def execute_migration(self, version: int, description: str, sql_commands: list[str]):
        """Execute Migration"""
        logger.info(f"Execute Migration v{version}: {description}")

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Execute the SQL relocation order
            for sql in sql_commands:
                if sql.strip():  # Skip empty commands
                    logger.info(f"ImplementationSQL: {sql}")
                    cursor.execute(sql)

            conn.commit()
            logger.info(f"Migration v{version} Implementation Success")

        except Exception as e:
            logger.error(f"Migration v{version} Implementation Failed: {e}")
            raise
        finally:
            if "conn" in locals():
                conn.close()

    def check_column_exists(self, table_name: str, column_name: str) -> bool:
        """Check column for presence"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = [column[1] for column in cursor.fetchall()]
            return column_name in columns

        except Exception:
            return False
        finally:
            if "conn" in locals():
                conn.close()

    def run_migrations(self):
        """Run all pending migrations"""
        current_version = self.get_current_version()
        latest_version = self.get_latest_migration_version()

        # Create a version table and set it to the latest if the database already exists without a version table
        if current_version == 0 and latest_version > 0 and os.path.exists(self.db_path):
            # Check if there are new fields in the user table, if any, indicating that they were created through SQLAlchemy
            if (
                self.check_column_exists("users", "login_failed_count")
                and self.check_column_exists("users", "last_failed_login")
                and self.check_column_exists("users", "login_locked_until")
            ):
                # Field already exists, set directly to the latest version
                logger.info(f"Detects that the existing database contains the latest fields，Set Version As v{latest_version}")
                self.set_version(latest_version)
                return

        if current_version >= latest_version:
            logger.info(f"Database is the latest version v{current_version}")
            return

        logger.info(f"Start database migration: v{current_version} -> v{latest_version}")

        # Backup Database
        backup_path = self.backup_database()

        try:
            # Execute Migration
            migrations = self.get_migrations()
            has_executed_migrations = False

            for version, description, sql_commands in migrations:
                if version > current_version:
                    if sql_commands:  # Relocation only when SQL commands
                        self.execute_migration(version, description, sql_commands)
                        has_executed_migrations = True
                    else:
                        logger.info(f"Migration v{version}: {description} - No implementation required，Field already exists")

                    # Set version with or without SQL commands
                    self.set_version(version)

            if has_executed_migrations:
                logger.info("Database migration complete")
            else:
                logger.info("Database structure is up to date，Update only version records")

        except Exception as e:
            logger.error(f"Database migration failed: {e}")
            if backup_path and os.path.exists(backup_path):
                logger.info(f"Try to recover from backup: {backup_path}")
                try:
                    shutil.copy2(backup_path, self.db_path)
                    logger.info("Database restored from backup")
                except Exception as restore_error:
                    logger.error(f"Database restoration failed: {restore_error}")
            raise

    def get_latest_migration_version(self) -> int:
        """Get the latest migration number"""
        # Returns the latest version of the hard code here, without depending on the migration definition
        # Because the migration definition may be empty (field already exists)
        return 1  # Current latest version is v1

    def get_migrations(self) -> list[tuple[int, str, list[str]]]:
        """Get All Migration Definitions
        Return Format: [(version, description, [sql_commands])]
        """
        migrations = []

        # Move v1: Add login limit field to user table
        # Use condition check to avoid adding fields
        v1_commands = []

        # Check and add login failed count field
        if not self.check_column_exists("users", "login_failed_count"):
            v1_commands.append("ALTER TABLE users ADD COLUMN login_failed_count INTEGER NOT NULL DEFAULT 0")

        # Check and add last failed login fields
        if not self.check_column_exists("users", "last_failed_login"):
            v1_commands.append("ALTER TABLE users ADD COLUMN last_failed_login DATETIME")

        # Check and add login locked until field
        if not self.check_column_exists("users", "login_locked_until"):
            v1_commands.append("ALTER TABLE users ADD COLUMN login_locked_until DATETIME")

        # If there's an order to execute, add migration
        if v1_commands:
            migrations.append((1, "Could not close temporary folder: %s", v1_commands))

        # Future migration can be added here
        # migrations.append((
        #     2,
        # "Add a new functionality-related table,"
        #     [
        #         "CREATE TABLE new_feature (...)",
        #         "ALTER TABLE existing_table ADD COLUMN new_field ..."
        #     ]
        # ))

        return migrations


def validate_database_schema(db_path: str) -> tuple[bool, list[str]]:
    """Verify database structure for current model

    Returns:
        tuple: (Compatibility, List of missing fields)
    """
    if not os.path.exists(db_path):
        return False, ["Database file does not exist"]

    missing_fields = []

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check the required fields of the user table
        required_fields = {
            "users": [
                "id",
                "username",
                "user_id",
                "phone_number",
                "avatar",
                "password_hash",
                "role",
                "created_at",
                "last_login",
                "login_failed_count",
                "last_failed_login",
                "login_locked_until",
            ],
            "operation_logs": ["id", "user_id", "operation", "details", "ip_address", "timestamp"],
        }

        for table_name, fields in required_fields.items():
            # Checklist exists
            cursor.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name=?
            """,
                (table_name,),
            )

            if not cursor.fetchone():
                missing_fields.append(f"Table {table_name} does not exist")
                continue

            # Checks if fields exist
            cursor.execute(f"PRAGMA table_info({table_name})")
            existing_columns = [column[1] for column in cursor.fetchall()]

            for field in fields:
                if field not in existing_columns:
                    missing_fields.append(f"Table {table_name} Missing fields {field}")

        return len(missing_fields) == 0, missing_fields

    except Exception as e:
        logger.error(f"Failed to validate database structure: {e}")
        return False, [f"Authentication Failed: {str(e)}"]
    finally:
        if "conn" in locals():
            conn.close()


def check_and_migrate(db_path: str):
    """Check and execute database migration"""
    # Validate database structure first
    is_valid, issues = validate_database_schema(db_path)

    if not is_valid:
        logger.warning("Database structure does not match current design:")
        for issue in issues:
            logger.warning(f"  - {issue}")

        if os.path.exists(db_path):
            logger.info("Recommended to run the migration script: docker exec api-dev python /app/scripts/migrate_user_fields.py")

    migrator = DatabaseMigrator(db_path)

    try:
        migrator.run_migrations()
        return True
    except Exception as e:
        logger.error(f"Error during database migration: {e}")
        return False