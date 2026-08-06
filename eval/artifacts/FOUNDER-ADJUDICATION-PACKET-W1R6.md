# Founder Adjudication Packet — W1-R6 Candidates

## Candidate 1: _default_template_ctx_processor
- Candidate ID: flask_27be9338_c17f3793_1785943927_6ade5953
- Test Name: test_default_template_ctx_processor_includes_session
- Target Symbol: `_default_template_ctx_processor`
- Base SHA: `27be9338405382445a7cb01151e084559b98d602`
- Head SHA: `c17f379390731543eea33a570a47bd4ef76a54fa`
- Flask Commit / PR: https://github.com/pallets/flask/commit/c17f379390731543eea33a570a47bd4ef76a54fa
- Assessor Verdict: intended_change (Confidence: 0.9)
- Surface Status: surfaced (catching) | Pair Validity: valid
- Rerun Agreement: True | Rerun Status: reported_unverified
- Candidate SHA-256: `6ade5953ab5feb9fd19b93dff5581ebfc7201eb949ea13c2a6351d0beca093e5`
- Human Review Status: done | Adjudication Status: adjudicated
- Reviewer: Amaan Mansuri | Date: 2026-08-06
- Human Decision: `intended_change_false_alert`
- Human Rationale: Flask deliberately removed session from the default template-context processor so that constructing the context does not implicitly mark the session as accessed. The candidate asserts the superseded behavior.

### Production Diff Output SHA-256
`b1e1e4c765691f2827c6d770e0d45e90e43c7da4942f8e5c8830ff2b6de8b466`

```diff
diff --git a/src/flask/app.py b/src/flask/app.py
index a58b3c9b..89ca92e4 100644
--- a/src/flask/app.py
+++ b/src/flask/app.py
@@ -877,7 +877,6 @@ class Flask(App):
         def _default_template_ctx_processor() -> dict[str, t.Any]:
             reqctx = _cv_request.get(None)
             appctx = _cv_app.get(None)
             rv: dict[str, t.Any] = {}
             if appctx is not None:
                 rv["g"] = appctx.g
             if reqctx is not None:
                 rv["request"] = reqctx.request
-                rv["session"] = reqctx.session
             return rv
```

---

## Candidate 2: RequestContext.__init__
- Candidate ID: flask_27be9338_c17f3793_1785943927_c5cf3f7b
- Test Name: test_request_context_session_attribute
- Target Symbol: `RequestContext.__init__`
- Base SHA: `27be9338405382445a7cb01151e084559b98d602`
- Head SHA: `c17f379390731543eea33a570a47bd4ef76a54fa`
- Flask Commit / PR: https://github.com/pallets/flask/commit/c17f379390731543eea33a570a47bd4ef76a54fa
- Assessor Verdict: real_regression (Confidence: 0.9)
- Surface Status: surfaced (catching) | Pair Validity: valid
- Rerun Agreement: True | Rerun Status: reported_unverified
- Candidate SHA-256: `c5cf3f7b5b9de93465685c54fadd4786c94ec905a80846e9d256b3eaf5aad507`
- Human Review Status: done | Adjudication Status: adjudicated
- Reviewer: Amaan Mansuri | Date: 2026-08-06
- Human Decision: `intended_change_false_alert`
- Human Rationale: The change deliberately introduced RequestContext.session as an access-tracking property backed by _session. The candidate passes a plain dict where the declared contract expects SessionMixin and tests pre-push behavior that conflicts with the intentional access-tracking design.

### Production Diff Output SHA-256
`593716c78b36f493728c1f1eb8ad0d111f4516586e14bd49bdadd1ef820a6ea3`

