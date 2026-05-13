# ThreatRAG Chat API - Frontend Integration Guide

## 📌 Basic Information

**API Base URL:** `http://localhost:8006`

**Authentication:** None for now (all requests must include `user_id`)

**Data Format:** JSON

---

## 🚀 Core Endpoints (Required Reading)

### 1. Send Message - POST `/chat/stream`

**Most important endpoint, supports two usage modes:**

#### Mode A: Auto-create session (recommended for first message)

```javascript
fetch('http://localhost:8006/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: "User input question",
    user_id: 1,  // ID of the currently logged-in user
    meta: {
      title: "Session title",  // Optional
      system_prompt: "You are an assistant",  // Optional
      model_provider: "deepseek"  // Optional: openai/deepseek/ollama
    }
  })
})
```

#### Mode B: Continue an existing session

```javascript
fetch('http://localhost:8006/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: "Continue asking",
    user_id: 1,
    thread_id: "Saved session ID"  // From the first response
  })
})
```

#### Response format (streaming)

The response is JSON returned **line by line**, one object per line:

```javascript
// Line 1: Loading
{"response": "Thinking", "status": "loading", "thread_id": "abc123..."}

// Line 2: Continue loading
{"response": "...", "status": "loading", "thread_id": "abc123..."}

// Line 3: Finished
{"status": "finished", "thread_id": "abc123...", "history": [...]}
```

#### Frontend handling example

```javascript
async function sendMessage(query, threadId = null) {
  const response = await fetch('http://localhost:8006/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      user_id: getCurrentUserId(),
      ...(threadId && { thread_id: threadId })
    })
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let sessionId = null;
  let fullText = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value);
    const lines = chunk.split('\n').filter(line => line.trim());

    for (const line of lines) {
      const data = JSON.parse(line);
      
      // Save session ID (on first conversation)
      if (data.thread_id && !sessionId) {
        sessionId = data.thread_id;
        localStorage.setItem('current_session_id', sessionId);
      }

      // Display AI response in real time
      if (data.response) {
        fullText += data.response;
        updateChatUI(fullText);  // Update UI
      }

      // Conversation finished
      if (data.status === 'finished') {
        console.log('Conversation finished', { sessionId, fullText });
        return { sessionId, fullText };
      }
    }
  }
}
```

---

### 2. Create Session - POST `/chat/sessions/create`

**Optional endpoint for pre-creating sessions**

```javascript
fetch('http://localhost:8006/chat/sessions/create', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_id: 1,
    title: "My session",  // Optional, max 50 characters
    system_prompt: "You are an assistant"  // Optional
  })
})
```

**Response:**
```json
{
  "success": true,
  "session_id": "abc123-def456-...",
  "message": "Session created successfully"
}
```

---

### 3. Get session list - GET `/chat/sessions`

**Query parameters:**
- `user_id` (required): User ID
- `limit` (optional): Number of results, default 50
- `offset` (optional): Offset, default 0

```javascript
fetch(`http://localhost:8006/chat/sessions?user_id=1&limit=20`)
  .then(res => res.json())
  .then(data => {
    console.log(data.sessions);  // Session list
  });
```

**Response:**
```json
{
  "success": true,
  "sessions": [
    {
      "session_id": "abc123...",
      "title": "Threat Intelligence Discussion",
      "created_at": "2025-10-16T14:30:00",
      "updated_at": "2025-10-16T15:00:00"
    }
  ],
  "total": 10
}
```

---

### 4. Get session details - GET `/chat/sessions/{session_id}`

**Query parameters:**
- `user_id` (required): User ID
- `include_messages` (optional): Whether to include messages, default true

```javascript
fetch(`http://localhost:8006/chat/sessions/abc123?user_id=1&include_messages=true`)
  .then(res => res.json())
  .then(data => {
    console.log(data.session);  // Session details
    console.log(data.session.messages);  // Message history
  });
