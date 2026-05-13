# ThreatRAG Multi-Model Integration Guide

## 📚 Overview

ThreatRAG supports a diverse ecosystem of LLM providers, allowing you to select the optimal model based on reasoning complexity, latency requirements, and data privacy constraints.

| Provider | Core Strength | Primary Use Case |
| :--- | :--- | :--- |
| **OpenAI** | State-of-the-art reasoning | Complex strategic analysis, multi-step chain-of-thought. |
| **Ollama** | Local deployment & privacy | On-premise intelligence processing, sensitive data handling. |
| **DeepSeek** | Cost-efficiency & Code optimization | High-volume log analysis, automated exploit detection scripts. |

---

## 1. OpenAI Integration

### Environment Configuration
Add your API key to the `.env` file:
```dotenv
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
```

### Available Models & Tiers

| Model ID | Description | Context Window | Recommended For |
| :--- | :--- | :--- | :--- |
| `gpt-4o` | Flagship multimodal model | 128K | Advanced CTI synthesis & image-based forensics. |
| `gpt-4o-mini` | Cost-effective flagship | 128K | Daily dialogue and rapid triage. |
| `gpt-3.5-turbo` | Legacy efficiency | 16K | High-throughput batch classification tasks. |

### API Implementation Example

**Streaming Analysis:**
```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze the lateral movement tactics of APT-29.",
    "meta": {
      "model_provider": "openai",
      "model_name": "gpt-4o",
      "db_id": "kb_threat_intel",
      "use_graph": true
    }
  }'
```

---

## 2. Ollama (Local) Configuration

### Service Initialization
The Ollama service is bundled in the `docker-compose.yml` and initializes automatically.
```bash
docker compose up -d ollama

# Verify health status
curl http://localhost:11434/api/tags
```

### Recommended Local Models

| Model | Command | Strengths |
| :--- | :--- | :--- |
| **Qwen 2.5 (7B)** | `ollama pull qwen2.5:7b` | Excellent balance of performance & speed. |
| **DeepSeek R1 (7B)** | `ollama pull deepseek-r1:7b` | Optimized for logical reasoning and scripts. |
| **Llama 3.2 (3B)** | `ollama pull llama3.2:3b` | Ultra-fast execution for lightweight triage. |

### Hardware Acceleration (GPU)
The system is pre-configured for NVIDIA GPUs. Verify your setup:
```bash
docker exec -it threatrag-ollama nvidia-smi
```

### API Implementation Example (Local)

```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Identify attack patterns for IP 194.48.251.18",
    "meta": {
      "model_provider": "ollama",
      "model_name": "qwen2.5:7b",
      "db_id": "kb_security_logs",
      "use_graph": true
    }
  }'
```

---

## 3. DeepSeek Integration

### Environment Configuration
```dotenv
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```

### API Implementation Example (Script Generation)
```bash
curl -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Generate a Python detection script for this malware behavior.",
    "meta": {
      "model_provider": "deepseek",
      "model_name": "deepseek-chat",
      "db_id": "kb_malware_samples"
    }
  }'
```

---

## 🚀 Model Selection Strategy

### Scenario A: Complex APT Attribution
**Recommendation**: OpenAI `gpt-4o`.
- **Reason**: Requires high-fidelity synthesis of disparate reports.

### Scenario B: Air-Gapped Intelligence Analysis
**Recommendation**: Ollama `qwen2.5:14b`.
- **Reason**: Data privacy is paramount; local execution ensures no external leaks.

### Scenario C: High-Volume Log Classification
**Recommendation**: Ollama `llama3.2:3b` or `gpt-4o-mini`.
- **Reason**: Balance between token cost and classification accuracy.

---

## 📊 Performance Benchmark (Reference)

| Model | Time-To-First-Token (TTFT) | Tokens Per Second (TPS) | Reliability |
| :--- | :--- | :--- | :--- |
| **Ollama (GPU)** | ~50ms | 60+ | High (Local) |
| **DeepSeek (API)** | ~150ms | 30+ | Medium (Network) |
| **OpenAI (GPT-4o)** | ~300ms | 25+ | High (Managed) |

---

## 🛠 Troubleshooting & Best Practices

### Connection Refused (OpenAI)
1. Verify `OPENAI_API_KEY` is exported.
2. Check network connectivity to `api.openai.com`.

### Low Performance (Ollama)
1. Ensure `nvidia-container-toolkit` is installed.
2. Monitor VRAM usage with `nvidia-smi`.
3. Consider using a smaller model (e.g., 3B instead of 14B) if memory is constrained.

### Graceful Fallback Implementation (Pseudo-code)
```python
def execute_query(query):
    try:
        # Attempt high-performance cloud model
        return api_call(provider="openai", model="gpt-4o")
    except Exception as e:
        # Fallback to local execution if API fails
        print(f"Cloud API failed: {e}. Falling back to Ollama...")
        return api_call(provider="ollama", model="qwen2.5:7b")
```

---

## 📚 Related Documentation
- [Chat API Specification](chat-session-api.md)
- [Frontend Integration Guide](frontend-api-guide.md)
- [Workflow Logic](chat-api-workflow.md)
