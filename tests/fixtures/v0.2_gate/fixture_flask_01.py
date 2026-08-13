import flask
import flask.views


def test_provide_automatic_options_config():
    app = flask.Flask(__name__)
    app.config["PROVIDE_AUTOMATIC_OPTIONS"] = False

    class Index(flask.views.View):
        provide_automatic_options = True

        def dispatch_request(self):
            return "Hello World!"

    app.add_url_rule("/", view_func=Index.as_view("index"))
    c = app.test_client()
    rv = c.open("/", method="OPTIONS")
    assert sorted(rv.allow) == ["GET", "HEAD", "OPTIONS"]
