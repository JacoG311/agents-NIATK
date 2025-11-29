"""
Agent Runner: Multi-provider LLM orchestration with cascading fallback and cost control.

Supports Azure OpenAI, Anthropic Claude, and local Ollama models with:
- Dynamic config loading (YAML/JSON)
- Task-specific routing and output validation
- Structured logging and observability
- Cost tracking and daily limits
- Comprehensive error handling with retries
"""

import json
import logging
import os
import time
from typing import Dict, Any, Optional, Literal
from pathlib import Path

import yaml
def _run_example_sync():
    """Run a synchronous example (keeps backward compatibility)."""
    # Load config
    config = ConfigManager(os.getenv("AGENT_CONFIG_PATH", "agent-config.yaml"))
    router = AgentRouter(config)

    sample_prompt = (
        "Given a variance row with Audit_Date=2025-11-28 14:10, "
        "Owner=Inbound, Audit_Location=GP36, SKU=A8369881-001, "
        "TM_ID=JDOE123, determine Owner/Area/Processor/Error/Pattern "
        "and emit JSON."
    )

    result = router.run_agent(prompt=sample_prompt, task="variance_assignment")
    print("\n" + "=" * 60)
    print("Agent Result:")
    print("=" * 60)
    print(json.dumps(result, indent=2))


async def async_main():
    """Async entrypoint: runs sync router in thread to preserve provider APIs.

    This is a simple async shim to demonstrate parallel usage while keeping
    the core router synchronous. Future work: fully async provider implementations
    that expose `call_async` and an async router.
    """
    config = ConfigManager(os.getenv("AGENT_CONFIG_PATH", "agent-config.yaml"))
    router = AgentRouter(config)

    prompts = [
        "Summarize inventory variance for batch A.",
        "Analyze root cause for variance row X.",
        "Generate assignment for variance event Y."
    ]

    # Run multiple agents in parallel using threads to call the synchronous router
    tasks = [asyncio.to_thread(router.run_agent, prompt, "variance_assignment") for prompt in prompts]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for i, r in enumerate(results, 1):
        print(f"\n--- Result {i} ---")
        if isinstance(r, Exception):
            print(f"Error: {r}")
        else:
            print(json.dumps(r, indent=2))


def main():
    """Compatibility main: prefer async_main when run under asyncio-aware environments."""
    try:
        # Prefer async main if caller wants to integrate with asyncio
        if os.getenv("AGENT_RUNNER_ASYNC", "0") == "1":
            asyncio.run(async_main())
        else:
            _run_example_sync()
    except ConfigError as e:
        logger.error(f"Configuration error: {e}")
        print(f"Error: {e}", file=__import__('sys').stderr)
        exit(1)
    except CostLimitError as e:
        logger.error(f"Cost limit error: {e}")
        print(f"Error: {e}", file=__import__('sys').stderr)
        exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"Error: {e}", file=__import__('sys').stderr)
        exit(1)


