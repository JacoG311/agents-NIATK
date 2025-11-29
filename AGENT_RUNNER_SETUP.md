# Agent Runner: Multi-Provider LLM Orchestration Setup Guide

A production-ready Python agent framework for cascading LLM requests across multiple providers (Azure OpenAI, Anthropic Claude, local Ollama) with intelligent fallback, cost tracking, and comprehensive error handling.

## Features

✅ **Multi-Provider Routing**  
   - Cascade: Try Azure → Claude → Local (configurable order)  
   - Automatic fallback on failures  
   - Task-specific model preferences  

✅ **Cost Control**  
   - Track API spending per call  
   - Daily budget limits (USD)  
   - Auto-switch to local when limit exceeded  

✅ **Observability**  
   - Structured logging with sensitive field redaction  
   - Per-call metrics: latency, tokens, estimated cost  
   - Request tracing and error tracking  

✅ **Output Validation**  
   - JSON schema validation for task outputs  
   - Configurable per-task validation rules  

✅ **Configuration Management**  
   - YAML/JSON config with environment variable interpolation  
   - Task-specific settings (temperature, max_tokens, output format)  
   - Runtime config validation  

✅ **Error Handling**  
   - Specific exception handling (not broad `except Exception`)  
   - Exponential backoff retry logic  
   - Graceful degradation  

---

## Installation

### 1. Set Up Python Virtual Environment (Recommended)

```bash
cd c:\Users\ONTC\PyCharmMiscProject\agents-NIATK

# Create virtual environment
python -m venv .venv

# Activate (Windows PowerShell)
.venv\Scripts\Activate.ps1

# Or Windows Command Prompt
.venv\Scripts\activate.bat

# Or macOS/Linux
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

Expected packages:
- `openai>=1.0.0` - Azure OpenAI SDK
- `anthropic>=0.7.0` - Anthropic Claude SDK
- `pyyaml>=6.0` - YAML configuration
- `jsonschema>=4.0.0` - JSON schema validation
- `requests>=2.31.0` - HTTP requests
- `python-dotenv>=1.0.0` - Environment variable loading

---

## Configuration

### 1. Set Up Environment Variables

Copy the template:

```bash
cp .env.example .env
```

Edit `.env` with your API keys:
```env
# Required
AZURE_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=sk-...
AZURE_DEPLOYMENT_GPT4_TURBO=gpt-4-turbo
ANTHROPIC_API_KEY=sk-ant-...

# Optional
AZURE_DEPLOYMENT_GPT5=gpt-5            # Future model
LOCAL_LLM_HOST=http://localhost:11434  # Ollama host
LOCAL_LLM_MODEL=llama2                 # Ollama model
DAILY_COST_LIMIT_USD=10.0              # Daily budget
LOG_LEVEL=INFO                         # DEBUG for verbose
AGENT_CONFIG_PATH=agent-config.yaml    # Config file
```

**Load into your shell:**

Windows PowerShell:
```powershell
Get-Content .env | ForEach-Object {
    if ($_ -match '^\s*([^=]+)=(.*)$' -and $matches[1] -notmatch '^#') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
}
```

macOS/Linux:
```bash
set -a
source .env
set +a
```

### 2. Configure agent-config.yaml

The default `agent-config.yaml` is pre-configured for supply chain variance analysis:

**Key sections:**

- **models**: Credentials and endpoints for Azure, Anthropic, Ollama
- **routing**: Provider order (cascade policy), timeouts, retry logic
- **guardrails**: Daily USD limit, cost tracking
- **tasks**: 3 example tasks with output schemas:
  - `variance_assignment` - Assign variances (Azure preferred)
  - `diagnostics_why_processor` - Analyze processor behavior (Claude preferred)
  - `offline_batch` - Batch processing (Ollama only)

To customize:
1. Edit `routing.order` to change provider priority
2. Set `guardrails.daily_usd_limit` for your budget
3. Add task-specific settings (temperature, max_tokens, validation schemas)

---

## Usage

### Basic Example

```python
from agent_runner import ConfigManager, AgentRouter

