import pytest
from flask.sansio.app import App

def test_select_jinja_autoescape_type_annotation():
    ann = App.select_jinja_autoescape.__annotations__["filename"]
    assert "None" in str(ann)