```

**Response:**
```json
{
  "success": true,
  "session": {
    "session_id": "abc123...",
    "title": "Threat Intelligence Discussion",
    "messages": [
      {
        "role": "user",
        "content": "What is an APT attack?",
        "created_at": "2025-10-16T14:30:00"
      },
      {
        "role": "assistant",
        "content": "APT is...",
        "created_at": "2025-10-16T14:30:05"
      }
    ]
  }
}
```

---

### 5. Update session - PUT `/chat/sessions/{session_id}`

```javascript
fetch('http://localhost:8006/chat/sessions/abc123', {
  method: 'PUT',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_id: 1,
    title: "New title"  // Optional, max 50 characters
  })
})
```

---

### 6. Delete session - DELETE `/chat/sessions/{session_id}`

**Query parameters:**
- `user_id` (required): User ID
- `hard_delete` (optional): Physical delete, default false (soft delete)

```javascript
fetch(`http://localhost:8006/chat/sessions/abc123?user_id=1`, {
  method: 'DELETE'
})
```

---

## 💡 Frontend Development Recommendations

### 1. Session management strategy

```typescript
class ChatSessionManager {
  private currentSessionId: string | null = null;
  private readonly MAX_TITLE_LENGTH = 50;

  // Validate and truncate title
  private validateTitle(title: string): string {
    if (!title) return title;
    if (title.length > this.MAX_TITLE_LENGTH) {
      console.warn(`Title too long, truncated to ${this.MAX_TITLE_LENGTH} characters`);
      return title.substring(0, this.MAX_TITLE_LENGTH);
    }
    return title;
  }

  // Start a new conversation
  async startNewChat(query: string, userId: number, title?: string) {
    const result = await this.sendMessage(query, userId, null, title);
    this.currentSessionId = result.sessionId;
    return result;
  }

  // Continue current conversation
  async continueChat(query: string, userId: number) {
    if (!this.currentSessionId) {
      return this.startNewChat(query, userId);
    }
    return this.sendMessage(query, userId, this.currentSessionId);
  }

  // Switch session
  switchSession(sessionId: string) {
    this.currentSessionId = sessionId;
    localStorage.setItem('current_session_id', sessionId);
  }

