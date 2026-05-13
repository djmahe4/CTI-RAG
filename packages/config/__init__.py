import os
import json
import yaml
from pathlib import Path
from ..utils.logging_config import logger
from ..utils import get_project_root

DEFAULT_MOCK_API = 'this_is_mock_api_key_in_frontend'

class SimpleConfig(dict):

    def __key(self, key):
        return "" if key is None else key  # I've forgotten why we're here.

    def __str__(self):
        return json.dumps(self)

    def __setattr__(self, key, value):
        self[self.__key(key)] = value

    def __getattr__(self, key):
        return self.get(self.__key(key))

    def __getitem__(self, key):
        return self.get(self.__key(key))

    def __setitem__(self, key, value):
        return super().__setitem__(self.__key(key), value)

    def __dict__(self):
        return {k: v for k, v in self.items()}


class Config(SimpleConfig):

    def __init__(self):
        super().__init__()
        self._config_items = {}
        # Relative path to using the root directory
        project_root = get_project_root()
        self.save_dir = os.path.join(project_root, "saves")

        # Prefer root directory config.yaml and if not available
        root_config = os.path.join(project_root, "config.yaml")
        fallback_config = str(Path(self.save_dir) / "config" / "base.yaml")

        if os.path.exists(root_config):
            self.filename = root_config
        else:
            self.filename = fallback_config
            os.makedirs(os.path.dirname(self.filename), exist_ok=True)

        self._update_models_from_file()

        # ## > > Default Configuration
        # Function Options
        self.add_item("enable_reranker", default=False, des="Whether to open reordering")
        self.add_item("enable_knowledge_base", default=False, des="Whether to open the knowledge base")
        self.add_item("enable_knowledge_graph", default=False, des="Whether to open the knowledge map")
        self.add_item("enable_web_search", default=False, des="Whether to open a web search（Notes：It'll be based on this. TAVILY_API_KEY Autostart，Unable to manually configure，This configuration will be removed in the next version）")
        # Model Configuration
        # # Note that this is the model name, not the specific model path, defaulting on the HuggingFace path
        # # Configure MODEL DIR in src/.env if custom local model paths are required
        self.add_item("model_provider", default="siliconflow", des="Model providers", choices=list(self.model_names.keys()))
        self.add_item("model_name", default="Qwen/Qwen2.5-7B-Instruct", des="Model Name")

        self.add_item("embed_model", default="siliconflow/BAAI/bge-m3", des="Embedding Model", choices=list(self.embed_model_names.keys()))
        self.add_item("reranker", default="siliconflow/BAAI/bge-reranker-v2-m3", des="Re-Ranker Model", choices=list(self.reranker_names.keys()))
        self.add_item("model_local_paths", default={}, des="Local Model Path")
        self.add_item("use_rewrite_query", default="off", des="Rewrite queries", choices=["off", "on", "hyde"])
        self.add_item("device", default="cuda", des="Device to run local models", choices=["cpu", "cuda"])
        self.add_item("RERANK_TOP_K", default=5, des="Number of documents returned after rearranging")
        # Enhance the allocation of learning reasoning
        self.add_item(
            "rl_base_model_path",
            default="models/reasoning_model/Qwen2.5-3B-Instruct",
            des="RL Basic Model Path"
        )
        self.add_item(
            "rl_lora_path",
            default="models/reasoning_model/final_lora",
            des="RL LoRA Weight Path"
        )
        self.add_item(
            "rl_policy_checkpoint_path",
            default="models/reasoning_model/rl_policy_path_match/best_policy.pt",
            des="RL Policy Network checkpoint"
        )
        self.add_item(
            "rl_adjacency_path",
            default="RL/cache/adjacency.json",
            des="RL Map adjacent cache path"
        )
        self.add_item(
            "rl_device",
            default="cuda",
            des="RL reason device",
            choices=["cpu", "cuda"]
        )
        self.add_item("rl_max_steps", default=4, des="RL Maximum step of reasoning")
        self.add_item("rl_candidate_top_k", default=3, des="RL Number of candidates for the starting entity")
        # # << Default configuration end

        self.load()
        # Uniformize path separator to avoid repository ID verification failure due to the Windows-style backslash
        try:
            def _normalize_path(p: str) -> str:
                if not isinstance(p, str):
                    return p
                q = p.replace('\\', '/')
                # Raise relative models/ prefixes to the absolute path within the container and maintain backward compatibility
                if q.startswith('models/'):
                    q = '/app/' + q
                return q

            if isinstance(self.model_local_paths, dict):
                for _k, _v in list(self.model_local_paths.items()):
                    self.model_local_paths[_k] = _normalize_path(_v)

            # Synchronize local path in static model tables (if loaded to memory)
            for _table in (getattr(self, 'embed_model_names', {}), getattr(self, 'reranker_names', {})):
                if isinstance(_table, dict):
                    for _k, _v in _table.items():
                        if isinstance(_v, dict) and 'local_path' in _v:
                            _v['local_path'] = _normalize_path(_v['local_path'])
        except Exception:
            # Regulatory failure should not block startup
            pass

        self.handle_self()

    def add_item(self, key, default, des=None, choices=None):
        self.__setattr__(key, default)
        self._config_items[key] = {
            "default": default,
            "des": des,
            "choices": choices
        }

    def __dict__(self):
        blocklist = [
            "_config_items",
            "model_names",
            "model_provider_status",
            "embed_model_names",
            "reranker_names",
        ]
        return {k: v for k, v in self.items() if k not in blocklist}

    def _update_models_from_file(self):
        """
        From models.yaml and models.yml Update MODEL_NAMES
        """
        # Relative path to using the root directory
        project_root = get_project_root()
        static_dir = os.path.join(project_root, "packages", "static")

        with open(os.path.join(static_dir, "models.yaml"), 'r', encoding='utf-8') as f:
            _models = yaml.safe_load(f)

        # Try opening a models.private.yml file to overwrite the configuration in models.yaml
        try:
            with open(os.path.join(static_dir, "models.yml"), 'r', encoding='utf-8') as f:
                _models_private = yaml.safe_load(f)
        except FileNotFoundError:
            _models_private = {}

        # Keep models for deepseek, zhipu and local
        filtered_models = {
            "MODEL_NAMES": {
                k: v for k, v in _models["MODEL_NAMES"].items()
                if k in ["deepseek", "zhipu"]
            },
            "EMBED_MODEL_INFO": {
                k: v for k, v in _models["EMBED_MODEL_INFO"].items()
                if k.startswith(("deepseek/", "zhipu/", "local/", "dashscope/")) or k in ["deepseek", "zhipu", "local", "dashscope"]
            },
            "RERANKER_LIST": {
                k: v for k, v in _models["RERANKER_LIST"].items()
                if k.startswith(("deepseek/", "zhipu/", "local/")) or k in ["deepseek", "zhipu", "local"]
            }
        }

        # Merge Private Configuration
        self.model_names = {**filtered_models["MODEL_NAMES"], **_models_private.get("MODEL_NAMES", {})}
        self.embed_model_names = {**filtered_models["EMBED_MODEL_INFO"], **_models_private.get("EMBED_MODEL_INFO", {})}
        self.reranker_names = {**filtered_models["RERANKER_LIST"], **_models_private.get("RERANKER_LIST", {})}

    def _save_models_to_file(self):
        """Save model configuration to file"""
        _models = {
            "MODEL_NAMES": self.model_names,
            "EMBED_MODEL_INFO": self.embed_model_names,
            "RERANKER_LIST": self.reranker_names,
        }
        # Relative path to using the root directory
        project_root = get_project_root()
        static_dir = os.path.join(project_root, "packages", "static")

        with open(os.path.join(static_dir, "models.yml"), 'w', encoding='utf-8') as f:
            yaml.dump(_models, f, indent=2, allow_unicode=True)

    def handle_self(self):
        """
        Process Configuration
        """
        # Deals only with deepseek and zhipai models
        model_provider_info = self.model_names.get(self.model_provider, {})
        self.model_dir = os.environ.get("MODEL_DIR", "")

        if self.model_dir:
            if os.path.exists(self.model_dir):
                logger.info(f"MODEL_DIR （{self.model_dir}） Folder Below: {os.listdir(self.model_dir)}")
            else:
                logger.warning(f"Organisation：MODEL_DIR （{self.model_dir}） does not exist，If Unconfigured，Ignore，If it's configured,，Check if the configuration is correct.，Like what? docker-compose Map in File")

        # Check if the model provider exists
        if self.model_provider not in ["deepseek"]:
            logger.warning(f"Model provider {self.model_provider} not supported, using default model provider")
            self.model_provider = "deepseek"  # Default use deepseek
            model_provider_info = self.model_names.get(self.model_provider, {})

        # Check for model names
        if self.model_name not in model_provider_info.get("models", []):
            logger.warning(f"Model name {self.model_name} not in {self.model_provider}, using default model name")
            self.model_name = model_provider_info.get("default", "deepseek-chat")

        # Check environmental variables of model providers
        conds = {}
        self.model_provider_status = {}
        for provider in ["deepseek"]:  # Check only these two providers.
            conds[provider] = self.model_names[provider]["env"]
            conds_bool = [bool(os.getenv(_k)) for _k in conds[provider]]
            self.model_provider_status[provider] = all(conds_bool)

        # 2025.04.08 Change to Unmanual Configuration, with TAVILY API KEY configured, to open web search by default
        if os.getenv("TAVILY_API_KEY"):
            self.enable_web_search = True

        self.valuable_model_provider = [k for k, v in self.model_provider_status.items() if v]
        assert len(self.valuable_model_provider) > 0, f"No model provider available, please check your `.env` file. API_KEY_LIST: {conds}"

    def load(self):
        """Overwrite default configuration based on imported files"""
        logger.info(f"Loading config from {self.filename}")
        if self.filename is not None and os.path.exists(self.filename):

            if self.filename.endswith(".json"):
                with open(self.filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content:
                        local_config = json.loads(content)
                        self.update(local_config)
                    else:
                        print(f"{self.filename} is empty.")

            elif self.filename.endswith(".yaml"):
                with open(self.filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content:
                        local_config = yaml.safe_load(content)
                        self.update(local_config)
                    else:
                        print(f"{self.filename} is empty.")
            else:
                logger.warning(f"Unknown config file type {self.filename}")

        else:
            logger.warning(f"\n\n{'='*70}\n{'Config file not found':^70}\n{'You can custum your config in `' + self.filename + '`':^70}\n{'='*70}\n\n")

    def save(self):
        logger.info(f"Saving config to {self.filename}")
        if self.filename is None:
            logger.warning("Config file is not specified, save to default config/base.yaml")
            self.filename = os.path.join(self.save_dir, "config", "base.yaml")
            os.makedirs(os.path.dirname(self.filename), exist_ok=True)

        if self.filename.endswith(".json"):
            with open(self.filename, 'w+', encoding='utf-8') as f:
                json.dump(self.__dict__(), f, indent=4, ensure_ascii=False)
        elif self.filename.endswith(".yaml"):
            with open(self.filename, 'w+', encoding='utf-8') as f:
                yaml.dump(self.__dict__(), f, indent=2, allow_unicode=True)
        else:
            logger.warning(f"Unknown config file type {self.filename}, save as json")
            with open(self.filename, 'w+', encoding='utf-8') as f:
                json.dump(self, f, indent=4)

        logger.info(f"Config file {self.filename} saved")

    def get_safe_config(self):
        """
        Get Secure Configuration，It's filtering out. api_key
        """

        config = json.loads(str(self))

        # Filter out api key
        for model in config.get("custom_models", []):
            model["api_key"] = DEFAULT_MOCK_API if model.get("api_key") else ""

        return config

    def compare_custom_models(self, value):
        """
        Comparison custom_models Medium api_key，If entered api_key With Current api_key Same，Do not modify
        If entered api_key Yes DEFAULT_MOCK_API，Use current api_key
        """
        current_models_dict = {model["custom_id"]: model.get("api_key") for model in self.get("custom_models", [])}

        for i, model in enumerate(value):
            input_custom_id = model.get("custom_id")
            input_api_key = model.get("api_key")

            if input_custom_id in current_models_dict:
                current_api_key = current_models_dict[input_custom_id]
                if input_api_key == DEFAULT_MOCK_API or input_api_key == current_api_key:
                    value[i]["api_key"] = current_api_key

        return value
