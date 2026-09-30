"""python3 -m pytest tests/test_stack_auth.py  (or just python3 tests/test_stack_auth.py)"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
import stack_auth as a  # noqa: E402

def test_signed_tokens():
    t = a.sign("k1", "talk:acct", 60, now=1000)
    assert a.verify(t, "k1", now=1030) == "talk:acct"
    assert a.verify(t, "k1", now=1061) is None            # expired
    assert a.verify(t, "k2", now=1030) is None            # wrong key
    p, s = t.split(".")
    assert a.verify(p[:-2] + "xx." + s, "k1", now=1030) is None  # tampered payload
    assert a.verify("", "k1") is None and a.verify("garbage", "k1") is None

def _forge(key, claims):
    """A correctly signed token with arbitrary claims."""
    import base64, hashlib, hmac, json
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    sig = base64.urlsafe_b64encode(hmac.new(key.encode(), payload.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{payload}.{sig}"

def test_audience():
    assert a.verify(a.sign("k1", "talk:acct", 60, now=1000), "k1", now=1030, legacy=False) == "talk:acct"
    # The pod's ready report is signed with the same key but is not a connection token.
    report = a.sign("k1", "pod:abc", 300, now=1000, aud=a.AUD_REPORT)
    assert a.verify(report, "k1", now=1030, legacy=False) is None
    assert a.verify(report, "k1", now=1030, legacy=True) is None
    assert a.verify(report, "k1", now=1030, audience=a.AUD_REPORT) == "pod:abc"
    assert a.verify(_forge("k1", {"sub": "x", "exp": 1060, "aud": ["stack"]}), "k1", now=1030) is None
    # No audience (Lithos servers before it existed): refused unless the transition switch is on.
    legacy = a.sign("k1", "talk:acct", 60, now=1000, aud=None)
    assert a.verify(legacy, "k1", now=1030, legacy=False) is None
    assert a.verify(legacy, "k1", now=1030, legacy=True) == "talk:acct"
    old_report = a.sign("k1", "pod:abc", 300, now=1000, aud=None)
    assert a.verify(old_report, "k1", now=1030, legacy=True) is None   # never a pod's report
    os.environ.pop("STACK_ACCEPT_LEGACY_TOKENS", None)
    assert a.verify(legacy, "k1", now=1030) is None                     # default: off
    os.environ["STACK_ACCEPT_LEGACY_TOKENS"] = "1"
    try:
        assert a.verify(legacy, "k1", now=1030) == "talk:acct"
    finally:
        os.environ.pop("STACK_ACCEPT_LEGACY_TOKENS", None)

def test_expiry_must_be_finite_and_bounded():
    for exp in (float("inf"), float("nan"), "9999999999", True, None):
        claims = {"sub": "x", "aud": "stack"}
        if exp is not None:
            claims["exp"] = exp
        assert a.verify(_forge("k1", claims), "k1", now=1000) is None, exp
    # (json.dumps writes inf/nan as Infinity/NaN, which json.loads reads back as floats.)
    assert a.verify(_forge("k1", {"sub": "x", "aud": "stack", "exp": 1000 + a.MAX_TOKEN_TTL_S + 60}), "k1", now=1000) is None
    assert a.verify(_forge("k1", {"sub": "x", "aud": "stack", "iat": 0, "exp": a.MAX_TOKEN_TTL_S + 10}),
                    "k1", now=a.MAX_TOKEN_TTL_S) is None    # issued for longer than the maximum
    assert a.verify(a.sign("k1", "x", 12 * 3600, now=1000), "k1", now=1000) == "x"   # Live Translation's 12 h
    assert a.verify(a.sign("k1", "x", 25 * 3600, now=1000), "k1", now=1000) is None
    assert a.verify(_forge("k1", {"sub": "", "aud": "stack", "exp": 2000}), "k1", now=1000) is None

def test_static_token_with_a_dot_and_a_signing_key():
    assert a.verify("static.token", "k1", "static.token") == "static"
    assert a.verify("other.token", "k1", "static.token") is None
    # A validly signed but expired token is not rescued by the static comparison.
    t = a.sign("k1", "x", 60, now=1000)
    assert a.verify(t, "k1", t, now=5000) is None

def test_static_token_and_open():
    assert a.verify("secret", "", "secret") == "static"
    assert a.verify("nope", "", "secret") is None
    os.environ.pop("STACK_SIGNING_KEY", None); os.environ.pop("STACK_TOKEN", None)
    assert a.subject_for({}, "/translate", {}) == ("open", "none")

def test_where_the_token_comes_from():
    assert a.presented_token({"Authorization": "Bearer abc"}, "/translate", {}) == ("abc", "header")
    assert a.presented_token({}, "/abc/translate", {}) == ("abc", "path")
    assert a.presented_token({}, "/translate", {"key": ["abc"]}) == ("abc", "query")
    assert a.presented_token({}, "/translate", {}) == ("", "none")

def test_limits():
    L = a.Limits(per_client=2, total=3, session_min=1)
    assert L.admit("a") is None and L.admit("a") is None
    assert "this client" in L.admit("a")
    assert L.admit("b") is None
    assert "limit" in L.admit("c")                          # total reached
    L.release("a"); assert L.admit("c") is None

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn(); print("ok", name)
