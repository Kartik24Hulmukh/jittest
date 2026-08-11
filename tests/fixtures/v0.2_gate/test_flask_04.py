import pytest
import flask

def test_host_matching_with_server_name():
    app = flask.Flask(__name__, host_matching=True, static_host="example.test")
    app.config["SERVER_NAME"] = "example.test"
    @app.route("/", host="xyz.other.test")
    def index(): return "xyz"
    client = app.test_client()
    r = client.get("/", base_url="http://xyz.other.test")
    assert r.status_code == 200
    assert r.text == "xyz"