  // Update session title
  async updateSessionTitle(sessionId: string, userId: number, title: string) {
    const validatedTitle = this.validateTitle(title);
    
    const response = await fetch(`/chat/sessions/${sessionId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        user_id: userId,
        title: validatedTitle
      })
    });
    
    return await response.json();
  }

  // Send message
  private async sendMessage(
    query: string, 
    userId: number, 
    threadId?: string,
    title?: string
  ) {
    const body: any = { query, user_id: userId };
    
    if (threadId) {
      body.thread_id = threadId;
    } else if (title) {
      // Validate title when creating a new session
      body.meta = { title: this.validateTitle(title) };
    }
    
    // ... implement streaming handling
  }
}
```

---

### 2. Data persistence

```javascript
// Save current session ID
localStorage.setItem('current_session_id', sessionId);

// Restore session
const lastSessionId = localStorage.getItem('current_session_id');
if (lastSessionId) {
  // Load historical messages
  loadSessionHistory(lastSessionId);
}
```

---

### 3. Error handling

```javascript
async function sendMessage(query, threadId) {
  try {
    const response = await fetch('/chat/stream', {
      method: 'POST',
      body: JSON.stringify({ query, user_id: 1, thread_id: threadId })
    });

    if (response.status === 404) {
      // Session does not exist, create a new one
      console.log('Session expired, creating new session');
      return sendMessage(query, null);  // no thread_id
    }

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    // Handle response...
  } catch (error) {
    console.error('Send failed:', error);
    showError('Failed to send message, please try again');
  }
}
```

---

## 🎨 UI Component Recommendations

### Chat interface layout

```
┌─────────────────────────────────────┐
│  [Session List]  │  [Chat Area]     │
│                  │                   │
│  Session 1       │  User: Hello      │
│  Session 2       │  AI: Hello!       │
│  Session 3 ✓     │                   │
│                  │  User: ...        │
│  [+ New Session] │  AI: ...          │
│                  │                   │
│                  │  [Input_________] │
│                  │  [Send] [Clear]   │
└─────────────────────────────────────┘
```

### React example component

```tsx
function ChatInterface() {
  const [sessions, setSessions] = useState([]);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');

  // Send message
  const handleSend = async () => {
    const result = await sendMessage(input, currentSessionId);
    setCurrentSessionId(result.sessionId);
    // Update message list...
  };

  // Create new session
  const handleNewSession = async () => {
    const result = await sendMessage('Hello', null);
    setCurrentSessionId(result.sessionId);
    loadSessions();  // Refresh session list
  };

  return (
    <div className="chat-interface">
      <SessionList 
        sessions={sessions} 
        onSelect={setCurrentSessionId}
        onNew={handleNewSession}
      />
      <ChatArea 
        messages={messages}
        input={input}
        onInputChange={setInput}
        onSend={handleSend}
      />
    </div>
  );
}
```

---

## 📊 Data Flow Diagram

```
User action         Frontend process          API call             Backend process
   │                      │                      │                      │
   │ Click "Send"         │                      │                      │
   ├─────────────────────▶│                      │                      │
   │                      │ Call sendMessage()   │                      │
   │                      ├─────────────────────▶│ POST /chat/stream    │
   │                      │                      ├─────────────────────▶│
   │                      │                      │                      │ Create/get session
   │                      │                      │                      │ Generate response
   │                      │                      │                      │
   │                      │  Streaming response ◀┤◀─────────────────────┤
   │                      │  {"response": "..."}                       │
   │                      │                      │                      │
   │ Real-time display ◀──┤                      │                      │
   │ AI response          │ Update UI            │                      │
   │                      │                      │                      │
   │                      │  {"status": "finished", "thread_id": "..."}
   │                      │                      │                      │
   │                      │ Save thread_id       │                      │
   │                      │ to localStorage      │                      │
```

---

## ⚠️ Important Notes

### ✅ Must-do items

1. **Save thread_id**: Extract and store it after first conversation
2. **Error handling**: Handle network errors and 404 (session not found)
3. **Streaming handling**: Parse response line-by-line with ReadableStream
4. **User feedback**: Show loading state and error messages
5. **Title length limit**: Session title max is 50 characters, longer titles are truncated automatically

### ❌ Common mistakes

1. **Forgetting to save thread_id**: Causes a new session each time
2. **Not handling streaming response**: Only final output is visible
3. **user_id mismatch**: Trying to access another user's session
4. **No session validation**: Using a deleted `session_id`
5. **Overlong title**: Titles over 50 chars are truncated; enforce on frontend in advance

---

## 🔧 Debugging Tools

### Browser console test

```javascript
// Test sending a message
fetch('http://localhost:8006/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: 'Hello',
    user_id: 1
  })
}).then(res => res.body.getReader()).then(reader => {
  const decoder = new TextDecoder();
  reader.read().then(function processText({ done, value }) {
    if (done) return;
    console.log(decoder.decode(value));
    return reader.read().then(processText);
  });
});
```

---

## 📞 Contact

Having issues?
- Check detailed docs: `docs/chat-session-api.md`
- Check full examples: `docs/chat-session-quickstart.md`
- Check workflow: `docs/chat-api-workflow.md`

---

## 📝 Quick Reference

| Endpoint | Method | Purpose | Required Parameters |
|------|------|------|---------|
| `/chat/stream` | POST | Send message | `query`, `user_id` |
| `/chat/sessions/create` | POST | Create session | `user_id` |
| `/chat/sessions` | GET | Session list | `user_id` |
| `/chat/sessions/{id}` | GET | Session details | `user_id` |
| `/chat/sessions/{id}` | PUT | Update session | `user_id` |
| `/chat/sessions/{id}` | DELETE | Delete session | `user_id` |

---

**Version:** 1.0  
**Updated:** 2025-10-16  
**Compatibility:** All modern browsers (Fetch API and ReadableStream required)
