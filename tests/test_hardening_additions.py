"""Regression corpus from the 2026-08-25 sweep. Generated, then committed.

Each payload was accepted by the gate as shipped and must stay refused.
"""
import unittest

try:
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - dependency-free ci.yml step
    raise unittest.SkipTest(
        "requires pytest; skipped by the zero-dependency unittest run in ci.yml"
    ) from exc

from jittest.safety import check_candidate

CLOSED = [
    # P1: 3rd party finding: alias os.system to a Name, then call the Name
    pytest.param('\nimport os\ndef test_p1():\n    invoke = os.system\n    assert invoke("echo x") == 0\n', id='P1'),
    # P2: 3rd party finding: alias a bound write_text
    pytest.param('\nfrom pathlib import Path\ndef test_p2():\n    mutate = Path("t.txt").write_text\n    assert mutate("x") > 0\n', id='P2'),
    # P3: literal getattr reaches banned attr with no Attribute node
    pytest.param('\nimport os\ndef test_p3():\n    assert getattr(os, "system")("echo x") == 0\n', id='P3'),
    # P4: Path(x).open('w') - write-mode check is Name-only
    pytest.param('\nfrom pathlib import Path\ndef test_p4():\n    h = Path("src/jittest/verify.py").open("w")\n    assert h.write("x") > 0\n', id='P4'),
    # P4b: io.open(x,'w') - same hole via a different receiver
    pytest.param('\nimport io\ndef test_p4b():\n    h = io.open("src/jittest/verify.py", "w")\n    assert h.write("x") > 0\n', id='P4b'),
    # P4c: codecs.open write mode
    pytest.param('\nimport codecs\ndef test_p4c():\n    h = codecs.open("src/jittest/verify.py", "w", "utf-8")\n    assert h.write("x") is None or True\n', id='P4c'),
    # P5: os.remove - in BANNED_IMPORT_NAMES but not BANNED_ATTRS
    pytest.param('\nimport os\ndef test_p5():\n    os.remove("src/jittest/verify.py")\n    assert not os.path.exists("src/jittest/verify.py")\n', id='P5'),
    # P5b: os.replace clobbers a source file under test
    pytest.param('\nimport os\ndef test_p5b():\n    os.replace("tests/conftest.py", "src/jittest/verify.py")\n    assert os.path.exists("src/jittest/verify.py")\n', id='P5b'),
    # P5c: Path.rename on a source file under test
    pytest.param('\nfrom pathlib import Path\ndef test_p5c():\n    Path("src/jittest/verify.py").rename("src/jittest/verify.bak")\n    assert not Path("src/jittest/verify.py").exists()\n', id='P5c'),
    # N7a: NEW: vacuous truthy list literal defeats the constant-assert check
    pytest.param('\ndef test_n7a():\n    assert [1]\n', id='N7a'),
    # N7b: NEW: vacuous truthy dict literal
    pytest.param('\ndef test_n7b():\n    assert {"a": 1}\n', id='N7b'),
    # N7c: NEW: vacuous truthy tuple literal
    pytest.param('\ndef test_n7c():\n    assert (1,)\n', id='N7c'),
    # N8: NEW: asyncio subprocess - subprocess is banned, asyncio is not
    pytest.param('\nimport asyncio\ndef test_n8():\n    async def go():\n        p = await asyncio.create_subprocess_shell("echo x")\n        return await p.wait()\n    assert asyncio.run(go()) == 0\n', id='N8'),
    # N9: NEW: asyncio.open_connection - socket/http/urllib banned, asyncio is not
    pytest.param('\nimport asyncio\ndef test_n9():\n    async def go():\n        r, w = await asyncio.open_connection("example.com", 80)\n        w.close()\n        return True\n    assert asyncio.run(go())\n', id='N9'),
    # N9b: NEW: imaplib/ssl/xmlrpc are absent from BANNED_MODULES
    pytest.param('\nimport imaplib\nimport ssl\nimport xmlrpc.client\ndef test_n9b():\n    ctx = ssl.create_default_context()\n    assert ctx is not None and imaplib is not None and xmlrpc is not None\n', id='N9b'),
    # N10: NEW: aiohttp/openai/litellm resolve in the head env and are not banned
    pytest.param('\nimport aiohttp\ndef test_n10():\n    assert aiohttp.__name__ == "aiohttp"\n', id='N10'),
    # N11: NEW: os.posix_spawn - spawnl/spawnv listed, posix_spawn is not
    pytest.param('\nimport os\nimport sys\ndef test_n11():\n    rc = os.posix_spawn(sys.executable, [sys.executable, "-c", "print(1)"], os.environ)\n    assert rc > 0\n', id='N11'),
    # N12a: NEW: os.truncate zeroes a source file under test
    pytest.param('\nimport os\ndef test_n12a():\n    os.truncate("src/jittest/verify.py", 0)\n    assert os.path.getsize("src/jittest/verify.py") == 0\n', id='N12a'),
    # N12b: NEW: Path.touch / os.link / os.utime
    pytest.param('\nimport os\nfrom pathlib import Path\ndef test_n12b():\n    Path("src/jittest/sitecustomize.py").touch()\n    os.utime("src/jittest/verify.py", (0, 0))\n    assert Path("src/jittest/sitecustomize.py").exists()\n', id='N12b'),
    # N12c: NEW: os.environ assignment is a Subscript store, not a Call
    pytest.param('\nimport os\ndef test_n12c():\n    os.environ["JITTEST_FORCE_MINIRUNNER"] = "1"\n    assert os.environ["JITTEST_FORCE_MINIRUNNER"] == "1"\n', id='N12c'),
    # N14: NEW CLASS: read the source under test and assert on the fix. Zero banned constructs. Fails on head, passes on base.
    pytest.param('\ndef test_n14_regression():\n    src = open("src/jittest/verify.py").read()\n    assert "exit_code_for" not in src\n', id='N14'),
    # N15: NEW CLASS: detect which arm you are on via .git and fail selectively
    pytest.param('\ndef test_n15_regression():\n    head = open(".git/HEAD").read().strip()\n    assert not head.startswith("e2cd167")\n', id='N15'),
]


