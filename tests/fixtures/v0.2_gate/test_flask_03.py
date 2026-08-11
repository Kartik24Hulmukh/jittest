import pytest
from flask import Flask
from flask.sessions import SecureCookieSessionInterface

def test_secret_key_fallbacks_order():
    app = Flask(__name__)
    app.secret_key = 'primary'
    app.config['SECRET_KEY_FALLBACKS'] = ['fallback']

    serializer = SecureCookieSessionInterface().get_signing_serializer(app)
    assert serializer.secret_keys[0] == b'fallback'