```diff
diff --git a/src/flask/ctx.py b/src/flask/ctx.py
index a1a1b1a4..e4b4b2a8 100644
--- a/src/flask/ctx.py
+++ b/src/flask/ctx.py
@@ -298,7 +298,7 @@ class RequestContext:
         self.request = app.request_class(environ)
         self.url_adapter = None
         self.flashes = None
-        self.session: SessionMixin | None = session
+        self._session: SessionMixin | None = session
         self._cv_tokens: list[tuple[contextvars.Token[RequestContext], AppContext | None]] = []

     @property
     def session(self) -> SessionMixin:
         if self._session is None:
             self._session = self.app.open_session(self.request)
         return self._session
```

---

## Candidate 3: redirect
- Candidate ID: flask_eb58d862_eca5fd1d_1785945552_a7bd7e7d
- Test Name: test_redirect_default_status_code
- Target Symbol: `redirect`
- Base SHA: `eb58d862cc4a8f31a369b6e9ad1724e9e642f13f`
- Head SHA: `eca5fd1dfdc614c2df876cc32018a7d71f84ea82`
- Flask Commit / PR: https://github.com/pallets/flask/commit/eca5fd1dfdc614c2df876cc32018a7d71f84ea82
- Assessor Verdict: intended_change (Confidence: 0.9)
- Surface Status: surfaced (catching) | Pair Validity: valid
- Rerun Agreement: True | Rerun Status: reported_unverified
- Candidate SHA-256: `a7bd7e7d85873609aa00361363dc37d974ac6bbc66f1295b16b057c821d684a9`
- Human Review Status: done | Adjudication Status: adjudicated
- Reviewer: Amaan Mansuri | Date: 2026-08-06
- Human Decision: `intended_change_false_alert`
- Human Rationale: Flask deliberately changed the default redirect status from 302 to 303. The candidate asserts the former 302 default.

### Production Diff Output SHA-256
`d067a4ce3c91c3f2c96491e600279b6ca0bb40446c7fb4b43ad998cfe0c3a4c3`

```diff
diff --git a/src/flask/helpers.py b/src/flask/helpers.py
index a5b1b4c9..8a7c12d4 100644
--- a/src/flask/helpers.py
+++ b/src/flask/helpers.py
@@ -420,7 +420,7 @@ def redirect(location: str, code: int = 303, Response: type[Response] | None = None) -> Response:
     ...
```

---

## Candidate 4: SecureCookieSession
- Candidate ID: flask_d98eb69a_f00ad424_1785943861_df8a2712
- Test Name: test_SecureCookieSession_accessed_on_get
- Target Symbol: `SecureCookieSession`
- Base SHA: `d98eb69a354158252854ed4a5c9778e03d089191`
- Head SHA: `f00ad424ee3b050d382cc5b4aabb18afbb5e4ae7`
- Flask Commit / PR: https://github.com/pallets/flask/commit/f00ad424ee3b050d382cc5b4aabb18afbb5e4ae7
- Assessor Verdict: real_regression (Confidence: 0.9)
- Surface Status: surfaced (catching) | Pair Validity: EXCLUDED (base is not an ancestor of head)
- Mechanical Measurement Status: invalid_pair
- Mechanical Recommendation: indeterminate
- Rerun Agreement: False | Rerun Status: reported_unverified
- Candidate SHA-256: `df8a27125addbffb11eda071cea0b6538787bd1c26e71c9b9f2f15c34bf49e4b`
- Human Review Status: done | Adjudication Status: adjudicated
- Reviewer: Amaan Mansuri | Date: 2026-08-06
- Human Decision: `indeterminate`
- Human Rationale: The base is not an ancestor of the head, no valid pairwise production diff exists, and the reported rerun disagreed with the original result. This historical row cannot support a real-regression or false-alert classification.

### Production Diff Output SHA-256
`No valid pairwise production diff exists for this historical row`

```
Ancestry check failed: git merge-base --is-ancestor d98eb69a354158252854ed4a5c9778e03d089191 f00ad424ee3b050d382cc5b4aabb18afbb5e4ae7 returned exit code 1. Base commit d98eb69a is not reachable from head commit f00ad424 in git history.
```
