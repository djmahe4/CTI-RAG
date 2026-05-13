# CTI-RAG Interview Presentation (Complete Answer Version)

## I. Project Overview (1 minute)
I have built a GraphRAG system tailored for Cyber Threat Intelligence (CTI) question-answering. The main pipeline consists of:

`Vector Retrieval + Graph Retrieval + Reinforcement Learning Edge Pruning + LLM Generation`

The goal is not just to compress the input, but to reduce context noise and inference costs without significantly compromising answer quality. In my experiments, the average subgraph size was reduced from `14.12` to `6.50` (a `53.96%` decrease), and the average tokens decreased from `4936.24` to `2564.71` (a `48.04%` decrease).

---

## II. Core Workflow (3 minutes)

### 1) Request Ingestion
User queries enter the FastAPI service, where they undergo parameter validation, rate limiting, and `request_id` generation for full-chain tracing.

### 2) Retrieval Phase
Semantic retrieval is performed first via vector search to obtain relevant candidates. Then, the corresponding K-hop subgraphs are extracted from the graph database to form a candidate evidence graph.

### 3) RL Pruning Phase
The candidate subgraph is fed into an RL pruning model, which makes edge-level keep/delete decisions to produce a more compact "high-value subgraph."

### 4) Generation Phase
The pruned subgraph is converted into a structured context and sent to the LLM (via a unified Gateway) to generate the final answer.

### 5) Feedback and Evaluation
While returning the answer, the system records key metrics (tokens, latency, retention rate, F1/F2, retry failures, etc.) for offline analysis and threshold tuning.

---

## III. Four High-Frequency Interview Questions

### 1. Why can it reduce tokens?
It doesn't rely on "clumsy text truncation," but rather on RL to make decisions based on **edge-level information value**. The system recalls the candidate subgraph, and then the model determines which edges are most helpful for the current query's reasoning chain, retaining high-value edges and deleting redundant or noisy ones.

Essentially, it transforms the input from a "neighbor stack" into a "goal-oriented evidence subgraph." Therefore, the token reduction is a result of structural optimization, not simple shortening. This is why the answer quality remains stable after compression.

I track dual metrics:
- Structural side: Subgraph size, edge retention rate.
- Answer side: F1/F2/Exact Match, answer-level accuracy.

A reduction is only considered successful if both sides meet the criteria.

### 2. How do you ensure critical information isn't pruned?
I use a three-layer strategy: "Training Constraints + Inference Protection + Offline Calibration."

#### Training Constraints
The reward function doesn't just optimize the compression rate; it also incorporates structural hits and semantic relevance. F2 (favoring recall) is added to the final reward to prevent the model from over-pruning for the sake of compression.

#### Inference Protection
Online inference uses protection policies:
- Minimum retention ratio (prevents pruning into an empty graph).
- Key node protection (e.g., starting nodes, target type nodes).
- Low-confidence fallback (e.g., rule-based pruning or loosening thresholds).

#### Offline Calibration
Threshold scanning and ablation experiments are performed to find the optimal "Answer Quality vs. Compression Rate" balance point.

Summary: **Fidelity first, compression second.**

### 3. How do you handle stability under high concurrency?
The core approach is "Synchronous Light Orchestration + Asynchronous Heavy Computation."

#### Architecture Decoupling
- The API main thread only performs lightweight orchestration.
- Heavy tasks (vectorization, subgraph construction, batch evaluation) are handled via RabbitMQ + Workers.

#### Stability Strategies
- Redis caches hotspot queries to reduce redundant computation.
- Distributed locks prevent cache breakdown.
- Idempotency keys prevent duplicate execution.
- Request timeouts and queue limits prevent "avalanche" effects.

#### Resource Protection
The RL inference service is deployed independently with concurrency limits and micro-batching. If system load is too high, a fallback strategy prioritizes availability.

### 4. What if the model service fluctuates?
Governance is managed through a unified LLM Gateway, ensuring business logic isn't directly coupled to specific models.

#### Gateway Capabilities
- Multi-model routing (Primary + Standby).
- Timeout control.
- Retry with backoff.
- Circuit breaking and half-open detection.
- Automatic fallback.

#### Error Handling Principles
- Retryable errors (timeouts, rate limits, 5xx) use exponential backoff.
- Non-retryable errors (invalid parameters) fail fast.
- Standby models are automatically triggered if the primary model fails.

Goal: **"Degradable quality, non-interruptible service."**

---

## IV. Will RL Pruning Collapse Under High Traffic?
There is a risk, but it can be mitigated through engineering. The key is treating RL pruning as a "degradable component" rather than a single point of failure.

Mitigation strategies:
1. Independent deployment of RL pruning services, isolated from the API thread.
2. Model process pre-warming to avoid loading weights on every request.
3. GPU concurrency limits + queue caps to control memory peaks.
4. Fallback to rule-based pruning or conservative threshold schemes on failure.
5. Monitoring queue length, P95 latency, OOM, timeout rates, and fallback rates.

This ensures that even if RL is temporarily unavailable, the system continues to function (albeit with lower compression efficiency) without collapsing.

---

## V. Common Follow-up Questions

### Q1: Why not use pure vector RAG?
CTI Q&A relies heavily on multi-hop relationships and entity paths. Pure vector retrieval lacks structural constraints and provides poor interpretability. Graph retrieval + pruning explicitly preserves attack chain evidence.

### Q2: What is your core contribution?
1) Implementation of an end-to-end pipeline; 2) Deployment of online RL pruning; 3) Engineering enhancements in asynchronous tasks, caching, and gateway governance.

### Q3: How do you prove the optimization is effective?
I look at combined metrics across Structural, Answer, and Cost dimensions:
`Retention Rate / Subgraph Size / Tokens / Latency / F1 / Exact Match`.

---

## VI. 30-Second Closing Statement
I have transformed CTI-based RAG from a simple "answering" tool into a "controllable and scalable" system. By utilizing graph retrieval and RL-based edge pruning, I significantly reduced context costs while ensuring stability and availability under high concurrency through asynchronous tasks, caching, and a robust model gateway.
