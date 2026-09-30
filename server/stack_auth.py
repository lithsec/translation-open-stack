"""Who may use the stack, and how much.

Two ways in, either or both:

  STACK_SIGNING_KEY  short-lived signed tokens: "<payload>.<signature>", both
                     base64url, payload {"sub": "talk:<account>", "exp": <unix>}
                     and signature HMAC-SHA256(key, payload). The Lithos server
                     issues them (2 h for Lithos Talk, 12 h for Live Translation)
                     and holds the same key; the stack holds nothing a client
                     could reuse forever. A leaked token dies on its own, and
                     every connection is attributable to its subject.

                     Audience: a token says what it is for. Connection tokens
                     carry "aud": "stack"; the pod's "ready" report to the
                     Lithos server (runpod-start.sh) carries "aud": "report".
                     Both are signed with the same key, so without the claim a
                     report token (logged, sent to a URL) would also open a
                     connection. verify() for a connection accepts only "stack".
                     Tokens without "aud" (Lithos servers before this change)
                     are refused unless STACK_ACCEPT_LEGACY_TOKENS=1, a switch
                     for the transition only. A token must also expire (a finite
                     "exp") and live at most MAX_TOKEN_TTL_S (24 h).
  STACK_TOKEN        one static token, for a stack on a trusted LAN run without
                     the Lithos server (subject "static").

The token travels in an "Authorization: Bearer <token>" header. The URL path
(ws://host/<token>/translate) and ?key= still work for older clients, but a
URL gets written into proxy and server logs, so clients should not use them.

Limits, so one credential cannot crowd out a service or keep the pod from ever
idling: connections per subject (STACK_MAX_PER_CLIENT, default 30: a Live
Translation room opens one per language) and in total (STACK_MAX_CONNECTIONS,
default 60), and how long one connection may last (STACK_MAX_SESSION_MIN,
default 360).
"""
import base64
import hashlib
import hmac
import json
import math
import os
import time


def _b64d(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# Audiences: what a signed token is for.
AUD_STACK = "stack"      # open a connection to this stack
AUD_REPORT = "report"    # the pod's ready report to the Lithos server (never a connection)
# The longest a signed token may live (Live Translation's are 12 h).
MAX_TOKEN_TTL_S = 24 * 3600


def sign(key, sub, ttl_s, now=None, aud=AUD_STACK):
    """A token for `sub`, valid for ttl_s seconds (tests and tools; the Lithos server signs its own).
    aud=None leaves the audience out (the pre-audience format, for tests)."""
    now = int(now if now is not None else time.time())
    claims = {"sub": sub, "iat": now, "exp": now + ttl_s}
    if aud is not None:
        claims["aud"] = aud
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{payload}.{sig}"


def accept_legacy_tokens():
    """STACK_ACCEPT_LEGACY_TOKENS=1: also take signed tokens without an audience (transition only)."""
    return os.environ.get("STACK_ACCEPT_LEGACY_TOKENS", "0") == "1"


def _number(v):
    """v as a finite float, or None (bools, strings, NaN and infinities are not times)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


def _signed_subject(token, signing_key, now, audience, legacy):
    """(signature_ok, subject or None) for a "<payload>.<signature>" token."""
    payload, sig = token.split(".")
    want = hmac.new(signing_key.encode(), payload.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(_b64d(sig), want):
            return False, None
        claims = json.loads(_b64d(payload))
    except Exception:
        return False, None
    if not isinstance(claims, dict) or not isinstance(claims.get("sub"), str) or not claims["sub"]:
        return True, None
    exp = _number(claims.get("exp"))
    if exp is None or exp < now or exp - now > MAX_TOKEN_TTL_S:
        return True, None
    iat = claims.get("iat")
    if iat is not None:
        iat = _number(iat)
        if iat is None or exp - iat > MAX_TOKEN_TTL_S:
            return True, None
    aud = claims.get("aud")
    if aud is None:
        # A pre-audience token. Even in the transition, never a pod's report
        # (subject "pod:..."): those are the tokens the audience exists to stop.
        if not legacy or claims["sub"].startswith("pod:"):
            return True, None
    elif aud != audience:
        return True, None
    return True, claims["sub"][:80]


def verify(token, signing_key="", static_token="", now=None, audience=AUD_STACK, legacy=None):
    """The token's subject if it is valid now for `audience`, else None.

    A token that is not a valid signature under signing_key is still compared
    with the static token, so a static token containing "." keeps working when
    both credentials are configured."""
    if not token:
        return None
    now = now if now is not None else time.time()
    if legacy is None:
        legacy = accept_legacy_tokens()
    if signing_key and token.count(".") == 1:
        sig_ok, sub = _signed_subject(token, signing_key, now, audience, legacy)
        if sig_ok:
            return sub
    if static_token and hmac.compare_digest(token.encode(), static_token.encode()):
        return "static"
    return None


def presented_token(headers, path, query):
    """The token a client sent: Authorization header, else the legacy URL forms. (token, via)"""
    auth = headers.get("Authorization", "") if headers is not None else ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip(), "header"
    key = (query.get("key") or [""])[0]
    if key:
        return key, "query"
    parts = path.strip("/").split("/")
    if len(parts) >= 2:
        return parts[0], "path"
    return "", "none"


class Limits:
    """Live connections per subject and in total."""

    def __init__(self, per_client=None, total=None, session_min=None):
        env = os.environ.get
        self.per_client = per_client or int(env("STACK_MAX_PER_CLIENT", "30"))
        self.total = total or int(env("STACK_MAX_CONNECTIONS", "60"))
        self.session_s = 60 * (session_min or int(env("STACK_MAX_SESSION_MIN", "360")))
        self.live = {}

    def admit(self, sub):
        """None if admitted (call release() when done), else why not."""
        if sum(self.live.values()) >= self.total:
            return "the stack is at its connection limit"
        if self.live.get(sub, 0) >= self.per_client:
            return "too many connections for this client"
        self.live[sub] = self.live.get(sub, 0) + 1
        return None

    def release(self, sub):
        n = self.live.get(sub, 0) - 1
        if n > 0:
            self.live[sub] = n
        else:
            self.live.pop(sub, None)


def auth_required():
    return bool(os.environ.get("STACK_SIGNING_KEY") or os.environ.get("STACK_TOKEN"))


def subject_for(headers, path, query):
    """(subject, via) for a request, or (None, via) when it must be refused. Open when no credential is configured."""
    token, via = presented_token(headers, path, query)
    if not auth_required():
        return "open", via
    return verify(token, os.environ.get("STACK_SIGNING_KEY", ""), os.environ.get("STACK_TOKEN", "")), via