# Load configuration
config = ConfigManager("agent-config.yaml")

# Create router (initializes all LLM providers)
router = AgentRouter(config)

# Run agent on a single prompt
prompt = "Given variance with Owner=Inbound, Area=GP36, determine error type."
result = router.run_agent(
    prompt=prompt,
    task="variance_assignment"  # Task-specific config
)

# Result includes: model, output, elapsed_ms, tokens_in, tokens_out
print(result)
```

**Sample output:**
```json
{
  "model": "azure:gpt-4-turbo",
  "output": "{\"Owner\": \"Inbound\", \"Area\": \"GP36\", ...}",
  "elapsed_ms": 1250,
  "tokens_in": 45,
  "tokens_out": 120
}
```

### Command Line

Run the built-in example:

```bash
python agent_runner.py
```

This will:
1. Load `agent-config.yaml`
2. Initialize Azure, Anthropic, and Ollama providers
3. Run the variance_assignment task
4. Print results as formatted JSON

### Batch Processing

```python
prompts = [
    "Variance 1: ...",
    "Variance 2: ...",
    "Variance 3: ...",
]

for i, prompt in enumerate(prompts):
    result = router.run_agent(prompt, task="variance_assignment")
    
    # Cost tracker tracks daily spending
    total_cost = router.cost_tracker.daily_total_cost
    print(f"Prompt {i}: {result['model']} | Daily cost: ${total_cost:.4f}")
    
    # If limit exceeded, auto-switches to local Ollama
    if router.cost_tracker.daily_total_cost > router.cost_tracker.daily_limit:
        print("Daily limit exceeded; using local Ollama for remaining prompts")
```

### Task-Specific Routing

Each task can have different model preferences:

```python
# Use Azure for variance (accurate, costs more)
result1 = router.run_agent(
    prompt="Variance analysis...",
    task="variance_assignment"  # Prefers Azure
)

# Use Claude for why-questions (good reasoning)
result2 = router.run_agent(
    prompt="Why did processor JDOE cause 5 variances?",
    task="diagnostics_why_processor"  # Prefers Claude
)

# Use local for batch (no cost)
result3 = router.run_agent(
    prompt="Process 100 variance records",
    task="offline_batch"  # Ollama only
)
```

---

## Architecture

### Components

```
ConfigManager
├─ Loads YAML/JSON config from disk
├─ Validates schema (required keys, structure)
├─ Resolves environment variables (${VAR_NAME})
└─ Provides dotted-key access ("models.azure_openai.api_key")

AgentRouter
├─ Orchestrates LLM provider cascade
├─ Routes requests to preferred provider, falls back on error
├─ Tracks costs and enforces daily limits
├─ Validates outputs against JSON schemas
└─ Implements task-specific configuration

LLMProvider (Base Class)
├─ AzureOpenAIProvider → Uses official Azure SDK
├─ AnthropicProvider → Uses official Anthropic SDK
└─ OllamaProvider → HTTP POST to /api/generate

CostTracker
├─ Estimates cost per call (tokens × pricing rates)
├─ Tracks daily spending by provider
├─ Enforces daily USD limit
└─ Auto-resets counter on new calendar day
```

### Request Flow

```
router.run_agent(prompt, task="variance_assignment")
    ↓
[ConfigManager] Load task-specific config (model, schema, temperature)
    ↓
[CostTracker] Check daily limit, reset if new day
    ↓
[AgentRouter] Determine provider order based on routing.order
    ↓
For each provider in order:
    ├─ [Provider.call()] Execute with timeout and error handling
    ├─ [CostTracker] Log tokens and estimate cost
    ├─ [Validation] Check output against JSON schema
    └─ Return success → break; or log error → continue to next
    ↓
If all fail: Return error dict with details
    ↓
Return {model, output, elapsed_ms, tokens_in, tokens_out, error?}
```

---

## Configuration Reference

### agent-config.yaml Structure

```yaml
version: "1"                               # Schema version

