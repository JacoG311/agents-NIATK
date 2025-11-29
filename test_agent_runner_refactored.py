"""
Comprehensive test suite for agent_runner_refactored.py

Tests cover:
- Configuration management and validation
- Cost tracking with budget enforcement
- Error handling and exception hierarchy
- Provider initialization and fallback
- Token counting accuracy
- Output schema validation
- Retry logic with exponential backoff
"""

import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open
from datetime import datetime, timedelta

import yaml

# Import components under test
from agent_runner_refactored import (
    ConfigManager,
    ConfigError,
    AuthError,
    NetworkError,
    ValidationError,
    CostLimitError,
    CostTracker,
    TokenCounter,
    AzureOpenAIProvider,
    AnthropicProvider,
    OllamaProvider,
    AgentRouter,
    retry_with_backoff,
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_config_yaml():
    """Create a temporary valid config file."""
    config = {
        "version": "1.0.0",
        "agent": {
            "name": "test_agent",
            "instructions_path": None,
            "temperature": 0.2,
            "max_tokens": 4000
        },
        "models": {
            "azure_openai": {
                "endpoint": "${AZURE_ENDPOINT}",
                "api_key": "${AZURE_OPENAI_API_KEY}",
                "api_version": "2024-10-01",
                "deployments": [{"id": "gpt-4-turbo"}]
            },
            "anthropic": {
                "api_key": "${ANTHROPIC_API_KEY}"
            },
            "local": {
                "host": "http://localhost:11434",
                "model": "llama2"
            }
        },
        "routing": {
            "policy": "cascade",
            "order": ["azure_openai:gpt-4-turbo", "anthropic:claude", "local:llama2"],
            "timeouts": {
                "azure_openai": 20,
                "anthropic": 25,
                "local": 60
            },
            "retry": {
                "max_retries": 2,
                "initial_delay_ms": 500,
                "max_delay_ms": 3000
            }
        },
        "guardrails": {
            "daily_usd_limit": "10.0",
            "cost_tracking_enabled": True
        },
        "tasks": {
            "variance_assignment": {
                "preferred_model": "azure_openai:gpt-4-turbo",
                "allow_fallback": True,
                "temperature": 0.1,
                "max_tokens": 2000,
                "validation_mode": "warn",
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "owner": {"type": "string"},
                        "processor": {"type": "string"}
                    },
                    "required": ["owner", "processor"]
                }
            }
        },
        "secrets": {
            "required": ["AZURE_ENDPOINT", "AZURE_OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
        },
        "logging": {
            "level": "INFO",
            "format": "json"
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(config, f)
        temp_file = f.name
    
    yield temp_file
    
    # Cleanup
    Path(temp_file).unlink()

@pytest.fixture
def env_setup(monkeypatch):
    """Set up required environment variables."""
    monkeypatch.setenv("AZURE_ENDPOINT", "https://test.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-azure-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")

@pytest.fixture
def cost_tracker():
    """Create a cost tracker instance."""
    return CostTracker(daily_limit_usd=10.0)

@pytest.fixture
def token_counter():
    """Create a token counter instance."""
    return TokenCounter()

# ============================================================================
# ConfigManager Tests
# ============================================================================

class TestConfigManager:
    """Test configuration loading, validation, and environment resolution."""
    
    def test_load_config_success(self, temp_config_yaml, env_setup):
        """Test successful config loading from YAML."""
        config = ConfigManager(temp_config_yaml)
        
        assert config.config is not None
        assert config.config.get("version") == "1.0.0"
        assert config.config.get("agent", {}).get("name") == "test_agent"
    
    def test_config_file_not_found(self):
        """Test error when config file doesn't exist."""
        with pytest.raises(ConfigError, match="Config file not found"):
            ConfigManager("/nonexistent/path/config.yaml")
    
    def test_missing_required_config_keys(self):
        """Test error when required config keys are missing."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({"version": "1.0.0"}, f)
            temp_file = f.name
        
        try:
            with pytest.raises(ConfigError, match="Missing required config key"):
                ConfigManager(temp_file)
        finally:
            Path(temp_file).unlink()
    
    def test_missing_required_env_vars(self, temp_config_yaml, monkeypatch):
        """Test error when required env vars are missing."""
        monkeypatch.delenv("AZURE_ENDPOINT", raising=False)
        monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        
        with pytest.raises(ConfigError, match="Missing required environment variables"):
            ConfigManager(temp_config_yaml)
    
    def test_env_var_resolution(self, temp_config_yaml, env_setup):
        """Test ${VAR_NAME} resolution in config."""
        config = ConfigManager(temp_config_yaml)
        
        azure_key = config.get("models.azure_openai.api_key")
        assert azure_key == "test-azure-key"
        
        anthropic_key = config.get("models.anthropic.api_key")
        assert anthropic_key == "test-anthropic-key"
    
    def test_dotted_path_access(self, temp_config_yaml, env_setup):
        """Test get() method with dotted paths."""
        config = ConfigManager(temp_config_yaml)
        
        endpoint = config.get("models.azure_openai.endpoint")
        assert "openai.azure.com" in endpoint
        
        timeout = config.get("routing.timeouts.azure_openai")
        assert timeout == 20
    
    def test_get_with_default(self, temp_config_yaml, env_setup):
        """Test get() with default fallback."""
        config = ConfigManager(temp_config_yaml)
        
        nonexistent = config.get("nonexistent.path", default="fallback")
        assert nonexistent == "fallback"

# ============================================================================
# CostTracker Tests
# ============================================================================

class TestCostTracker:
    """Test cost tracking and budget enforcement."""
    
    def test_cost_estimation(self, cost_tracker):
        """Test cost estimation for different models."""
        cost_gpt4 = cost_tracker.estimate_cost("gpt-4-turbo", 1000, 500)
        assert cost_gpt4 > 0
        
        cost_claude = cost_tracker.estimate_cost("claude-3.5-sonnet", 1000, 500)
        assert cost_claude > 0
        
        cost_local = cost_tracker.estimate_cost("llama3", 1000, 500)
        assert cost_local == 0.0  # Local model should be free
    
    def test_budget_check_within_limit(self, cost_tracker):
        """Test that budget check passes when within limit."""
        cost_tracker.check_budget_before_call(5.0)  # Should not raise
        cost_tracker.record_call("gpt-4-turbo", 1000, 500)
        assert cost_tracker.daily_spent_usd > 0
    
    def test_budget_check_exceeds_limit(self, cost_tracker):
        """Test that budget check fails when limit exceeded."""
        cost_tracker.daily_spent_usd = 9.5
        
        with pytest.raises(CostLimitError, match="Daily limit"):
            cost_tracker.check_budget_before_call(1.0)
    
    def test_cost_tracking_record(self, cost_tracker):
        """Test recording API calls and cost accumulation."""
        initial = cost_tracker.daily_spent_usd
        cost_tracker.record_call("gpt-4-turbo", 1000, 500)
        
        assert cost_tracker.daily_spent_usd > initial
    
    def test_daily_reset(self, cost_tracker):
        """Test that daily counter resets on new day."""
        cost_tracker.daily_spent_usd = 5.0
        cost_tracker.last_reset_date = datetime.utcnow().date() - timedelta(days=1)
        
        cost_tracker.reset_if_new_day()
        
        assert cost_tracker.daily_spent_usd == 0.0
    
    def test_no_limit_tracking(self):
        """Test tracking when no daily limit is set."""
        tracker = CostTracker(daily_limit_usd=None)
        tracker.check_budget_before_call(1000.0)  # Should not raise
        tracker.record_call("gpt-4-turbo", 1000, 500)
        # Should complete without error

# ============================================================================
# TokenCounter Tests
# ============================================================================

class TestTokenCounter:
    """Test token counting with tiktoken and fallback."""
    
    def test_token_counting_without_tiktoken(self, token_counter):
        """Test fallback to word count when tiktoken unavailable."""
        text = "This is a test sentence with multiple words."
        
        # Should return word count if tiktoken not available
        count = token_counter.count_tokens(text, "gpt-3.5-turbo")
        assert isinstance(count, int)
        assert count > 0
    
    def test_estimate_tokens_with_warning(self, token_counter):
        """Test that local models log debug warnings."""
        text = "Test prompt"
        count = token_counter.estimate_tokens(text, "local:llama2")
        
        assert isinstance(count, int)
        assert count > 0

# ============================================================================
# Exception Hierarchy Tests
# ============================================================================

class TestExceptionHierarchy:
    """Test custom exception types and inheritance."""
    
    def test_config_error(self):
        """Test ConfigError."""
        with pytest.raises(ConfigError):
            raise ConfigError("test")
    
    def test_auth_error(self):
        """Test AuthError."""
        with pytest.raises(AuthError):
            raise AuthError("test")
    
    def test_network_error(self):
        """Test NetworkError."""
        with pytest.raises(NetworkError):
            raise NetworkError("test")
    
    def test_validation_error(self):
        """Test ValidationError."""
        with pytest.raises(ValidationError):
            raise ValidationError("test")
    
    def test_cost_limit_error(self):
        """Test CostLimitError."""
        with pytest.raises(CostLimitError):
            raise CostLimitError("test")

# ============================================================================
# Provider Initialization Tests
# ============================================================================

class TestProviderInitialization:
    """Test provider initialization and error handling."""
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_azure_provider_init_success(self, mock_azure, temp_config_yaml, env_setup):
        """Test successful Azure provider initialization."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        
        provider = AzureOpenAIProvider(config)
        
        assert provider.client is not None
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_azure_provider_init_missing_config(self, mock_azure, temp_config_yaml, monkeypatch):
        """Test Azure provider with missing config."""
        monkeypatch.setenv("AZURE_ENDPOINT", "")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
        
        config = ConfigManager(temp_config_yaml)
        provider = AzureOpenAIProvider(config)
        
        assert provider.client is None
    
    @patch('agent_runner_refactored.Anthropic')
    def test_anthropic_provider_init_success(self, mock_anthropic, temp_config_yaml, env_setup):
        """Test successful Anthropic provider initialization."""
        mock_anthropic.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        
        provider = AnthropicProvider(config)
        
        assert provider.client is not None
    
    def test_ollama_provider_init(self, temp_config_yaml, env_setup):
        """Test Ollama provider initialization (no external deps)."""
        config = ConfigManager(temp_config_yaml)
        provider = OllamaProvider(config)
        
        assert provider.model == "llama2"
        assert "localhost:11434" in provider.host

# ============================================================================
# Output Validation Tests
# ============================================================================

class TestOutputValidation:
    """Test output schema validation with different modes."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.schema = {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "processor": {"type": "string"}
            },
            "required": ["owner", "processor"]
        }
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_validate_valid_output(self, mock_azure, temp_config_yaml, env_setup):
        """Test validation passes for valid output."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        router = AgentRouter(config)
        
        valid_output = json.dumps({"owner": "John", "processor": "Proc1"})
        
        # Should not raise
        router._validate_output(valid_output, self.schema, validation_mode="fail")
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_validate_invalid_json(self, mock_azure, temp_config_yaml, env_setup):
        """Test validation with invalid JSON."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        router = AgentRouter(config)
        
        invalid_json = "not valid json"
        
        # Should raise in fail mode
        with pytest.raises(ValidationError):
            router._validate_output(invalid_json, self.schema, validation_mode="fail")
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_validate_missing_required_field(self, mock_azure, temp_config_yaml, env_setup):
        """Test validation with missing required fields."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        router = AgentRouter(config)
        
        incomplete_output = json.dumps({"owner": "John"})  # missing 'processor'
        
        # Should raise in fail mode
        with pytest.raises(ValidationError):
            router._validate_output(incomplete_output, self.schema, validation_mode="fail")
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_validate_warn_mode(self, mock_azure, temp_config_yaml, env_setup):
        """Test validation in warn mode (doesn't raise)."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        router = AgentRouter(config)
        
        invalid_output = json.dumps({"owner": "John"})  # missing processor
        
        # Should not raise in warn mode
        router._validate_output(invalid_output, self.schema, validation_mode="warn")

# ============================================================================
# Retry Logic Tests
# ============================================================================

class TestRetryLogic:
    """Test retry decorator with exponential backoff."""
    
    def test_retry_succeeds_on_first_attempt(self):
        """Test successful call on first attempt."""
        call_count = 0
        
        @retry_with_backoff(max_retries=2)
        def mock_call():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = mock_call()
        
        assert result == "success"
        assert call_count == 1
    
    def test_retry_succeeds_after_transient_failure(self):
        """Test retry on transient failure."""
        call_count = 0
        
        @retry_with_backoff(max_retries=2, initial_delay_ms=10, max_delay_ms=20)
        def mock_call():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise NetworkError("transient")
            return "success"
        
        result = mock_call()
        
        assert result == "success"
        assert call_count == 2
    
    def test_retry_exhaustion(self):
        """Test retry exhaustion after max attempts."""
        call_count = 0
        
        @retry_with_backoff(max_retries=2, initial_delay_ms=10, max_delay_ms=20)
        def mock_call():
            nonlocal call_count
            call_count += 1
            raise NetworkError("persistent")
        
        with pytest.raises(NetworkError, match="persistent"):
            mock_call()
        
        assert call_count == 3  # initial + 2 retries

# ============================================================================
# AgentRouter Integration Tests
# ============================================================================

class TestAgentRouter:
    """Test agent router orchestration and fallback."""
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_router_initialization(self, mock_azure, temp_config_yaml, env_setup):
        """Test router initialization."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        
        router = AgentRouter(config)
        
        assert router.cost_tracker is not None
        assert router.routing_order is not None
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_router_cost_limit_enforcement(self, mock_azure, temp_config_yaml, env_setup):
        """Test that router enforces cost limits."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        router = AgentRouter(config)
        
        # Simulate cost at limit
        router.cost_tracker.daily_spent_usd = 10.0
        
        with pytest.raises(CostLimitError):
            router.run_agent(
                prompt="Test prompt",
                task="variance_assignment"
            )
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_router_unknown_task(self, mock_azure, temp_config_yaml, env_setup):
        """Test router with unknown task."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        router = AgentRouter(config)
        
        with pytest.raises(ConfigError, match="Unknown task"):
            router.run_agent(
                prompt="Test prompt",
                task="unknown_task"
            )
    
    @patch('agent_runner_refactored.AzureOpenAI')
    def test_router_timeout_configuration(self, mock_azure, temp_config_yaml, env_setup):
        """Test that router reads timeout from config."""
        mock_azure.return_value = MagicMock()
        config = ConfigManager(temp_config_yaml)
        router = AgentRouter(config)
        
        timeout = router.timeouts.get("azure_openai")
        assert timeout == 20

# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """End-to-end integration tests."""
    
    @patch('agent_runner_refactored.AzureOpenAI')
    @patch.object(AzureOpenAIProvider, 'call')
    def test_full_agent_run_mock(self, mock_call, mock_azure, temp_config_yaml, env_setup):
        """Test full agent run with mocked provider."""
        mock_azure.return_value = MagicMock()
        mock_call.return_value = {
            "model": "azure:gpt-4-turbo",
            "output": json.dumps({"owner": "John", "processor": "Proc1"}),
            "elapsed_ms": 1500,
            "tokens_in": 500,
            "tokens_out": 200,
        }
        
        config = ConfigManager(temp_config_yaml)
        router = AgentRouter(config)
        
        result = router.run_agent(
            prompt="Test prompt",
            task="variance_assignment"
        )
        
        assert result is not None
        assert result.get("model") == "azure:gpt-4-turbo"
        assert "owner" in result.get("output", "{}")

# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])
