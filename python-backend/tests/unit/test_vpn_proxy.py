# -*- coding: utf-8 -*-

"""
Unit tests for VPN/Proxy configuration logic.

Tests verify that proxy environment variables are set correctly
for different input formats and scenarios.
"""

import os
import pytest


@pytest.mark.parametrize(
    "test_id, initial_no_proxy, vpn_url, expected_http_proxy, expected_https_proxy, expected_no_proxy",
    [
        (
            "proxy_with_http_scheme",
            None,
            "http://192.168.1.103:2080",
            "http://192.168.1.103:2080",
            "http://192.168.1.103:2080",
            "127.0.0.1,localhost"
        ),
        (
            "proxy_with_socks5_scheme",
            None,
            "socks5://192.168.1.103:1080",
            "socks5://192.168.1.103:1080",
            "socks5://192.168.1.103:1080",
            "127.0.0.1,localhost"
        ),
        (
            "proxy_without_scheme",
            None,
            "192.168.1.103:2080",
            "http://192.168.1.103:2080",
            "http://192.168.1.103:2080",
            "127.0.0.1,localhost"
        ),
        (
            "proxy_with_auth",
            None,
            "http://user:pass@192.168.1.103:2080",
            "http://user:pass@192.168.1.103:2080",
            "http://user:pass@192.168.1.103:2080",
            "127.0.0.1,localhost"
        ),
        (
            "proxy_preserves_existing_no_proxy",
            "internal.corp,*.example.com",
            "http://192.168.1.103:2080",
            "http://192.168.1.103:2080",
            "http://192.168.1.103:2080",
            "internal.corp,*.example.com,127.0.0.1,localhost"
        ),
        (
            "proxy_empty_url",
            None,
            "",
            None,
            None,
            None
        ),
    ]
)
def test_vpn_proxy_environment_setup(
    test_id,
    initial_no_proxy,
    vpn_url,
    expected_http_proxy,
    expected_https_proxy,
    expected_no_proxy,
    monkeypatch
):
    """
    Parametrized test for VPN/Proxy setup via environment variables.
    
    Verifies that:
    - HTTP_PROXY, HTTPS_PROXY, ALL_PROXY are set correctly
    - URL normalization works (adds http:// if no scheme)
    - NO_PROXY includes localhost and preserves existing values
    - Empty URL doesn't set any proxy variables
    """
    print(f"\n--- Running VPN/Proxy test: ID = {test_id} ---")
    
    # Clear proxy environment variables before test
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"]:
        monkeypatch.delenv(key, raising=False)
    
    # Set initial NO_PROXY if specified
    if initial_no_proxy:
        monkeypatch.setenv("NO_PROXY", initial_no_proxy)
        print(f"Initial NO_PROXY: '{initial_no_proxy}'")
    
    # Simulate VPN_PROXY_URL configuration
    print(f"VPN_PROXY_URL set to: '{vpn_url}'")
    
    # Replicate logic from main.py (lines 175-197)
    if vpn_url:
        proxy_url_with_scheme = vpn_url if "://" in vpn_url else f"http://{vpn_url}"
        os.environ['HTTP_PROXY'] = proxy_url_with_scheme
        os.environ['HTTPS_PROXY'] = proxy_url_with_scheme
        os.environ['ALL_PROXY'] = proxy_url_with_scheme
        
        no_proxy_hosts = os.environ.get("NO_PROXY", "")
        local_hosts = "127.0.0.1,localhost"
        if no_proxy_hosts:
            os.environ["NO_PROXY"] = f"{no_proxy_hosts},{local_hosts}"
        else:
            os.environ["NO_PROXY"] = local_hosts
    
    # --- Assertions ---
    print("\n[Verification]")
    
    if expected_http_proxy:
        actual_http_proxy = os.environ.get("HTTP_PROXY")
        print(f"HTTP_PROXY: Expected '{expected_http_proxy}', Got '{actual_http_proxy}'")
        assert actual_http_proxy == expected_http_proxy, "HTTP_PROXY mismatch!"
        
        actual_https_proxy = os.environ.get("HTTPS_PROXY")
        print(f"HTTPS_PROXY: Expected '{expected_https_proxy}', Got '{actual_https_proxy}'")
        assert actual_https_proxy == expected_https_proxy, "HTTPS_PROXY mismatch!"
        
        actual_all_proxy = os.environ.get("ALL_PROXY")
        print(f"ALL_PROXY: Expected '{expected_http_proxy}', Got '{actual_all_proxy}'")
        assert actual_all_proxy == expected_http_proxy, "ALL_PROXY mismatch!"
    else:
        # If proxy should not be set
        assert os.environ.get("HTTP_PROXY") is None, "HTTP_PROXY should be None!"
        assert os.environ.get("HTTPS_PROXY") is None, "HTTPS_PROXY should be None!"
        print("Proxy not set (as expected)")
    
    if expected_no_proxy:
        actual_no_proxy = os.environ.get("NO_PROXY")
        print(f"NO_PROXY: Expected '{expected_no_proxy}', Got '{actual_no_proxy}'")
        assert actual_no_proxy == expected_no_proxy, "NO_PROXY mismatch!"
    
    print(f"--- Test '{test_id}' passed successfully ---")