agent:
  name: "Variance Analysis Agent"
  description: "Multi-provider LLM orchestrator"
  instructions_path: "./instructions.md"   # System prompt file

models:
  azure_openai:
    provider: "azure-openai"
    endpoint: "${AZURE_ENDPOINT}"          # Resolved from .env
    api_key: "${AZURE_OPENAI_API_KEY}"     # Resolved from .env
    api_version: "2024-10-01"
    deployments:
      - name: "gpt-4-turbo"
        deployment_id: "${AZURE_DEPLOYMENT_GPT4_TURBO}"
      - name: "gpt-5"
        deployment_id: "${AZURE_DEPLOYMENT_GPT5}"
  
  anthropic:
    provider: "anthropic"
    api_key: "${ANTHROPIC_API_KEY}"
    model: "claude-3-5-sonnet-20241022"
  
  local:
    provider: "ollama"
    host: "${LOCAL_LLM_HOST:-http://localhost:11434}"
    model: "${LOCAL_LLM_MODEL:-llama2}"

routing:
  policy: "cascade"                         # Try providers in order
  order:
    - "azure_openai:gpt-4-turbo"           # Primary
    - "anthropic:claude-3.5-sonnet"        # Secondary
    - "local:llama2"                       # Fallback
  
  timeouts:
    azure_openai: 20                       # seconds
    anthropic: 25
    local: 60
  
  retry:
    attempts: 2                            # Retry count
    backoff: "exponential"                 # fixed or exponential
    initial_delay_ms: 500
    max_delay_ms: 3000

guardrails:
  daily_usd_limit: "${DAILY_COST_LIMIT_USD:-10.0}"
  cost_tracking_enabled: true
  on_exceed: "switch_to_local"            # switch_to_local or error

tasks:
  variance_assignment:
    description: "Categorize supply chain variance"
    preferred_model: "azure_openai:gpt-4-turbo"
    allow_fallback: true
    temperature: 0.2                      # More deterministic
    max_tokens: 4000
    output_schema:
      type: "object"
      required: ["Owner", "Area", "ProcessWeek"]
      properties:
        Owner: { type: "string" }
        Area: { type: "string" }
        ProcessWeek: { type: "string" }
        # ... more fields
  
  diagnostics_why_processor:
    description: "Analyze processor behavior"
    preferred_model: "anthropic:claude-3.5-sonnet"
    allow_fallback: true
    temperature: 0.7                      # More creative
    max_tokens: 6000
    output_schema:
      type: "string"                      # Markdown output
  
  offline_batch:
    description: "Batch processing (local only)"
    preferred_model: "local:llama2"
    allow_fallback: false                 # Don't fail over
    max_tokens: 8000

secrets:
  env_required:
    - "AZURE_ENDPOINT"
    - "AZURE_OPENAI_API_KEY"
    - "ANTHROPIC_API_KEY"
  env_optional:
    - "AZURE_DEPLOYMENT_GPT5"
    - "LOCAL_LLM_HOST"
    - "DAILY_COST_LIMIT_USD"

logging:
  level: "${LOG_LEVEL:-INFO}"             # DEBUG for verbose
  format: "json"
  redact_fields: ["api_key", "endpoint", "password"]
