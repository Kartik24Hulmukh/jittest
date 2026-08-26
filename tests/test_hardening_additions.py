"""Regression corpus from the 2026-08-25 sweep. Generated, then committed.

Each payload was accepted by the gate as shipped and must stay refused.
"""
import unittest

from jittest.safety import check_candidate

CLOSED = [
    # P1: 3rd party finding: alias os.system to a Name, then call the Name
    ("P1", '\nimport os\ndef test_p1():\n    invoke = os.system\n    assert invoke("echo x") == 0\n'),
    # P2: 3rd party finding: alias a bound write_text
    ("P2", '\nfrom pathlib import Path\ndef test_p2():\n    mutate = Path("t.txt").write_text\n    assert mutate("x") > 0\n'),
    # P3: literal getattr reaches banned attr with no Attribute node
    ("P3", '\nimport os\ndef test_p3():\n    assert getattr(os, "system")("echo x") == 0\n'),
    # P4: Path(x).open('w') - write-mode check is Name-only
    ("P4", '\nfrom pathlib import Path\ndef test_p4():\n    h = Path("src/jittest/verify.py").open("w")\n    assert h.write("x") > 0\n'),
    # P4b: io.open(x,'w') - same hole via a different receiver
    ("P4b", '\nimport io\ndef test_p4b():\n    h = io.open("src/jittest/verify.py", "w")\n    assert h.write("x") > 0\n'),
    # P4c: codecs.open write mode
    ("P4c", '\nimport codecs\ndef test_p4c():\n    h = codecs.open("src/jittest/verify.py", "w", "utf-8")\n    assert h.write("x") is None or True\n'),
    # P5: os.remove - in BANNED_IMPORT_NAMES but not BANNED_ATTRS
    ("P5", '\nimport os\ndef test_p5():\n    os.remove("src/jittest/verify.py")\n    assert not os.path.exists("src/jittest/verify.py")\n'),
    # P5b: os.replace clobbers a source file under test
    ("P5b", '\nimport os\ndef test_p5b():\n    os.replace("tests/conftest.py", "src/jittest/verify.py")\n    assert os.path.exists("src/jittest/verify.py")\n'),
    # P5c: Path.rename on a source file under test
    ("P5c", '\nfrom pathlib import Path\ndef test_p5c():\n    Path("src/jittest/verify.py").rename("src/jittest/verify.bak")\n    assert not Path("src/jittest/verify.py").exists()\n'),
    # N7a: NEW: vacuous truthy list literal defeats the constant-assert check
    ("N7a", '\ndef test_n7a():\n    assert [1]\n'),
    # N7b: NEW: vacuous truthy dict literal
    ("N7b", '\ndef test_n7b():\n    assert {"a": 1}\n'),
    # N7c: NEW: vacuous truthy tuple literal
    ("N7c", '\ndef test_n7c():\n    assert (1,)\n'),
    # N8: NEW: asyncio subprocess - subprocess is banned, asyncio is not
    ("N8", '\nimport asyncio\ndef test_n8():\n    async def go():\n        p = await asyncio.create_subprocess_shell("echo x")\n        return await p.wait()\n    assert asyncio.run(go()) == 0\n'),
    # N9: NEW: asyncio.open_connection - socket/http/urllib banned, asyncio is not
    ("N9", '\nimport asyncio\ndef test_n9():\n    async def go():\n        r, w = await asyncio.open_connection("example.com", 80)\n        w.close()\n        return True\n    assert asyncio.run(go())\n'),
    # N9b: NEW: imaplib/ssl/xmlrpc are absent from BANNED_MODULES
    ("N9b", '\nimport imaplib\nimport ssl\nimport xmlrpc.client\ndef test_n9b():\n    ctx = ssl.create_default_context()\n    assert ctx is not None and imaplib is not None and xmlrpc is not None\n'),
    # N10: NEW: aiohttp/openai/litellm resolve in the head env and are not banned
    ("N10", '\nimport aiohttp\ndef test_n10():\n    assert aiohttp.__name__ == "aiohttp"\n'),
    # N11: NEW: os.posix_spawn - spawnl/spawnv listed, posix_spawn is not
    ("N11", '\nimport os\nimport sys\ndef test_n11():\n    rc = os.posix_spawn(sys.executable, [sys.executable, "-c", "print(1)"], os.environ)\n    assert rc > 0\n'),
    # N12a: NEW: os.truncate zeroes a source file under test
    ("N12a", '\nimport os\ndef test_n12a():\n    os.truncate("src/jittest/verify.py", 0)\n    assert os.path.getsize("src/jittest/verify.py") == 0\n'),
    # N12b: NEW: Path.touch / os.link / os.utime
    ("N12b", '\nimport os\nfrom pathlib import Path\ndef test_n12b():\n    Path("src/jittest/sitecustomize.py").touch()\n    os.utime("src/jittest/verify.py", (0, 0))\n    assert Path("src/jittest/sitecustomize.py").exists()\n'),
    # N12c: NEW: os.environ assignment is a Subscript store, not a Call
    ("N12c", '\nimport os\ndef test_n12c():\n    os.environ["JITTEST_FORCE_MINIRUNNER"] = "1"\n    assert os.environ["JITTEST_FORCE_MINIRUNNER"] == "1"\n'),
    # N14: NEW CLASS: read the source under test and assert on the fix. Zero banned constructs. Fails on head, passes on base.
    ("N14", '\ndef test_n14_regression():\n    src = open("src/jittest/verify.py").read()\n    assert "exit_code_for" not in src\n'),
    # N15: NEW CLASS: detect which arm you are on via .git and fail selectively
    ("N15", '\ndef test_n15_regression():\n    head = open(".git/HEAD").read().strip()\n    assert not head.startswith("e2cd167")\n'),
]


class TestHardeningAdditions(unittest.TestCase):
    def test_closed_bypass_stays_refused(self):
        for payload_id, code in CLOSED:
            with self.subTest(payload_id=payload_id):
                result = check_candidate(code)
                self.assertFalse(result.ok, f"payload {payload_id} was accepted; a bypass class reopened")


if __name__ == "__main__":
    unittest.main()
