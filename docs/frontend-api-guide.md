# ThreatRAG Chat API - Frontend Integration Guide

## 📌 Implementation Basics

**API Base URL**: `http://localhost:8006`
**Authentication**: Currently stateless (all requests must include a valid `user_id` for authorization).
**Data Format**: JSON (Request) / Line-delimited JSON (Stream Response).

---

## 🚀 Core Endpoints

### 1. Send Message: `POST /chat/stream`
The primary interface for interaction. Supports both session initialization and ongoing dialogue.

#### Mode A: Zero-Config Initialization (Quick Mode)
```javascript
fetch('http://localhost:8006/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: "Explain recent log4j variants.",
    user_id: 1,
    meta: {
      title: "Vulnerability Analysis",
      system_prompt: "You are a senior CTI researcher.",
      model_provider: "deepseek"
    }
  })
})
```

#### Mode B: Continuous Dialogue (Standard Mode)
```javascript
fetch('http://localhost:8006/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: "What are the common IOCs for this?",
    user_id: 1,
    thread_id: "PERSISTED_SESSION_ID"
  })
})
```

#### Stream Processing Logic
The server responds with a `ReadableStream` of line-delimited JSON objects:
```javascript
// Response Chunk 1: Processing state
{"response": "Analyzing the logs...", "status": "loading", "thread_id": "uuid-123"}

// Response Chunk 2: Conclusion state
{"status": "finished", "thread_id": "uuid-123", "history": [...]}
```

---

### 2. Session Management

#### Create Session: `POST /chat/sessions/create`
Pre-allocate a conversation context.
```javascript
const response = await fetch('/chat/sessions/create', {
  method: 'POST',
  body: JSON.stringify({ user_id: 1, title: "APT-29 Investigation" })
});
```

#### List Sessions: `GET /chat/sessions`
Populate your sidebar or workspace navigation.
- `user_id` (Required)
- `limit` (Optional, Default: 50)

#### Delete Session: `DELETE /chat/sessions/{id}`
Soft-delete (default) or hard-purge a record.

---

## 💡 Frontend Architecture Recommendations

### 1. State Management Pattern
Implement a robust client-side manager to handle UUID persistence and UI state synchronization.

```typescript
class ChatManager {
  private currentThreadId: string | null = null;

  async handleQuery(text: string, userId: number) {
    const response = await fetch('/chat/stream', {
      method: 'POST',
      body: JSON.stringify({
        query: text,
        user_id: userId,
        thread_id: this.currentThreadId // Null for new chats
      })
    });

    const reader = response.body.getReader();
    // ... logic to parse line-by-line ...
    // Extract thread_id from the first chunk and save it
  }
}
```

### 2. Stream Handling Utility
Use the native `ReadableStream` API for the best UX (no waiting for the full response).

```javascript
async function consumeStream(reader, onToken) {
  const decoder = new TextDecoder();
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split('\n').filter(l => l.trim());
    
    for (const line of lines) {
      const data = JSON.parse(line);
      if (data.response) onToken(data.response);
      if (data.status === 'finished') handleCompletion(data);
    }
  }
}
```

---

## 🎨 UI/UX Component Guidelines

### Layout Strategy
- **Sidebar**: List recent sessions with `GET /chat/sessions`. Support renaming via `PUT`.
- **Main Chat**: Use a scrollable container with real-time token appending.
- **Header**: Display the current session title and model routing metadata (e.g., "DeepSeek (RAG Enabled)").

### Error Recovery
- **404 Handling**: If a `thread_id` is invalid/expired, gracefully notify the user and offer to start a "New Session" (retry without the ID).
- **Network Interruptions**: Implement a "Retry" button for failed fetch calls.

---

## ⚠️ Security & Performance Checklist

### ✅ Do's
- **Persistence**: Store `thread_id` in `localStorage` to survive page refreshes.
- **Identity**: Always verify that the `user_id` sent matches the authenticated user context.
- **Validation**: Enforce a 50-character limit on titles in the UI before sending to the API.

### ❌ Don'ts
- **Global Context Leak**: Never hardcode `user_id`. Retrieve it from your Auth provider.
- **Blocking Calls**: Do not wait for the stream to end before showing the UI. Streaming is critical for "perceived performance."

---

## 🛠 Debugging
Test your integration directly from the browser console:
```javascript
const res = await fetch('http://localhost:8006/chat/stream', {
  method: 'POST',
  body: JSON.stringify({ query: 'Ping', user_id: 1 })
});
console.log("Stream initialized successfully.");
```

---

## 📚 Technical References
- [Full API Specification](chat-session-api.md)
- [Workflow & Sequence Diagrams](chat-api-workflow.md)
- [Model Routing Deep Dive](model-usage-examples.md)