```

---

## Logging & Debugging

All operations are logged to stdout with structured format:

```
2025-11-26 14:35:22,123 - agent_runner - INFO - ConfigManager: Loaded config from agent-config.yaml
2025-11-26 14:35:22,234 - agent_runner - INFO - AgentRouter: Azure OpenAI client initialized
2025-11-26 14:35:22,456 - agent_runner - INFO - AgentRouter: Calling azure_openai:gpt-4-turbo (attempt 1/2)
2025-11-26 14:35:23,789 - agent_runner - INFO - CostTracker: Call cost $0.001234 | Daily total: $0.0123 / $10.00
2025-11-26 14:35:23,890 - agent_runner - INFO - AgentRouter: Success in 1434ms (45 tokens in, 120 out)
```

**Enable debug logging:**

```bash
export LOG_LEVEL=DEBUG
python agent_runner.py
```

Debug output includes:
- Full request/response payloads
- Provider selection logic
- Cost estimation details
- Validation results

---

## Cost Estimation & Tracking

Costs are estimated based on token counts and published pricing:

| Model | Input | Output |
|-------|-------|--------|
| gpt-4-turbo | $0.01/1K | $0.03/1K |
| gpt-5 (TBA) | $0.03/1K | $0.06/1K |
| claude-3.5 | $0.003/1K | $0.015/1K |
| llama2 (local) | $0.00 | $0.00 |

The `CostTracker` class:
- Estimates cost per call using official SDKs' token counts
- Tracks daily total by provider
- Automatically resets counter on new calendar day (UTC)
- When daily limit exceeded, routes remaining requests to local Ollama (zero cost)

Update pricing in `CostTracker.estimate_cost()` if rates change.

---

## Error Handling & Fallback

The router implements intelligent cascading:

1. **Transient Errors** (timeout, connection reset)
   - Retry with exponential backoff (500ms → 3000ms)
   - Log warning, attempt next provider

2. **Provider Unavailable** (bad credentials, no API key)
   - Skip provider, log error
   - Move to next in cascade

3. **All Providers Fail**
   - Return error response with details
   - Include full error messages for debugging

4. **Daily Budget Hit**
   - Auto-switch to local Ollama (zero cost)
   - Log warning
   - Continue with local provider

**Example error response:**

```json
{
  "error": "All providers failed. Errors: {\"azure_openai:gpt-4-turbo\": \"Connection timeout\", \"anthropic:claude-3.5\": \"API rate limit exceeded\", \"local:llama2\": \"Connection refused\"}",
  "model": "none",
  "elapsed_ms": 5000
}
```

---

## Troubleshooting

### "Config file not found"
```bash
# Ensure agent-config.yaml exists in current directory
ls -la agent-config.yaml

# Or set AGENT_CONFIG_PATH environment variable
export AGENT_CONFIG_PATH=/path/to/config.yaml
python agent_runner.py
```

### "Azure OpenAI client not initialized"
```bash
# Verify environment variables
echo $AZURE_ENDPOINT
echo $AZURE_OPENAI_API_KEY
echo $AZURE_DEPLOYMENT_GPT4_TURBO

# Enable debug logging
export LOG_LEVEL=DEBUG
python agent_runner.py

# Check Azure portal for valid resource, endpoint, deployment
```

### "All providers failed"
- Check internet connectivity: `ping google.com`
- Verify API keys and credentials in `.env`
- Check provider status dashboards:
  - Azure Portal: https://portal.azure.com
  - Anthropic Console: https://console.anthropic.com
- Enable DEBUG logging: `LOG_LEVEL=DEBUG`

### "Connection to Ollama failed"
- Start Ollama service:
  ```bash
  # Download: https://ollama.ai
  ollama serve
  ```
- Verify model is available:
  ```bash
  ollama list  # Should show llama2 or your configured model
  ```
- Check LOCAL_LLM_HOST and LOCAL_LLM_MODEL in `.env`

### Slow responses
- Increase timeouts in `agent-config.yaml`:
  ```yaml
  routing:
    timeouts:
      azure_openai: 30    # was 20
      anthropic: 35       # was 25
  ```
- Check provider status (may be experiencing load)
- Use `LOG_LEVEL=DEBUG` to see actual latencies

### High costs
- Review daily cost total in logs
- Check token counts for large prompts
- Consider using task-specific settings with lower `max_tokens`
- Set lower `daily_usd_limit` to trigger local fallback sooner

---

## Testing

### Run Built-in Example

```bash
python agent_runner.py
```

Expected output:
```
2025-11-26 14:35:22,123 - agent_runner - INFO - ConfigManager: Loaded config from agent-config.yaml
...
Result:
{
  "model": "azure:gpt-4-turbo",
  "output": "...",
  "elapsed_ms": 1250,
  "tokens_in": 45,
  "tokens_out": 120
}
```

### Test Single Task

```python
from agent_runner import ConfigManager, AgentRouter