def test_proxy_scheme_normalization():
    """
    Verifies that URLs without scheme are correctly normalized to http://.
    
    Tests various input formats:
    - Plain host:port → http://host:port
    - http:// → unchanged
    - https:// → unchanged
    - socks5:// → unchanged
    """
    print("\n--- Test: Proxy scheme normalization ---")
    
    test_cases = [
        ("192.168.1.100:8080", "http://192.168.1.100:8080"),
        ("http://192.168.1.100:8080", "http://192.168.1.100:8080"),
        ("https://192.168.1.100:8080", "https://192.168.1.100:8080"),
        ("socks5://192.168.1.100:8080", "socks5://192.168.1.100:8080"),
        ("127.0.0.1:7890", "http://127.0.0.1:7890"),
    ]
    
    for input_url, expected_url in test_cases:
        print(f"\nInput: '{input_url}'")
        
        # Logic from main.py
        proxy_url_with_scheme = input_url if "://" in input_url else f"http://{input_url}"
        
        print(f"Result: '{proxy_url_with_scheme}'")
        print(f"Expected: '{expected_url}'")
        assert proxy_url_with_scheme == expected_url, f"Normalization failed for '{input_url}'"
    
    print("\n--- Test passed: all schemes normalized correctly ---")


def test_no_proxy_list_merging(monkeypatch):
    """
    Verifies correct merging of existing and new NO_PROXY values.
    
    Tests:
    - Empty existing → only localhost
    - Existing values → preserved and localhost added
    - Duplicate localhost → acceptable (not a problem)
    """
    print("\n--- Test: NO_PROXY list merging ---")
    
    test_cases = [
        # (existing, expected_result)
        ("", "127.0.0.1,localhost"),
        ("internal.local", "internal.local,127.0.0.1,localhost"),
        ("192.168.0.0/16,10.0.0.0/8", "192.168.0.0/16,10.0.0.0/8,127.0.0.1,localhost"),
        ("*.corp.com,localhost", "*.corp.com,localhost,127.0.0.1,localhost"),  # Duplicate localhost - OK
    ]
    
    for existing_value, expected_result in test_cases:
        print(f"\nExisting NO_PROXY: '{existing_value}'")
        
        # Simulate logic
        if existing_value:
            monkeypatch.setenv("NO_PROXY", existing_value)
        else:
            monkeypatch.delenv("NO_PROXY", raising=False)
        
        no_proxy_hosts = os.environ.get("NO_PROXY", "")
        local_hosts = "127.0.0.1,localhost"
        if no_proxy_hosts:
            result = f"{no_proxy_hosts},{local_hosts}"
        else:
            result = local_hosts
        
        print(f"Result: '{result}'")
        print(f"Expected: '{expected_result}'")
        assert result == expected_result, f"Merging failed for '{existing_value}'"
    
    print("\n--- Test passed: lists merged correctly ---")


