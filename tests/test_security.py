"""Tests for IP/host allowlist functionality."""


class TestIsIpAllowed:
    """Tests for is_ip_allowed() function."""

    def test_exact_ipv4_match(self):
        """Should match exact IPv4 address."""
        from systemd_control_api import is_ip_allowed

        assert is_ip_allowed("192.168.1.100", ["192.168.1.100"]) is True
        assert is_ip_allowed("192.168.1.101", ["192.168.1.100"]) is False

    def test_cidr_ipv4_match(self):
        """Should match IPv4 addresses within CIDR range."""
        from systemd_control_api import is_ip_allowed

        allowed = ["192.168.1.0/24"]
        assert is_ip_allowed("192.168.1.1", allowed) is True
        assert is_ip_allowed("192.168.1.254", allowed) is True
        assert is_ip_allowed("192.168.2.1", allowed) is False

    def test_localhost_keyword(self):
        """Should match localhost keyword to 127.0.0.1 and ::1."""
        from systemd_control_api import is_ip_allowed

        allowed = ["localhost"]
        assert is_ip_allowed("127.0.0.1", allowed) is True
        assert is_ip_allowed("::1", allowed) is True
        assert is_ip_allowed("192.168.1.1", allowed) is False

    def test_ipv6_exact_match(self):
        """Should match exact IPv6 address."""
        from systemd_control_api import is_ip_allowed

        assert is_ip_allowed("::1", ["::1"]) is True
        assert is_ip_allowed("2001:db8::1", ["2001:db8::1"]) is True
        assert is_ip_allowed("2001:db8::2", ["2001:db8::1"]) is False

    def test_ipv6_cidr_match(self):
        """Should match IPv6 addresses within CIDR range."""
        from systemd_control_api import is_ip_allowed

        allowed = ["2001:db8::/32"]
        assert is_ip_allowed("2001:db8::1", allowed) is True
        assert is_ip_allowed("2001:db8:1::1", allowed) is True
        assert is_ip_allowed("2001:db9::1", allowed) is False

    def test_multiple_allowed_hosts(self):
        """Should match if any allowed host matches."""
        from systemd_control_api import is_ip_allowed

        allowed = ["localhost", "192.168.1.0/24", "10.0.0.5"]
        assert is_ip_allowed("127.0.0.1", allowed) is True
        assert is_ip_allowed("192.168.1.50", allowed) is True
        assert is_ip_allowed("10.0.0.5", allowed) is True
        assert is_ip_allowed("10.0.0.6", allowed) is False

    def test_empty_allowed_list(self):
        """Should not match if allowed list is empty."""
        from systemd_control_api import is_ip_allowed

        assert is_ip_allowed("127.0.0.1", []) is False

    def test_invalid_client_ip(self):
        """Should handle invalid client IP gracefully."""
        from systemd_control_api import is_ip_allowed

        # Invalid IP falls back to string comparison
        assert is_ip_allowed("not-an-ip", ["not-an-ip"]) is True
        assert is_ip_allowed("not-an-ip", ["localhost"]) is False

    def test_hostname_string_match(self):
        """Should do string comparison for non-IP hostnames."""
        from systemd_control_api import is_ip_allowed

        # Note: This tests string comparison, not DNS resolution
        assert is_ip_allowed("myhost.local", ["myhost.local"]) is True


class TestGetCorsOrigins:
    """Tests for get_cors_origins() function."""

    def test_returns_empty_when_no_config(self):
        """Should return empty list when CONFIG is None."""
        import systemd_control_api

        original_config = systemd_control_api.CONFIG
        try:
            systemd_control_api.CONFIG = None
            from systemd_control_api import get_cors_origins

            assert get_cors_origins() == []
        finally:
            systemd_control_api.CONFIG = original_config

    def test_returns_empty_when_no_host_restriction(self):
        """Should return empty list when no host restriction configured."""
        import systemd_control_api
        from systemd_control_api import Config, get_cors_origins

        original_config = systemd_control_api.CONFIG
        try:
            systemd_control_api.CONFIG = Config(
                api_key="test",
                port=8080,
                services=[],
                allowed_hosts=[],
            )
            assert get_cors_origins() == []
        finally:
            systemd_control_api.CONFIG = original_config

    def test_converts_localhost_to_origins(self):
        """Should convert localhost to http and https origins."""
        import systemd_control_api
        from systemd_control_api import Config, get_cors_origins

        original_config = systemd_control_api.CONFIG
        try:
            systemd_control_api.CONFIG = Config(
                api_key=None,
                port=8080,
                services=[],
                allowed_hosts=["localhost"],
            )
            origins = get_cors_origins()
            assert "http://localhost" in origins
            assert "https://localhost" in origins
        finally:
            systemd_control_api.CONFIG = original_config

    def test_converts_ip_to_origins(self):
        """Should convert IP addresses to http and https origins."""
        import systemd_control_api
        from systemd_control_api import Config, get_cors_origins

        original_config = systemd_control_api.CONFIG
        try:
            systemd_control_api.CONFIG = Config(
                api_key=None,
                port=8080,
                services=[],
                allowed_hosts=["192.168.1.100"],
            )
            origins = get_cors_origins()
            assert "http://192.168.1.100" in origins
            assert "https://192.168.1.100" in origins
        finally:
            systemd_control_api.CONFIG = original_config

    def test_skips_cidr_ranges(self):
        """Should skip CIDR ranges (can't be used in CORS directly)."""
        import systemd_control_api
        from systemd_control_api import Config, get_cors_origins

        original_config = systemd_control_api.CONFIG
        try:
            systemd_control_api.CONFIG = Config(
                api_key=None,
                port=8080,
                services=[],
                allowed_hosts=["192.168.1.0/24"],
            )
            origins = get_cors_origins()
            # CIDR should not produce any origins
            assert origins == []
        finally:
            systemd_control_api.CONFIG = original_config
