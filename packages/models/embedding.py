import os
import json
import requests
import asyncio
from openai import OpenAI
from zhipuai import ZhipuAI

from .. import config
from ..utils import hashstr, logger, get_docker_safe_url


class BaseEmbeddingModel:
    embed_state = {}

    def get_dimension(self):
        if hasattr(self, "dimension"):
            return self.dimension

        if hasattr(self, "embed_model_fullname"):
            return config.embed_model_names[self.embed_model_fullname].get("dimension", None)

        return config.embed_model_names[self.model].get("dimension", None)

    def encode(self, message):
        return self.predict(message)

    def encode_queries(self, queries):
        return self.predict(queries)

    async def aencode(self, message):
        return await asyncio.to_thread(self.encode, message)

    async def aencode_queries(self, queries):
        return await asyncio.to_thread(self.encode_queries, queries)

    async def abatch_encode(self, messages, batch_size=20):
        return await asyncio.to_thread(self.batch_encode, messages, batch_size)

    def batch_encode(self, messages, batch_size=20):
        logger.info(f"Batch encoding {len(messages)} messages")
        data = []

        if len(messages) > batch_size:
            task_id = hashstr(messages)
            self.embed_state[task_id] = {
                'status': 'in-progress',
                'total': len(messages),
                'progress': 0
            }

        for i in range(0, len(messages), batch_size):
            group_msg = messages[i:i+batch_size]
            logger.info(f"Encoding {i} to {i+batch_size} with {len(messages)} messages")
            response = self.encode(group_msg)
            logger.debug(f"Response: {len(response)=}, {len(group_msg)=}, {len(response[0])=}")
            data.extend(response)

        if len(messages) > batch_size:
            self.embed_state[task_id]['progress'] = len(messages)
            self.embed_state[task_id]['status'] = 'completed'

        return data

class LocalEmbeddingModel(BaseEmbeddingModel):
    def __init__(self, config, **kwargs):
        """
        For Local Models，It could be here. src/static/models.private.yaml Other Organiser local_path Path

        ```yaml
        EMBED_MODEL_INFO:
            local/BAAI/bge-m3:
                dimension: 1024
                name: BAAI/bge-m3
                local_path: /path/to/bge-m3
        ```

        But make sure docker-compose We've got it. MODEL_DIR Present. /models Contents
        """
        info = config.embed_model_names[config.embed_model]

        self.model = config.model_local_paths.get(info["name"], info.get("local_path"))
        self.model = self.model or info["name"]
        # Regulate local path separator and complete the absolute path inside the container
        if isinstance(self.model, str):
            _m = self.model.replace('\\\
','/')
            if _m.startswith('models/'):
                _m = '/app/' + _m
            self.model = _m
        self.dimension = info["dimension"]
        self.embed_model_fullname = config.embed_model

        if os.getenv("MODEL_DIR"):
            if os.path.exists(_path := os.path.join(os.getenv("MODEL_DIR"), self.model)):
                self.model = _path
            else:
                logger.warning(f"Local model `{info['name']}` not found in `{self.model}`, using `{info['name']}`")

        logger.info(f"Loading local model `{info['name']}` from `{self.model}` with device `{config.device}`，"
                    f"If no path is configured，As a rule, it's automatic. Huggingface Download Model，If download fails，You can try it. HF_MIRROR Environmental variables；"
                    f"If not,，Suggests manually downloading to a folder such as  /path/to/models/BAAI/bge-m3 Contents；"
                    f"Then configure src/.env File MODEL_DIR Environment variable to /path/to/models Contents；"
                    f"If it was docker Running，Make sure. docker-compose Documentation（line 12 Around）We've got it. MODEL_DIR Present. /models Contents")

        from FlagEmbedding import FlagModel

        self._model = FlagModel(
            self.model,
            query_instruction_for_retrieval=info.get("query_instruction", None),
            use_fp16=False,
            device=config.device,
            **kwargs,
        )

        logger.info(f"Embedding model {info['name']} loaded")

    def predict(self, message):
        return self._model.encode(message)


class ZhipuEmbedding(BaseEmbeddingModel):

    def __init__(self, config) -> None:
        self.config = config
        self.model = config.embed_model_names[config.embed_model]["name"]
        self.dimension = config.embed_model_names[config.embed_model]["dimension"]
        self.client = ZhipuAI(api_key=os.getenv("ZHIPUAI_API_KEY"))
        self.embed_model_fullname = config.embed_model

    def predict(self, message):
        response = self.client.embeddings.create(
            model=self.model,
            input=message,
        )
        data = [a.embedding for a in response.data]
        return data


class OllamaEmbedding(BaseEmbeddingModel):
    def __init__(self, config) -> None:
        self.info = config.embed_model_names[config.embed_model]
        self.model = self.info["name"]
        self.url = self.info.get("url", "http://localhost:11434/api/embed")
        self.url = get_docker_safe_url(self.url)
        self.dimension = self.info.get("dimension", None)
        self.embed_model_fullname = config.embed_model

    def predict(self, message: list[str] | str):
        if isinstance(message, str):
            message = [message]

        payload = {
            "model": self.model,
            "input": message,
        }
        response = requests.request("POST", self.url, json=payload)
        response = json.loads(response.text)
        assert response.get("embeddings"), f"Ollama Embedding failed: {response}"
        return response["embeddings"]


class OtherEmbedding(BaseEmbeddingModel):

    def __init__(self, config) -> None:
        self.info = config.embed_model_names[config.embed_model]
        self.embed_model_fullname = config.embed_model
        self.dimension = self.info.get("dimension", None)
        self.model = self.info["name"]
        self.api_key = os.getenv(self.info["api_key"], None)
        raw_url = self.info["url"]
        if isinstance(raw_url, str) and not raw_url.startswith(("http://", "https://")):
            raw_url = os.getenv(raw_url, raw_url)
        self.url = get_docker_safe_url(raw_url)
        self.client = None
        if self.embed_model_fullname.startswith("dashscope/"):
            self.client = OpenAI(api_key=self.api_key, base_url=self.url)
        assert self.url and self.model, f"URL and model are required. Cur embed model: {config.embed_model}"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def predict(self, message):
        if self.client is not None:
            response = self.client.embeddings.create(
                model=self.model,
                input=message,
            )
            return [item.embedding for item in response.data]

        payload = self.build_payload(message)
        response = requests.request("POST", self.url, json=payload, headers=self.headers)
        response = json.loads(response.text)
        assert response["data"], f"Other Embedding failed: {response}"
        data = [a["embedding"] for a in response["data"]]
        return data

    def build_payload(self, message):
        return {
            "model": self.model,
            "input": message,
        }

def get_embedding_model(config):
    if not config.enable_knowledge_base:
        return None

    provider, model_name = config.embed_model.split('/', 1)
    assert config.embed_model in config.embed_model_names.keys(), f"Unsupported embed model: {config.embed_model}, only support {config.embed_model_names.keys()}"
    logger.debug(f"Loading embedding model {config.embed_model}")
    if provider == "local":
        model = LocalEmbeddingModel(config)

    elif provider == "zhipu":
        model = ZhipuEmbedding(config)

    elif provider == "ollama":
        model = OllamaEmbedding(config)

    else:
        model = OtherEmbedding(config)

    return model

def handle_local_model(paths, model_name, default_path):
    model_path = paths.get(model_name, default_path)
    return model_path