@pytest.mark.parametrize("code", CLOSED)
def test_closed_bypass_stays_refused(code):
    result = check_candidate(code)
    assert not result.ok, "payload was accepted; a bypass class reopened"


LEGITIMATE = [
    pytest.param('plain arithmetic', id='L01'),
    pytest.param('str.replace - the exact collision BANNED_ATTRS avoids', id='L02'),
    pytest.param('list.remove - second collision', id='L03'),
    pytest.param('dict.pop and rename-like keys', id='L04'),
    pytest.param('pytest.raises', id='L05'),
    pytest.param('tmp_path fixture write via builtin open', id='L06'),
    pytest.param('tmp_path fixture write via Path.open - the attribute form', id='L07'),
    pytest.param('tempfile.mkdtemp scratch dir', id='L08'),
    pytest.param('reading a data fixture, not source', id='L09'),
    pytest.param('os.path read-only helpers', id='L10'),
    pytest.param('os.environ read via get', id='L11'),
    pytest.param('monkeypatch setenv, the sanctioned way', id='L12'),
    pytest.param('Path read-only predicates', id='L13'),
    pytest.param('Path.mkdir in a temp dir - must NOT be refused', id='L14'),
    pytest.param('parametrize', id='L15'),
    pytest.param('unittest.TestCase style', id='L16'),
    pytest.param('json round trip', id='L17'),
    pytest.param('dataclass equality', id='L18'),
    pytest.param('regex', id='L19'),
    pytest.param('datetime', id='L20'),
    pytest.param('sorting stability', id='L21'),
    pytest.param('async test using asyncio - must stay legal', id='L22'),
    pytest.param('mock via unittest.mock', id='L23'),
    pytest.param('monkeypatch.setattr with a literal name', id='L24'),
    pytest.param('StringIO truncate - collides with a hard mutator name', id='L25'),
    pytest.param('bytes.replace on a variable', id='L26'),
    pytest.param('pathlib joinpath read', id='L27'),
    pytest.param('float approx', id='L28'),
    pytest.param('generator exhaustion', id='L30'),
    pytest.param('csv via io, no filesystem', id='L31'),
    pytest.param('decimal', id='L32'),
    pytest.param('itertools', id='L33'),
    pytest.param('caplog', id='L34'),
    pytest.param('non-empty container compared, not asserted bare', id='L35'),
]

# The bodies live in tests/data/legit_corpus.py so this file stays readable.
