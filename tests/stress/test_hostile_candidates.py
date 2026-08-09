"""Hostile candidate safety gate and sandbox containment tests (Mission M3)."""

import unittest

from jittest.safety import check_candidate


class HostileCandidatesSafetyTests(unittest.TestCase):
    def test_socket_open_rejected(self):
        code = "import socket\ndef test_socket():\n    s = socket.socket()\n    assert s is not None"
        res = check_candidate(code)
        self.assertFalse(res.ok)
        self.assertIn("socket", res.reason)

    def test_subprocess_spawn_rejected(self):
        code = "import subprocess\ndef test_sub():\n    subprocess.Popen(['ls'])\n    assert True"
        res = check_candidate(code)
        self.assertFalse(res.ok)
        self.assertIn("subprocess", res.reason)

    def test_file_write_outside_sandbox_rejected(self):
        code = "def test_write():\n    f = open('/tmp/hacked', 'w')\n    f.write('bad')\n    assert f is not None"
        res = check_candidate(code)
        self.assertFalse(res.ok)
        self.assertIn("hard-coded path", res.reason)

    def test_fork_bomb_rejected(self):
        code = "import os\ndef test_fork():\n    os.fork()\n    assert 1 == 1"
        res = check_candidate(code)
        self.assertFalse(res.ok)
        self.assertIn("fork", res.reason)

    def test_import_smuggling_rejected(self):
        code = "def test_smuggle():\n    mod = __import__('os')\n    mod.system('ls')\n    assert 1 == 1"
        res = check_candidate(code)
        self.assertFalse(res.ok)
        self.assertIn("__import__", res.reason)

    def test_assert_true_filler_rejected(self):
        code = "def test_vacuous():\n    assert True"
        res = check_candidate(code)
        self.assertFalse(res.ok)
        self.assertIn("assert True", res.reason)

    def test_obfuscated_builtins_rejected(self):
        code = "def test_obfuscated():\n    f = eval\n    res = f('1+1')\n    assert res == 2"
        res = check_candidate(code)
        self.assertFalse(res.ok)
        self.assertIn("eval", res.reason)


if __name__ == "__main__":
    unittest.main()
