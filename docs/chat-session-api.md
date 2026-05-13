# Chat Session API Documentation

## 📚 Overview

ThreatRAG's chat system utilizes a **dual-storage architecture (MySQL + Redis)** to balance persistence and performance:
- **MySQL**: The source of truth, persistently storing all session metadata and message history.
- **Redis**: The caching layer, providing low-latency retrieval for active sessions and frequent queries.

All chat records are cryptographically bound to specific user IDs to enforce multi-tenant isolation and session privacy.

---

## 🗄️ Database Schema

### 1. Chat Sessions Table (`chat_sessions`)

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `INT` | Primary Key (Auto-increment). |
| `session_id` | `VARCHAR(36)` | Unique UUID identifying the session. |
| `user_id` | `INT` | Foreign Key associated with `users.id`. |
| `title` | `VARCHAR(255)` | User-defined or auto-generated session title. |
| `system_prompt` | `TEXT` | Custom instructions governing LLM behavior for this session. |
| `created_at` | `DATETIME` | Record creation timestamp. |
| `updated_at` | `DATETIME` | Last modification timestamp. |
| `is_deleted` | `BOOLEAN` | Soft-deletion flag. |

**Indexes:**
- `idx_session_id`: Unique index for fast UUID lookup.
- `idx_user_id`: Standard index for listing user-specific sessions.

### 2. Chat Messages Table (`chat_messages`)

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `INT` | Primary Key (Auto-increment). |
| `session_id` | `VARCHAR(36)` | Reference to `chat_sessions.session_id`. |
| `role` | `VARCHAR(20)` | Message sender: `user`, `assistant`, or `system`. |
| `content` | `TEXT` | The raw text payload of the message. |
| `created_at` | `DATETIME` | Message timestamp. |
| `is_deleted` | `BOOLEAN` | Soft-deletion flag. |
| `meta` | `TEXT` | JSON-encoded metadata (tokens, model info, routing data). |

**Indexes:**
- `idx_session_id`: Standard index for retrieving full session history.

---

## 🚀 API Endpoints

### 1. Create a New Session
**Endpoint**: `POST /chat/sessions/create`

**Description**: Initializes a fresh conversation context.

**Request Body:**
```json
{
  "user_id": 1,
  "title": "Threat Intelligence Discussion",
  "system_prompt": "You are a senior CTI researcher specializing in APT tracking."
}
```

**Parameters:**
- `user_id` (Required): The ID of the owner.
- `title` (Optional): If omitted, the system generates a timestamp-based title.
- `system_prompt` (Optional): Overrides global defaults for this session.

**Response:**
```json
{
  "success": true,
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Session created successfully."
}
```

---

### 2. Stream Chat / Send Message
**Endpoint**: `POST /chat/stream`

**Description**: Primary interface for interactive dialogue. Supports both existing sessions and stateless auto-creation.

**Request Body:**
```json
{
  "query": "Analyze this IOC",
  "user_id": 1,
  "thread_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "meta": {
    "model_provider": "deepseek",
    "model_name": "deepseek-chat",
    "db_id": "kb_threat_intel",
    "use_graph": true
  }
}
```

**Parameters:**
- `query` (Required): User query text.
- `user_id` (Required): Valid user ID.
- `thread_id` (Optional): 
    - **Provided**: Continues an existing session.
    - **Omitted**: Automatically triggers a new session creation.
- `meta` (Optional): Configuration for RAG retrieval and model selection.

**Streaming Response Format:**
Chunks of JSON strings representing the generation progress.
```json
{"response": "Analyzing...", "status": "loading", "thread_id": "uuid-xxx"}
{"response": "Full result...", "status": "finished", "thread_id": "uuid-xxx"}
```

---

### 3. List User Sessions
**Endpoint**: `GET /chat/sessions`

**Description**: Retrieves a paginated list of sessions for a user.

**Query Parameters:**
- `user_id` (Required): Filter by owner.
- `limit` (Optional): Max records per page (default: 50).
- `offset` (Optional): Pagination offset (default: 0).

**Response:**
```json
{
  "success": true,
  "sessions": [
    {
      "session_id": "uuid-xxx",
      "title": "APT Attack Analysis",
      "created_at": "2025-10-16T14:30:00"
    }
  ],
  "total": 1
}
```

---

### 4. Fetch Session Details & History
**Endpoint**: `GET /chat/sessions/{thread_id}`

**Description**: Retrieves metadata and message history for a specific session.

**Query Parameters:**
- `user_id` (Required): Authorization verification.
- `include_messages` (Optional): Boolean to fetch full history (default: true).

---

### 5. Update Session Metadata
**Endpoint**: `PUT /chat/sessions/{thread_id}`

**Description**: Updates the session title or system prompt.

---

### 6. Delete Session
**Endpoint**: `DELETE /chat/sessions/{thread_id}`

**Parameters:**
- `hard_delete` (Optional): Set to `true` for permanent physical removal (default: `false` for soft-delete).

---

## 🔐 Security & Access Control

- **Identity Isolation**: Each API call validates `user_id` against the `thread_id` owner.
- **Unauthorized Access**: Attempting to access/modify another user's session results in a `404 Not Found` (to prevent ID enumeration).
- **Audit Logging**: All write operations are recorded for security monitoring.

---

## 💾 Caching Strategy

The system implements a **Read-Through / Write-Aside** caching policy:
1. **Reads**: Redis is checked first. If a cache miss occurs, data is fetched from MySQL and populated into Redis.
2. **Writes**: Updates are committed to MySQL first, then the corresponding Redis cache is invalidated.
3. **Invalidation**: 
    - Updating session info clears the session metadata cache.
    - Deleting/Adding messages clears the message history cache.
    - Cache TTL is set to **3600 seconds (1 hour)**.

---

## 🛠 Database Initialization

### Using CLI Scripts (Recommended)
```bash
python scripts/create_chat_tables.py create   # Initialize tables
python scripts/create_chat_tables.py recreate # Wipe and reset (CAUTION)
python scripts/create_chat_tables.py drop     # Remove all tables
```

### Manual SQL Migration
```sql
CREATE TABLE chat_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36) UNIQUE NOT NULL,
    user_id INT NOT NULL,
    title VARCHAR(255),
    system_prompt TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_deleted BOOLEAN DEFAULT FALSE,
    INDEX idx_user_id (user_id)
);

CREATE TABLE chat_messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(36) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    meta TEXT,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id)
);
```

---

## 📊 Integration Example (Python)

```python
import requests
import json

BASE_URL = "http://localhost:8006"
USER_ID = 1

def chat_stream(query, thread_id=None):
    payload = {
        "query": query,
        "user_id": USER_ID,
        "thread_id": thread_id
    }
    response = requests.post(f"{BASE_URL}/chat/stream", json=payload, stream=True)
    
    for line in response.iter_lines():
        if line:
            chunk = json.loads(line)
            print(chunk.get("response", ""), end="", flush=True)
```

---

## 📚 Related Documentation
- [Quick Start Guide](chat-session-quickstart.md)
- [Model Routing & Fallbacks](model-usage-examples.md)
- [Ollama Setup Guide](ollama-setup.md)
