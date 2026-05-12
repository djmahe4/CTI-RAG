from pathlib import Path

import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_models_yaml_declares_dashscope_text_embedding_v4():
    models = yaml.safe_load((ROOT / "packages" / "static" / "models.yaml").read_text(encoding="utf-8"))

    embed_info = models["EMBED_MODEL_INFO"]
    assert "dashscope/text-embedding-v4" in embed_info

    spec = embed_info["dashscope/text-embedding-v4"]
    assert spec["name"] == "text-embedding-v4"
    assert spec["api_key"] == "DASHSCOPE_API_KEY"
    assert spec["url"] == "DASHSCOPE_BASE_URL"
    assert spec["dimension"] == 1024


def test_config_yaml_switches_to_remote_dashscope_embedding_and_cpu_safe_devices():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    assert cfg["embed_model"] == "dashscope/text-embedding-v4"
    assert cfg["device"] == "cpu"
    assert cfg["rl_device"] == "cpu"


def test_source_allows_dashscope_embedding_and_resolves_url_from_env_name():
    config_source = (ROOT / "packages" / "config" / "__init__.py").read_text(encoding="utf-8")
    embedding_source = (ROOT / "packages" / "models" / "embedding.py").read_text(encoding="utf-8")

    assert '"dashscope/"' in config_source
    assert 'raw_url = self.info["url"]' in embedding_source
    assert 'os.getenv(raw_url, raw_url)' in embedding_source
    assert 'OpenAI(api_key=self.api_key, base_url=self.url)' in embedding_source
    assert 'self.client.embeddings.create(' in embedding_source
    assert 'self.url.rstrip("/").endswith("/embeddings")' not in embedding_source
