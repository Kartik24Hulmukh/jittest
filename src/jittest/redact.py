"""Defect 65: secrets must not reach reported output.

Environment isolation (Defect 62) stopped a generated test from reading the
runner's credentials. It does not stop a secret from reaching a pull-request
comment by a different route, and there are several:

- The repository under test has its own secrets. A candidate that imports the
  application triggers config loading, and a `.env` file, a settings object, or
  a connection string lands in the traceback.
- pytest prints local variables for the failing frame. A local named `token` is
  printed with its value.
- The application's own logging writes an Authorization header to stderr.

Every one of those ends up in `RunResult.tail`, which becomes
`Verdict.failure_excerpt`, which jittest quotes into a public comment. jittest
would be the thing that published the secret, on behalf of a repository that
was keeping it correctly.

Redaction is applied at the single choke point where captured output is turned
into an excerpt, so no future call site can forget it.

This is deliberately conservative in one direction: it prefers to mask
something harmless over leaking something real. A masked token still leaves the
surrounding traceback readable, so the reviewer loses almost nothing, whereas a
leaked token cannot be un-leaked. It is NOT a guarantee - a determined encoder
(base64, reversed strings, split across lines) defeats any regex. It removes
the accidental disclosures, which are the ones that actually happen.
"""
from __future__ import annotations

import re

__all__ = ["redact", "MASK"]

MASK = "[redacted by jittest]"

# Vendor-specific formats first. These are unambiguous: the prefix is issued by
# the vendor and means "this is a credential", so matching them is not a guess.
# No leading \b: a token pasted straight onto preceding text (log lines run
# together, truncated output, no separator) has no word boundary in front of
# it, and that is exactly when it would slip through.
_VENDOR = re.compile(
    r"""(?x)
    (
        nvapi-[A-Za-z0-9_\-]{20,}          # NVIDIA
      | sk-[A-Za-z0-9_\-]{20,}             # OpenAI and lookalikes
      | ghp_[A-Za-z0-9]{20,}               # GitHub personal access token
      | gho_[A-Za-z0-9]{20,}
      | ghs_[A-Za-z0-9]{20,}
      | ghu_[A-Za-z0-9]{20,}
      | github_pat_[A-Za-z0-9_]{20,}
      | xox[abposr]-[A-Za-z0-9\-]{10,}     # Slack
      | AKIA[0-9A-Z]{16}                   # AWS access key id
      | ASIA[0-9A-Z]{16}
      | AIza[0-9A-Za-z_\-]{30,}            # Google API key
      | ya29\.[0-9A-Za-z_\-]{20,}          # Google OAuth
      | eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}  # JWT
    )\b
    """
)

# PEM private key blocks. Masked whole rather than line by line, because a
# partial key is still a disclosure and the header alone is not useful.
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.DOTALL,
)

# A credential-shaped NAME bound to a value. This is the shape that actually
# leaks: an env var assigning a database password, a JSON "token" field, a
# config line setting an api key. The examples are described, not written out,
# because a literal name=value in this comment is indistinguishable from a
# real credential to a secret scanner (GitGuardian flagged them - correctly).
# The name is kept so the reviewer can see WHAT was withheld; only the value
# is masked.
_NAME = (
    r"[A-Za-z0-9_.\-]*"
    r"(?:API_?KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|PRIVATE_?KEY"
    r"|SESSION|COOKIE|AUTH|NVAPI|ACCESS_?KEY|CLIENT_?SECRET)"
    r"[A-Za-z0-9_.\-]*"
)

# name=value / name: value, optionally quoted. Stops at the closing quote when
# quoted, and at whitespace, comma, or a closing bracket otherwise - so a
# traceback line does not get swallowed past the end of the value.
_ASSIGNMENT = re.compile(
    rf"""(?xi)
    (?P<prefix>["']?{_NAME}["']?\s*[:=]\s*)
    # Do not mask an existing mask. Without this, redact() is not idempotent:
    # the value pattern matches "[redacted" up to the first space and rewrites
    # it, leaving "[redacted by jittest] by jittest]". The excerpt is
    # truncated and re-quoted downstream, so this runs more than once.
    (?!\[redacted)
    # `Authorization: Bearer <token>` is handled by _BEARER, which has already
    # masked the token. Matching here as well would mask the word "Bearer"
    # itself and destroy the one clue about what kind of auth failed.
    (?!(?:Bearer|Basic|Token)\b)
    (?P<value>
        "[^"\n]*"
      | '[^'\n]*'
      | [^\s,;)\]}}\n]+
    )
    """
)

# `Authorization: Bearer <token>` and friends.
_BEARER = re.compile(r"(?i)\b(Bearer|Basic|Token)\s+([A-Za-z0-9_\-.=+/]{8,})")

# Connection strings: postgres://user:password@host. Only the password is
# masked; the host is usually the diagnostically useful part.
_URL_CREDS = re.compile(r"://([^:/@\s]+):([^@/\s]+)@")


def redact(text: str) -> str:
    """Mask credential-shaped content in captured output.

    Order matters. PEM blocks are removed first because their base64 body would
    otherwise be chewed up by the narrower patterns and left partially visible.
    """
    if not text:
        return text

    out = _PEM.sub(MASK, text)
    out = _VENDOR.sub(MASK, out)
    out = _BEARER.sub(lambda m: f"{m.group(1)} {MASK}", out)
    out = _URL_CREDS.sub(lambda m: f"://{m.group(1)}:{MASK}@", out)
    out = _ASSIGNMENT.sub(lambda m: f"{m.group('prefix')}{MASK}", out)
    return out
