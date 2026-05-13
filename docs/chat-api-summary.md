# Chat API Summary

## Core Features

The ThreatRAG Chat System offers **two flexible interaction patterns**:

### Method 1: Quick Mode (Auto-Creation)
**Seamlessly start a conversation without manual session management.**

```bash
curl -X POST http://localhost:8006/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Hello",
    "user_id": 1
  }'
```
- **Behavior**: If no `thread_id` is provided, the system automatically creates a new session.
- **Output**: Returns the generated `thread_id` in the first response chunk or metadata.
- **Best For**: Rapid testing, simple chatbots, and quick integration.

### Method 2: Standard Mode (Controlled Management)
**Explicitly manage the session lifecycle for full visibility and control.**

```bash
# 1. Create a Session
curl -X POST http://localhost:8006/chat/sessions/create \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "title": "Cyber Threat Analysis"}'

# 2. Send Message using the Session ID
curl -X POST http://localhost:8006/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "Explain APT tactics", "user_id": 1, "thread_id": "YOUR_SESSION_ID"}'
```
- **Behavior**: Requires a pre-existing `thread_id`.
- **Best For**: Production applications, multi-tab interfaces, and persistent workspace environments.

---

## 📊 Comparison Table

| Feature | Quick Mode | Standard Mode |
| :--- | :--- | :--- |
| **API Calls** | 1 (Direct Chat) | 2 (Create + Chat) |
| **Session Lifecycle** | Automated creation | Manual CRUD operations |
| **Use Case** | Prototyping, one-off queries | Enterprise apps, full history management |
| **Customization** | Set via `meta.title` / `meta.system_prompt` | Configured during creation or updated via PUT |

---

## 🚀 Quick Start Example

### 1. Initiate Conversation (Quick Mode)

```bash
curl -X POST http://localhost:8006/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is an APT attack?",
    "user_id": 1,
    "meta": {
      "title": "Threat Intelligence Inquiry",
      "system_prompt": "You are a professional Cyber Threat Intelligence (CTI) analyst.",
      "model_provider": "deepseek"
    }
  }'
```

**Response Metadata Snippet:**
```json
{
  "response": "An Advanced Persistent Threat (APT) is...",
  "status": "loading",
  "thread_id": "a1b2c3d4-..."  // IMPORTANT: Save this ID for follow-up questions!
}
```

### 2. Follow-up Conversation

```bash
curl -X POST http://localhost:8006/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "How can we defend against it?",
    "user_id": 1,
    "thread_id": "a1b2c3d4-..."
  }'
```

---

## 💡 Best Practices

### ✅ Recommended Implementation
1. **Developer Sandbox**: Use Quick Mode to test prompts and model behaviors without overhead.
2. **Production Grade**: Always use `POST /chat/sessions/create` to ensure the UI can display session titles immediately.
3. **Persistence**: Clients MUST store the `thread_id` (e.g., in `localStorage` or a database) to maintain context.
4. **Maintenance**: Implement routine cleanup for orphaned sessions to optimize storage performance.

### ⚠️ Implementation Warnings
1. **User ID Mandatory**: Every request requires a valid `user_id` for auditing and data isolation.
2. **Strict RBAC**: Users can only access sessions they own; unauthorized `thread_id` access returns `404 Not Found`.
3. **ID Durability**: `thread_id` is a UUID. Ensure your client-side state management handles it as a unique key.

---

## 📝 API Reference Overview

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/chat/sessions/create` | `POST` | Manually initialize a new session. |
| `/chat/stream` | `POST` | Core chat endpoint (supports streaming and auto-creation). |
| `/chat/sessions` | `GET` | Retrieve a list of all sessions for a specific user. |
| `/chat/sessions/{id}` | `GET` | Fetch specific session metadata. |
| `/chat/sessions/{id}` | `PUT` | Update session properties (e.g., Title, System Prompt). |
| `/chat/sessions/{id}` | `DELETE` | Permanently remove a session and its history. |
| `/chat/sessions/{id}/messages` | `GET` | Fetch full message history for a session. |

---

## 🛠 Integration Scenarios

### Scenario 1: Mobile App / Lightweight Client
**Recommendation**: Use **Quick Mode** for zero-latency startup.

```typescript
async function sendMessage(query: string) {
  const response = await fetch('/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      user_id: currentUserId
    })
  });
  
  // Extract and persist thread_id for subsequent turns
  const data = await response.json();
  saveThreadId(data.thread_id);
}
```

### Scenario 2: Web Management Console
**Recommendation**: Use **Standard Mode** for robust session organization.

```typescript
class SessionManager {
  async createTopicSession(topic: string) {
    const res = await fetch('/chat/sessions/create', {
      method: 'POST',
      body: JSON.stringify({ user_id: currentUserId, title: topic })
    });
    return await res.json();
  }
  
  async chat(sessionId: string, query: string) {
    return await fetch('/chat/stream', {
      method: 'POST',
      body: JSON.stringify({ query, user_id: currentUserId, thread_id: sessionId })
    });
  }
}
```

---

## 📈 System Resilience & Routing

### Model Routing Metadata
The chat interface provides transparency into the routing decisions. Responses include:
- `expected_model_provider`
- `actual_model_provider`
- `is_degraded`: Boolean flag indicating if a fallback model was used.
- `routing_reason`: Context on why a specific provider was selected.

### Runtime Configuration
Ensure the following environment variables are optimized for production:

```dotenv
MODEL_ROUTER_ENABLED=true
MODEL_ROUTER_DEFAULT_PROVIDER=deepseek
MODEL_CIRCUIT_BREAKER_ENABLED=true
MODEL_CIRCUIT_BREAKER_FAILURE_THRESHOLD=5
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
```

### Background Infrastructure
- **RabbitMQ**: Handles model health checks and asynchronous task orchestration.
- **Redis**: Caches session states and frequent queries for high-performance retrieval.
