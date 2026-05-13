# Chat Session System Quick Start

## 🎯 Overview

ThreatRAG now supports robust multi-session management. All chat records are bound to user IDs and stored using a high-performance **MySQL + Redis** dual-layer architecture.

---

## 🚀 Fast Start (5-Minute Setup)

### 1️⃣ Initialize Database Schema
Run the migration script to create the necessary tables in your MySQL instance.

```bash
# Navigate to the project root
cd /path/to/ThreatRAG

# Initialize chat-related tables
python scripts/create_chat_tables.py create
```

**Expected Output:**
```text
✅ Chat tables created successfully!
Tables created:
  - chat_sessions (Metadata storage)
  - chat_messages (Message history storage)
```

### 2️⃣ Start Services
Ensure all backend components are active.

```bash
# Option A: Start using Docker Compose
docker compose up -d

# Option B: Start FastAPI manually
python main.py
```

### 3️⃣ Start Chatting (Two Interaction Patterns)

#### Pattern A: Quick Mode (Direct Chat)
Start a conversation instantly. The system will automatically create a session if no `thread_id` is provided.

```bash
curl -X POST http://localhost:8006/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Analyze recent APT trends.",
    "user_id": 1,
    "meta": {
      "title": "Threat Intel Discussion",
      "system_prompt": "You are a professional CTI analyst.",
      "model_provider": "deepseek"
    }
  }'
```
- **Advantage**: Zero setup; immediate response.
- **Note**: Save the `thread_id` from the response to continue the conversation.

#### Pattern B: Standard Mode (Pre-Created Session)
Explicitly create a session for better control over titles and configuration.

**Step 1: Create Session**
```bash
curl -X POST http://localhost:8006/chat/sessions/create \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": 1,
    "title": "Malware Analysis Lab",
    "system_prompt": "Focus on reverse engineering perspectives."
  }'
```

**Step 2: Send Message**
```bash
curl -X POST http://localhost:8006/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Identify common unpacking techniques.",
    "user_id": 1,
    "thread_id": "YOUR_SESSION_ID"
  }'
```

---

### 4️⃣ Continue the Conversation
Always provide the `thread_id` to maintain multi-turn context.

```bash
curl -X POST http://localhost:8006/chat/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Give me examples of those techniques.",
    "user_id": 1,
    "thread_id": "YOUR_SESSION_ID"
  }'
```

---

### 5️⃣ Manage Your Sessions

**List all active sessions:**
```bash
curl "http://localhost:8006/chat/sessions?user_id=1&limit=10"
```

**Fetch specific history:**
```bash
curl "http://localhost:8006/chat/sessions/YOUR_SESSION_ID?user_id=1&include_messages=true"
```

---

## 🛠 Core Functionality Table

| Feature | Description | Endpoint |
| :--- | :--- | :--- |
| **Create Session** | Manual initialization of a chat context. | `POST /chat/sessions/create` |
| **Stream Chat** | Send queries and receive real-time answers. | `POST /chat/stream` |
| **Session List** | Retrieve all conversations for a user. | `GET /chat/sessions` |
| **Update Session** | Rename titles or update system instructions. | `PUT /chat/sessions/{id}` |
| **Delete Session** | Soft-delete or hard-purge a conversation. | `DELETE /chat/sessions/{id}` |
| **Data Isolation** | Multi-tenant security based on `user_id`. | Automated |

---

## 🎨 Frontend Integration (TypeScript Example)

```typescript
class ThreatRAGClient {
  private baseUrl = "http://localhost:8006";
  private userId: number;

  constructor(userId: number) {
    this.userId = userId;
  }

  async createSession(title: string) {
    const res = await fetch(`${this.baseUrl}/chat/sessions/create`, {
      method: "POST",
      body: JSON.stringify({ user_id: this.userId, title })
    });
    return await res.json();
  }

  async sendMessage(query: string, threadId: string) {
    return await fetch(`${this.baseUrl}/chat/stream`, {
      method: "POST",
      body: JSON.stringify({ query, user_id: this.userId, thread_id: threadId })
    });
  }
}
```

---

## 🧪 Verification Script
A complete Python test suite is available in `scripts/test_chat_sessions.py`. Run it to verify your local environment:

```bash
python scripts/test_chat_sessions.py
```

---

## ❓ FAQ

**Q: How do I reset the entire chat database?**
```bash
python scripts/create_chat_tables.py recreate
```

**Q: How do I inspect the Redis cache?**
```bash
docker exec -it threatrag-redis redis-cli
KEYS chat_session:*
```

**Q: How do I export my chat history?**
```bash
docker exec threatrag-mysql mysqldump -u mysql -p12345678 knowledge_db chat_sessions chat_messages > backup.sql
```

---

## 📚 Related Documentation
- [Full API Specification](chat-session-api.md)
- [Workflow Diagrams](chat-api-workflow.md)
- [Model Switching & Routing](model-usage-examples.md)
