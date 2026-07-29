from types import SimpleNamespace

from plugins_func.functions.get_weather import _resolve_weather_api_config


def make_conn(plugin_config):
    return SimpleNamespace(config={"plugins": {"get_weather": plugin_config}})


def test_resolve_weather_api_config_falls_back_to_default_when_config_is_placeholder(monkeypatch):
    monkeypatch.delenv("QWEATHER_HOST", raising=False)
    monkeypatch.delenv("QWEATHER_KEY", raising=False)

    conn = make_conn({"api_host": "你的host", "api_key": "你的key"})
    host, key, source = _resolve_weather_api_config(conn)

    assert host.endswith("mx3v59pgjm.re.qweatherapi.com")
    assert key == "49d53330fd4f48e78e99eea3aa13f329"
    assert source == "default"


def test_resolve_weather_api_config_uses_plugin_config_when_present(monkeypatch):
    monkeypatch.setenv("QWEATHER_HOST", "https://env.example.com")
    monkeypatch.setenv("QWEATHER_KEY", "env-key")

    conn = make_conn({"api_host": "https://weather.company.com", "api_key": "plugin-key"})
    host, key, source = _resolve_weather_api_config(conn)

    assert host == "https://weather.company.com"
    assert key == "plugin-key"
    assert source == "config"


def test_resolve_weather_api_config_ignores_masked_credentials(monkeypatch):
    monkeypatch.delenv("QWEATHER_HOST", raising=False)
    monkeypatch.delenv("QWEATHER_KEY", raising=False)

    conn = make_conn({"api_host": "https://weather.company.com", "api_key": "***"})
    host, key, source = _resolve_weather_api_config(conn)

    assert host.endswith("mx3v59pgjm.re.qweatherapi.com")
    assert key == "49d53330fd4f48e78e99eea3aa13f329"
    assert source == "default"
