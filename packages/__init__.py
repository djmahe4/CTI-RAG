from concurrent.futures import ThreadPoolExecutor
executor = ThreadPoolExecutor()

# Load Environmental Variables
import os
from dotenv import load_dotenv
from pathlib import Path

# Fetch project root directory and load.env files
def get_project_root():
    current_path = Path(__file__).resolve()
    root_indicators = ['.git', 'requirements.txt', 'pyproject.toml', 'setup.py', 'README.md']

    for parent in current_path.parents:
        if any((parent / indicator).exists() for indicator in root_indicators):
            return str(parent)

    return str(current_path.parent.parent)

project_root = get_project_root()
env_path = os.path.join(project_root, '.env')
if os.path.exists(env_path):
    load_dotenv(env_path)
    print(f"Loaded Environment Variable File: {env_path}")
else:
    print(f"Warning: Environment variable file does not exist: {env_path}")

from packages.config import Config
config = Config()

# Delay importing other modules to avoid initializing all dependencies at import
class LazyLoader:
    def __init__(self):
        self._knowledge_base = None
        self._graph_base = None
        self._retriever = None

    @property
    def knowledge_base(self):
        if self._knowledge_base is None:
            from packages.core import KnowledgeBase
            self._knowledge_base = KnowledgeBase()
        return self._knowledge_base

    @property
    def graph_base(self):
        if self._graph_base is None:
            from packages.core import GraphDatabase
            self._graph_base = GraphDatabase()
        return self._graph_base

    @property
    def retriever(self):
        if self._retriever is None:
            from packages.core.retriever import Retriever
            self._retriever = Retriever()
        return self._retriever

# Create instance of delayed loader
_lazy = LazyLoader()

# Provision of modular-level access for backward compatibility
def __getattr__(name):
    if name == 'knowledge_base':
        return _lazy.knowledge_base
    elif name == 'graph_base':
        return _lazy.graph_base
    elif name == 'retriever':
        return _lazy.retriever
    else:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")