# LLM Gateway & Multi-Provider CLI Proxy Plan

> **Status:** ❌ DISCARDED (Concept replaced by direct API usage due to proxy noise)

## 1. Background & Motivation
Currently, the Biometric AI Platform relies on a direct connection to Google's Generative AI API using an API Key. While effective, this creates a dependency on a single provider and consumes API quota/tokens. 

The goal is to implement a **Universal LLM Gateway** that makes the project provider-agnostic (supporting Gemini, OpenAI, Anthropic, etc.) and introduces a "Power User" mode: a **CLI Multi-Provider Proxy**. This proxy will leverage local CLI tools (`gemini-cli`, `claude-code`, etc.) as zero-cost inference engines with automatic failover.

## 2. Architectural Vision: The "Dual-Mode" Strategy
The system will dynamically decide its "brain" based on environment configuration:
- **Mode A (Standard/API):** Use official SDKs (LangChain) with API Keys. High reliability, supports streaming, easiest for new users.
- **Mode B (Power User/CLI Proxy):** Use local system processes (`subprocess`) to call authenticated CLIs. Zero token cost, high resilience via multi-provider failover.

## 3. Core Components

### 3.1. Model Factory (`api/src/utils/model_factory.py`)
A centralized factory that returns a LangChain-compatible `BaseChatModel`. It reads `LLM_PROVIDER` from `.env`.
- **Gemini:** `ChatGoogleGenerativeAI`
- **OpenAI:** `ChatOpenAI`
- **CLI Proxy:** Our custom `CLIProxyChatModel`

### 3.2. CLI Proxy Wrapper (`api/src/utils/cli_proxy.py`)
A custom LangChain class that implements the "trap":
- **Execution Engine:** Manages `subprocess.run` calls to various CLIs.
- **Provider Chain:** Orchestrates a prioritized list (e.g., `gemini` -> `claude` -> `codex`).
- **Sanitization:** Regex-based cleaning of ANSI colors, banners, and CLI noise.
- **Failover Logic:** If a CLI returns a non-zero exit code or hits a rate limit, the proxy immediately attempts the next provider in the chain.

### 3.3. Transparency Layer
The main agent logic in `graph.py` remains untouched. It continues to call `llm.invoke()`, unaware of whether the response came from a cloud API or a local terminal process.

## 4. Proposed Implementation Phases

### Phase 1: Model Factory & API Agnosticism
- Implement `model_factory.py`.
- Update `graph.py` to use the factory.
- Add configuration variables to `.env` (e.g., `LLM_PROVIDER`, `OPENAI_API_KEY`).

### Phase 2: CLI Proxy Prototype
- Create `cli_proxy.py` with basic `gemini-cli` support.
- Implement output cleaning for "non-interactive" mode.
- Benchmark latency vs. direct API calls on Raspberry Pi.

### Phase 3: Multi-CLI Failover
- Extend the proxy to support `claude-code` and `codex/gh`.
- Implement the sequential failover logic.
- Add "Function Calling Simulation": Instruct the CLI to output XML/JSON that the proxy translates back into standard LangChain `ToolCalls`.

### Phase 4: Observability & FinOps
- Update `finops.py` to log "CLI Proxy" as a provider.
- Track "Saved Costs" based on token estimation (even if the cost is $0).

## 5. Security & Stability Considerations
- **Non-Interactive Mode:** Ensure all CLI calls use `--quiet` or equivalent flags to prevent the process from hanging.
- **Concurrency:** Use thread locking if multiple users access the CLI proxy simultaneously to prevent session file corruption.
- **Identity:** Ensure the `X-User-ID` is passed correctly to the prompt so the CLI has the right context, even without native session management.

## 6. Future-Proofing
This architecture allows the project to survive even if a specific LLM provider changes its pricing or free-tier policies. By relying on standardized protocols (LangChain) and ubiquitous interfaces (CLIs), the Biometric AI Platform becomes truly resilient.