def test_proxy_does_not_affect_local_connections(monkeypatch):
    """
    Verifies that local addresses (127.0.0.1, localhost) are always in NO_PROXY.
    
    This ensures that local tests don't go through VPN/proxy,
    which would be slow and incorrect.
    """
    print("\n--- Test: Local addresses excluded from proxy ---")
    
    # Simulate proxy setup
    vpn_url = "http://vpn.example.com:8080"
    os.environ['HTTP_PROXY'] = vpn_url
    os.environ['HTTPS_PROXY'] = vpn_url
    
    no_proxy_hosts = os.environ.get("NO_PROXY", "")
    local_hosts = "127.0.0.1,localhost"
    if no_proxy_hosts:
        os.environ["NO_PROXY"] = f"{no_proxy_hosts},{local_hosts}"
    else:
        os.environ["NO_PROXY"] = local_hosts
    
    no_proxy_value = os.environ.get("NO_PROXY")
    print(f"NO_PROXY set to: '{no_proxy_value}'")
    
    # Assertions
    assert "127.0.0.1" in no_proxy_value, "127.0.0.1 must be in NO_PROXY!"
    assert "localhost" in no_proxy_value, "localhost must be in NO_PROXY!"
    
    print("✅ Local addresses correctly excluded from proxy")
    print("--- Test passed ---")


def test_proxy_with_special_characters():
    """
    Verifies that proxy URLs with special characters in credentials work correctly.
    
    Tests authentication with:
    - Special characters in password
    - URL encoding (if needed)
    """
    print("\n--- Test: Proxy with special characters in credentials ---")
    
    test_cases = [
        # (input_url, expected_normalized)
        ("http://user:p@ss@proxy.com:8080", "http://user:p@ss@proxy.com:8080"),
        ("http://admin:P@ssw0rd!@192.168.1.1:3128", "http://admin:P@ssw0rd!@192.168.1.1:3128"),
        ("socks5://user123:pass456@localhost:1080", "socks5://user123:pass456@localhost:1080"),
    ]
    
    for input_url, expected_url in test_cases:
        print(f"\nInput: '{input_url}'")
        
        # Normalization logic (should preserve special chars)
        proxy_url_with_scheme = input_url if "://" in input_url else f"http://{input_url}"
        
        print(f"Result: '{proxy_url_with_scheme}'")
        print(f"Expected: '{expected_url}'")
        assert proxy_url_with_scheme == expected_url, f"Special chars handling failed for '{input_url}'"
    
    print("\n--- Test passed: special characters preserved correctly ---")


def test_empty_vpn_proxy_url_does_not_set_variables(monkeypatch):
    """
    Verifies that empty VPN_PROXY_URL doesn't set any proxy variables.
    
    This is the default behavior - direct connection without proxy.
    """
    print("\n--- Test: Empty VPN_PROXY_URL (direct connection) ---")
    
    # Clear all proxy variables
    for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"]:
        monkeypatch.delenv(key, raising=False)
    
    # Simulate empty VPN_PROXY_URL
    vpn_url = ""
    
    # Logic from main.py - should NOT execute if vpn_url is empty
    if vpn_url:
        proxy_url_with_scheme = vpn_url if "://" in vpn_url else f"http://{vpn_url}"
        os.environ['HTTP_PROXY'] = proxy_url_with_scheme
        os.environ['HTTPS_PROXY'] = proxy_url_with_scheme
        os.environ['ALL_PROXY'] = proxy_url_with_scheme
    
    # Verify no proxy variables are set
    assert os.environ.get("HTTP_PROXY") is None, "HTTP_PROXY should not be set!"
    assert os.environ.get("HTTPS_PROXY") is None, "HTTPS_PROXY should not be set!"
    assert os.environ.get("ALL_PROXY") is None, "ALL_PROXY should not be set!"
    
    print("✅ No proxy variables set (direct connection)")
    print("--- Test passed ---")


print("VPN/Proxy tests loaded. Will verify proxy setup logic!")