config = ConfigManager()
router = AgentRouter(config)

result = router.run_agent(
    "Your test prompt here",
    task="variance_assignment"
)
print(result)
```

### Test Fallback Logic

```python
# Temporarily disable Azure to test fallback
import os
os.environ['AZURE_OPENAI_API_KEY'] = 'invalid'

# This should cascade to Claude, then local
result = router.run_agent("Test prompt")
print(result['model'])  # Should be anthropic or local
```

---

## Advanced Configuration

### Custom Task with Schema Validation

Add to `agent-config.yaml`:

```yaml
tasks:
  my_custom_task:
    description: "Custom validation example"
    preferred_model: "anthropic:claude-3.5-sonnet"
    allow_fallback: true
    temperature: 0.5
    max_tokens: 6000
    output_schema:
      type: "object"
      required: ["status", "details", "confidence"]
      properties:
        status:
          type: "string"
          enum: ["success", "warning", "error"]
        details:
          type: "string"
        confidence:
          type: "number"
          minimum: 0
          maximum: 1
```

Use it:
```python
result = router.run_agent("Your prompt", task="my_custom_task")
# Output automatically validated against schema
```

### Custom Provider Setup

To add a new provider (e.g., Groq):

1. Create `GroqProvider` class extending `LLMProvider`:
   ```python
   class GroqProvider(LLMProvider):
       def call(self, prompt, system_prompt="", temperature=0.7, max_tokens=2048):
           # Implement HTTP call to Groq API
           ...
   ```

2. Register in `AgentRouter.__init__()`:
   ```python
   self.groq = GroqProvider(config)
   ```

3. Add to `agent-config.yaml`:
   ```yaml
   models:
     groq:
       provider: "groq"
       api_key: "${GROQ_API_KEY}"
       model: "mixtral-8x7b-32768"
   ```

4. Add to routing:
   ```yaml
   routing:
     order:
       - "azure_openai:gpt-4-turbo"
       - "anthropic:claude-3.5"
       - "groq:mixtral"
       - "local:llama2"
   ```

---

## Requirements

- **Python 3.10+**
- **Dependencies** (see `requirements.txt`):
  - openai >= 1.0.0
  - anthropic >= 0.7.0
  - pyyaml >= 6.0
  - jsonschema >= 4.0.0
  - requests >= 2.31.0
  - python-dotenv >= 1.0.0

---

## Performance Tips

1. **Set task-specific temperatures:**
   - Deterministic tasks (variance categorization): temperature=0.2
   - Creative tasks (brainstorming): temperature=0.8

2. **Limit max_tokens:**
   - Reduce for faster responses and lower costs
   - Default 4000 is generous; most tasks need < 1000

3. **Use local for high-volume:**
   - Ollama has minimal latency (no network)
   - Useful for batch processing (60s timeout vs 20s for cloud)

4. **Monitor daily costs:**
   - Review logs: `grep "CostTracker" agent_runner.log`
   - Adjust `daily_usd_limit` if budget exceeded

---

## Next Steps

1. **Install dependencies:** `pip install -r requirements.txt`
2. **Configure credentials:** Copy `.env.example` → `.env`, fill in API keys
3. **Test:** `python agent_runner.py`
4. **Customize:** Edit `agent-config.yaml` for your use case
5. **Integrate:** Import `AgentRouter` in your own code

---

## Support & Contribution

For issues:
1. Enable `LOG_LEVEL=DEBUG` and review full logs
2. Verify `.env` and `agent-config.yaml` are correct
3. Check provider status dashboards
4. See Troubleshooting section

To improve:
- Update `agent_runner.py` for logic enhancements
- Modify `agent-config.yaml` for defaults
- Update `requirements.txt` for new dependencies
- Add to `.env.example` for new environment variables
- Update this guide for documentation

