import requests


def test_graphite_web_should_be_running(graphite_web):
    assert requests.get(f"{graphite_web}/render").status_code == 200
