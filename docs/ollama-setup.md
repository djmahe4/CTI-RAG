# Ollama Local Model Integration Guide

## 📚 Overview

Ollama is fully integrated into the ThreatRAG ecosystem, enabling the use of locally hosted open-source Large Language Models (LLMs) for sensitive threat intelligence analysis and privacy-conscious workflows.

---

## 🚀 Quick Start

### 1. Start the Ollama Container
Ensure the Ollama service is defined in your `docker-compose.yml` and initiate it:
```bash
docker compose up -d ollama
```

### 2. Download Recommended Models
Access the Ollama container and pull the models required for your specific analysis tasks:

```bash
# Enter the container
docker exec -it threatrag-ollama bash

# Pull models for various use cases
ollama pull llama3.2:3b          # Optimized for speed and triage
ollama pull qwen2.5:7b           # High-fidelity Chinese & logic support
ollama pull deepseek-r1:7b       # Specialized for chain-of-thought reasoning
ollama pull mistral:7b           # General-purpose performance

# Verify downloaded models
ollama list

# Exit the container
exit
```

### 3. Configure ThreatRAG Integration
Update your `config.yaml` to register the local models.

**Option A: Custom Model Definition**
```yaml
custom_models:
  - custom_id: "ollama-llama3"
    base_url: "http://ollama:11434/v1"
    api_key: "ollama"  # Placeholder value
    model_name: "llama3.2:3b"
```

**Option B: Independent Provider Definition**
```yaml
model_names:
  ollama:
    base_url: "http://ollama:11434/v1"
    default: "llama3.2:3b"
    models: ["llama3.2:3b", "qwen2.5:7b", "deepseek-r1:7b"]
```

---

## 📊 Interaction Examples

### Pattern 1: Using Custom Configuration
```bash
curl -X POST http://localhost:8006/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Assess the risk level of this IOC payload.",
    "meta": {
      "model_provider": "custom",
      "model_name": "ollama-qwen"
    }
  }'
```

---

## 🚀 Model Recommendations

### ⚡ Rapid Triage (Real-time Analysis)
- **Llama 3.2 (3B)**: Meta's ultra-fast lightweight model.
- **Phi-3 (3.8B)**: Microsoft's efficiency-optimized powerhouse.

### 🧠 Strategic Analysis (Complex Reasoning)
- **DeepSeek-R1 (7B)**: Unparalleled chain-of-thought capabilities.
- **Llama 3.1 (8B)**: High-fidelity general performance.

### 🛠 Specialized Tasks
- **CodeLlama (7B)**: Malware behavior analysis and de-obfuscation.
- **SQLCoder (7B)**: Automated Cypher/SQL query generation.

---

## 🏎 Hardware Acceleration (GPU)

To enable NVIDIA GPU support:

1. **Install NVIDIA Container Toolkit**:
```bash
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

2. **Update `docker-compose.yml`**:
Ensure the `deploy` resources are uncommented for the Ollama service.

---

## 🛠 Performance Optimization

1. **Concurrency Control**: 
Set `OLLAMA_NUM_PARALLEL` to allow multiple simultaneous requests.
2. **Quantization Levels**:
Use `Q4_0` quantization for the best balance of accuracy and memory footprint:
```bash
ollama pull qwen2.5:7b-q4_0
```
3. **KV Caching**:
Ensure persistent caching is enabled to accelerate repetitive intelligence queries.

---

## ❓ FAQ & Troubleshooting

**Q: Container is running but the API is unreachable.**
- **Fix**: Check logs using `docker logs threatrag-ollama`. Verify port mapping (11434).

**Q: Model downloads are extremely slow.**
- **Fix**: Use a local mirror or regional registry if available.

**Q: GPU is not being utilized.**
- **Fix**: Run `nvidia-smi` to ensure the driver is active and verify Docker runtime configuration.

---

## 📚 Resources
- [Official Ollama Documentation](https://github.com/ollama/ollama)
- [Ollama Model Library](https://ollama.com/library)
- [ThreatRAG Model Integration Standards](model-usage-examples.md)