if __name__ == "__main__":
    main()
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        
        try:
            with open(self.config_path, "r") as f:
                if self.config_path.suffix == ".yaml":
                    config = yaml.safe_load(f)
                elif self.config_path.suffix == ".json":
                    config = json.load(f)
                else:
                    raise ValueError(f"Unsupported format: {self.config_path.suffix}")
            logger.info(f"Loaded config from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            raise
    
    def _resolve_env_vars(self):
        """Replace ${VAR_NAME} with environment variable values."""
        def resolve(obj):
            if isinstance(obj, dict):
                return {k: resolve(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [resolve(v) for v in obj]
            elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
                var_name = obj[2:-1]
                value = os.getenv(var_name)
                if value is None:
                    logger.warning(f"Env var not set: {var_name}, using placeholder")
                    return obj
                return value
            return obj
        
        self.config = resolve(self.config)
    
    def _validate_config(self):
        """Validate config structure (basic checks)."""
        required_top_level = ["version", "agent", "models", "routing", "tasks"]
        for key in required_top_level:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")
        
        required_models = self.config.get("routing", {}).get("order", [])
        for model_ref in required_models:
            provider_name = model_ref.split(":")[0]
            if provider_name not in self.config.get("models", {}):
                logger.warning(f"Model provider not found: {provider_name}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get config value by dotted path (e.g., 'models.azure_openai.api_key')."""
        keys = key.split(".")
        value = self.config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

# ============================================================================
# Cost Tracking
# ============================================================================

class CostTracker:
    """Track API call costs against daily limits."""
    
    def __init__(self, daily_limit_usd: Optional[float] = None):
        self.daily_limit_usd = daily_limit_usd
        self.daily_spent_usd = 0.0
        self.last_reset_date = time.time()
    
    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Estimate cost for a model call (simplified pricing)."""
        # Placeholder pricing (update with actual rates)
        pricing = {
            "gpt-4-turbo": {"input": 0.01 / 1000, "output": 0.03 / 1000},
            "gpt-5": {"input": 0.03 / 1000, "output": 0.06 / 1000},
            "claude-3.5": {"input": 0.003 / 1000, "output": 0.015 / 1000},
            "llama3": {"input": 0.0, "output": 0.0},  # local, no cost
        }
        
        rates = pricing.get(model, {"input": 0.0, "output": 0.0})
        cost = (tokens_in * rates["input"]) + (tokens_out * rates["output"])
        return cost
    
    def should_switch_to_fallback(self) -> bool:
        """Check if daily limit exceeded."""
        if self.daily_limit_usd is None:
            return False
        return self.daily_spent_usd >= self.daily_limit_usd
    
    def record_call(self, model: str, tokens_in: int, tokens_out: int):
        """Record a call and update spending."""
        cost = self.estimate_cost(model, tokens_in, tokens_out)
        self.daily_spent_usd += cost
        logger.info(f"Cost: {cost:.6f} USD for {model} | Daily total: {self.daily_spent_usd:.4f} USD")
    
    def reset_if_new_day(self):
        """Reset daily counter if new calendar day."""
        import datetime
        now = datetime.datetime.utcnow()
        last_reset = datetime.datetime.utcfromtimestamp(self.last_reset_date)
        if now.date() != last_reset.date():
            self.daily_spent_usd = 0.0
            self.last_reset_date = time.time()
            logger.info("Daily cost counter reset")

# ============================================================================
# LLM Clients
# ============================================================================

class LLMProvider:
    """Base class for LLM providers."""
    
    def call(self, prompt: str, system_prompt: Optional[str] = None, 
             temperature: float = 0.2, max_tokens: int = 4000) -> Dict[str, Any]:
        raise NotImplementedError

class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI client wrapper."""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        azure_cfg = config.get("models.azure_openai", {})
        
        endpoint = azure_cfg.get("endpoint")
        api_key = azure_cfg.get("api_key")
        api_version = azure_cfg.get("api_version", "2025-01-01-preview")
        
        if not endpoint or not api_key:
            logger.warning("Azure OpenAI config incomplete, provider disabled")
            self.client = None
            return
        
        try:
            self.client = AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version
            )
            logger.info("Azure OpenAI client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Azure OpenAI: {e}")
            self.client = None
    
    def call(self, prompt: str, system_prompt: Optional[str] = None,
             temperature: float = 0.2, max_tokens: int = 4000) -> Dict[str, Any]:
        """Call Azure OpenAI."""
        if not self.client:
            raise RuntimeError("Azure OpenAI client not initialized")
        
        azure_cfg = self.config.get("models.azure_openai", {})
        deployment = azure_cfg.get("deployments", [{}])[0].get("id")
        
        if not deployment:
            raise ValueError("No Azure deployment configured")
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        start = time.time()
        try:
            response = self.client.chat.completions.create(
                model=deployment,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            elapsed_ms = int((time.time() - start) * 1000)
            output = response.choices[0].message.content
            
            return {
                "model": "azure:gpt-4-turbo",
                "output": output,
                "elapsed_ms": elapsed_ms,
                "tokens_in": response.usage.prompt_tokens,
                "tokens_out": response.usage.completion_tokens,
            }
        except AzureConnectionError as e:
            logger.error(f"Azure connection error: {e}")
            raise
        except AzureAPIError as e:
            logger.error(f"Azure API error: {e}")
            raise

class AnthropicProvider(LLMProvider):
    """Anthropic Claude client wrapper."""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        anthropic_cfg = config.get("models.anthropic", {})
        api_key = anthropic_cfg.get("api_key")
        
        if not api_key:
            logger.warning("Anthropic config incomplete, provider disabled")
            self.client = None
            return
        
        try:
            self.client = Anthropic(api_key=api_key)
            logger.info("Anthropic client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic: {e}")
            self.client = None
    
    def call(self, prompt: str, system_prompt: Optional[str] = None,
             temperature: float = 0.2, max_tokens: int = 8000) -> Dict[str, Any]:
        """Call Anthropic Claude."""
        if not self.client:
            raise RuntimeError("Anthropic client not initialized")
        
        start = time.time()
        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt or "",
                messages=[{"role": "user", "content": prompt}]
            )
            elapsed_ms = int((time.time() - start) * 1000)
            output = response.content[0].text if response.content else ""
            
            return {
                "model": "anthropic:claude-3.5",
                "output": output,
                "elapsed_ms": elapsed_ms,
                "tokens_in": response.usage.input_tokens,
                "tokens_out": response.usage.output_tokens,
            }
        except AnthropicConnectionError as e:
            logger.error(f"Anthropic connection error: {e}")
            raise
        except AnthropicAPIError as e:
            logger.error(f"Anthropic API error: {e}")
            raise

class OllamaProvider(LLMProvider):
    """Ollama local LLM client wrapper."""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        local_cfg = config.get("models.local", {})
        self.host = local_cfg.get("host", "http://localhost:11434")
        self.model = local_cfg.get("model", "llama2")
    
    def call(self, prompt: str, system_prompt: Optional[str] = None,
             temperature: float = 0.2, max_tokens: int = 4096) -> Dict[str, Any]:
        """Call Ollama local model."""
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        start = time.time()
        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens}
                },
                timeout=60
            )
            response.raise_for_status()
            elapsed_ms = int((time.time() - start) * 1000)
            
            data = response.json()
            output = data.get("response", "")
            tokens_out = len(output.split())  # rough estimate
            
            return {
                "model": f"local:{self.model}",
                "output": output,
                "elapsed_ms": elapsed_ms,
                "tokens_in": len(full_prompt.split()),
                "tokens_out": tokens_out,
            }
        except requests.exceptions.Timeout:
            logger.error(f"Ollama timeout after {60}s")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Ollama request error: {e}")
            raise

