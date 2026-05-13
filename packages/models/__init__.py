import os
import traceback
from .. import config
from ..utils.logging_config import logger
from .chat_model import OpenAIBase
from .router import ModelRouter, ModelRoutingUnavailableError, RoutedPrediction


def select_model(model_provider=None, model_name=None):
    """Model selection based on model provider"""
    model_provider = model_provider or config.model_provider
    model_info = config.model_names.get(model_provider, {})
    model_name = model_name or config.model_name or model_info.get("default", "")


    logger.info(f"Selecting model from `{model_provider}` with `{model_name}`")


    if model_provider is None:
        raise ValueError("Model provider not specified, please modify `model_provider` in `src/config/base.yaml`")

    # OpenAI official (through transit station)
    if model_provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables")
        
        # Use stop address (configurable)
        base_url = os.getenv("OPENAI_BASE_URL", "https://jeniya.top/v1")
        logger.info(f"Using OpenAI via proxy: {base_url}")

        model = OpenAIBase(
            api_key=api_key,
            base_url=base_url,
            model_name=model_name or "gpt-4o-mini", # Based on your example, the default model is set to gpt-4.1
        )
        return model
    
    # Ollama Local Model
    if model_provider == "ollama":
        ollama_base = os.getenv("OLLAMA_API_BASE", "http://ollama:11434")
        model = OpenAIBase(
            api_key="ollama",  # Ollama doesn't need real API Key
            base_url=f"{ollama_base}/v1",
            model_name=model_name or "qwen3:30b",  # Default use qwen3.5 30b
        )
        return model

    # DeepSeek
    if model_provider == "deepseek":
        from .chat_model import DeepSeek
        return DeepSeek(model_name)

    # Custom Model
    if model_provider == "custom":
        model_info = next((x for x in config.custom_models if x["custom_id"] == model_name), None)
        if model_info is None:
            raise ValueError(f"Model {model_name} not found in custom models")

        from .chat_model import CustomModel
        return CustomModel(model_info)

    # Other models, default using OpenABase (provider compatible with OpenAI API format)
    try:
        model = OpenAIBase(
            api_key=os.getenv(model_info["env"][0]),
            base_url=model_info["base_url"],
            model_name=model_name,
        )
        return model
    except Exception as e:
        raise ValueError(f"Model provider {model_provider} load failed, {e} \n {traceback.format_exc()}")


def build_model_router(config=None, runtime_store=None, factory=None):
    return ModelRouter(config=config, runtime_store=runtime_store, factory=factory)
