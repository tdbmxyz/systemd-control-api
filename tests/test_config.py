"""Tests for configuration loading and validation."""

import os
import pytest
from unittest.mock import patch


class TestGetConfig:
    """Tests for get_config() function."""

    def test_config_with_api_key_only(self):
        """Config should work with just API key set."""
        from systemd_control_api import get_config

        env = {
            "SYSTEMD_CONTROL_API_KEY": "test-key-123",
            "SYSTEMD_CONTROL_API_PORT": "9000",
            "SYSTEMD_CONTROL_API_SERVICES": '[{"service": "test.service", "displayName": "Test", "description": "Test service"}]',
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_config()

            assert config.api_key == "test-key-123"
            assert config.port == 9000
            assert len(config.services) == 1
            assert config.services[0]["service"] == "test.service"
            assert config.allowed_hosts == []
            assert config.has_api_key is True
            assert config.has_host_restriction is False

    def test_config_with_allowed_hosts_only(self):
        """Config should work with just allowed hosts set."""
        from systemd_control_api import get_config

        env = {
            "SYSTEMD_CONTROL_API_ALLOWED_HOSTS": "localhost,192.168.1.0/24",
            "SYSTEMD_CONTROL_API_SERVICES": "[]",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_config()

            assert config.api_key is None
            assert config.allowed_hosts == ["localhost", "192.168.1.0/24"]
            assert config.has_api_key is False
            assert config.has_host_restriction is True

    def test_config_with_both_security_methods(self):
        """Config should work with both API key and allowed hosts."""
        from systemd_control_api import get_config

        env = {
            "SYSTEMD_CONTROL_API_KEY": "test-key",
            "SYSTEMD_CONTROL_API_ALLOWED_HOSTS": "localhost",
            "SYSTEMD_CONTROL_API_SERVICES": "[]",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_config()

            assert config.has_api_key is True
            assert config.has_host_restriction is True

    def test_config_without_security(self):
        """Config should work without any security for reverse proxy deployments."""
        from systemd_control_api import get_config

        env = {
            "SYSTEMD_CONTROL_API_SERVICES": "[]",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_config()

            assert config.api_key is None
            assert config.allowed_hosts == []
            assert config.has_api_key is False
            assert config.has_host_restriction is False

    def test_config_default_port(self):
        """Config should use default port 8080 if not specified."""
        from systemd_control_api import get_config

        env = {
            "SYSTEMD_CONTROL_API_KEY": "test-key",
            "SYSTEMD_CONTROL_API_SERVICES": "[]",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_config()
            assert config.port == 8080

    def test_config_invalid_services_json(self):
        """Config should fail with invalid JSON for services."""
        from systemd_control_api import get_config

        env = {
            "SYSTEMD_CONTROL_API_KEY": "test-key",
            "SYSTEMD_CONTROL_API_SERVICES": "not valid json",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="must be valid JSON"):
                get_config()

    def test_config_empty_allowed_hosts_string(self):
        """Empty allowed hosts string should result in empty list."""
        from systemd_control_api import get_config

        env = {
            "SYSTEMD_CONTROL_API_KEY": "test-key",
            "SYSTEMD_CONTROL_API_ALLOWED_HOSTS": "",
            "SYSTEMD_CONTROL_API_SERVICES": "[]",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_config()
            assert config.allowed_hosts == []
            assert config.has_host_restriction is False

    def test_config_allowed_hosts_whitespace_handling(self):
        """Allowed hosts should handle whitespace properly."""
        from systemd_control_api import get_config

        env = {
            "SYSTEMD_CONTROL_API_ALLOWED_HOSTS": " localhost , 10.0.0.1 , ",
            "SYSTEMD_CONTROL_API_SERVICES": "[]",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_config()
            assert config.allowed_hosts == ["localhost", "10.0.0.1"]


class TestConfigProperties:
    """Tests for Config dataclass properties."""

    def test_has_api_key_true(self):
        """has_api_key should be True when api_key is set."""
        from systemd_control_api import Config

        config = Config(
            api_key="secret",
            port=8080,
            services=[],
            allowed_hosts=[],
        )
        assert config.has_api_key is True

    def test_has_api_key_false_when_none(self):
        """has_api_key should be False when api_key is None."""
        from systemd_control_api import Config

        config = Config(
            api_key=None,
            port=8080,
            services=[],
            allowed_hosts=["localhost"],
        )
        assert config.has_api_key is False

    def test_has_api_key_false_when_empty(self):
        """has_api_key should be False when api_key is empty string."""
        from systemd_control_api import Config

        config = Config(
            api_key="",
            port=8080,
            services=[],
            allowed_hosts=["localhost"],
        )
        assert config.has_api_key is False

    def test_has_host_restriction_true(self):
        """has_host_restriction should be True when allowed_hosts is non-empty."""
        from systemd_control_api import Config

        config = Config(
            api_key="secret",
            port=8080,
            services=[],
            allowed_hosts=["localhost"],
        )
        assert config.has_host_restriction is True

    def test_has_host_restriction_false(self):
        """has_host_restriction should be False when allowed_hosts is empty."""
        from systemd_control_api import Config

        config = Config(
            api_key="secret",
            port=8080,
            services=[],
            allowed_hosts=[],
        )
        assert config.has_host_restriction is False