# ============================================================================
# Agent Router
# ============================================================================

class AgentRouter:
    """Route prompts to LLM providers based on config policy."""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.cost_tracker = CostTracker(
            daily_limit_usd=self._parse_cost_limit(
                config.get("guardrails.daily_usd_limit")
            )
        )
        
        # Initialize providers
        self.providers = {
            "azure_openai": AzureOpenAIProvider(config),
            "anthropic": AnthropicProvider(config),
            "local": OllamaProvider(config),
        }
        
        self.routing_policy = config.get("routing.policy", "cascade")
        self.routing_order = config.get("routing.order", [])
        self.timeouts = config.get("routing.timeouts", {})
        self.retry_config = config.get("routing.retry", {})
    
    def _parse_cost_limit(self, limit_str: Optional[str]) -> Optional[float]:
        """Parse cost limit from string or env var."""
        if not limit_str:
            return None
        try:
            return float(limit_str)
        except ValueError:
            logger.warning(f"Invalid cost limit: {limit_str}")
            return None
    
    def run_agent(
        self,
        prompt: str,
        task: str = "variance_assignment",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None
    ) -> Dict[str, Any]:
        """Route prompt to appropriate LLM provider with fallback and cost control."""
        
        self.cost_tracker.reset_if_new_day()
        
        # Check cost limit
        if self.cost_tracker.should_switch_to_fallback():
            logger.warning("Daily cost limit reached, switching to local fallback")
            task_config = self.config.get(f"tasks.{task}", {})
            task_config["preferred_model"] = "local"
        
        # Load task config
        task_config = self.config.get(f"tasks.{task}", {})
        if not task_config:
            logger.warning(f"Unknown task: {task}, using defaults")
            task_config = {}
        
        temperature = temperature or task_config.get("temperature", 0.2)
        max_tokens = max_tokens or task_config.get("max_tokens", 4000)
        
        # Load system prompt from agent instructions
        system_prompt = self._load_system_prompt()
        
        # Determine model routing order
        preferred_model = task_config.get("preferred_model")
        allow_fallback = task_config.get("allow_fallback", True)
        routing_order = [preferred_model] if preferred_model else self.routing_order
        
        if allow_fallback and preferred_model not in routing_order:
            routing_order.extend(self.routing_order)
        
        # Try each provider in cascade
        errors = {}
        for model_ref in routing_order:
            try:
                provider_name, model_name = self._parse_model_ref(model_ref)
                provider = self.providers.get(provider_name)
                
                if not provider or not provider.client:
                    logger.debug(f"Provider {provider_name} not available, skipping")
                    continue
                
                logger.info(f"Calling {provider_name} ({model_name})")
                
                result = provider.call(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                
                # Track cost
                self.cost_tracker.record_call(
                    model_name,
                    result.get("tokens_in", 0),
                    result.get("tokens_out", 0)
                )
                
                # Validate output schema if defined
                output_schema = task_config.get("output_schema")
                if output_schema:
                    self._validate_output(result["output"], output_schema)
                
                logger.info(f"Success: {provider_name} returned in {result['elapsed_ms']}ms")
                return result
            
            except Exception as e:
                logger.warning(f"Provider {model_ref} failed: {e}")
                errors[model_ref] = str(e)
                continue
        
        # All providers failed
        error_msg = f"All providers failed. Errors: {errors}"
        logger.error(error_msg)
        return {"error": error_msg, "model": "none"}
    
    def _parse_model_ref(self, model_ref: str) -> tuple:
        """Parse model reference 'provider:model' into tuple."""
        parts = model_ref.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid model reference: {model_ref}")
        return parts[0], parts[1]
    
    def _load_system_prompt(self) -> str:
        """Load system prompt from instructions file."""
        instructions_path = self.config.get("agent.instructions_path")
        if not instructions_path:
            return "You are a helpful assistant."
        
        try:
            path = Path(instructions_path)
            if path.exists():
                with open(path, "r") as f:
                    return f.read()
        except Exception as e:
            logger.warning(f"Failed to load instructions: {e}")
        
        return "You are a helpful assistant."
    
    def _validate_output(self, output: str, schema: Dict[str, Any]):
        """Validate output against JSON schema."""
        try:
            data = json.loads(output)
            jsonschema.validate(data, schema)
            logger.debug("Output schema validation passed")
        except json.JSONDecodeError:
            logger.warning("Output is not valid JSON, skipping schema validation")
        except jsonschema.ValidationError as e:
            logger.warning(f"Output schema validation failed: {e.message}")

# ============================================================================
# Main Entry Point
# ============================================================================

def main():
    """Example usage."""
    
    # Load config
    config = ConfigManager(os.getenv("AGENT_CONFIG_PATH", "agent-config.yaml"))
    
    # Create router
    router = AgentRouter(config)
    
    # Example prompts
    sample_prompt = (
        "Given a variance row with Audit_Date=2025-11-07 14:10, "
        "Owner=Inbound, Audit_Location=GP36, SKU=A8369881-001, "
        "TM_ID=JDOE123, determine Owner/Area/Processor/Error/Pattern "
        "and emit JSON."
    )
    
    # Run agent
    result = router.run_agent(
        prompt=sample_prompt,
        task="variance_assignment"
    )
    
    print("\n" + "=" * 60)
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    main()
