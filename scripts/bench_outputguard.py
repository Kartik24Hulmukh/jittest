import concurrent.futures
import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import tracemalloc
import types

sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[1] / "src").resolve()))
from jittest import outputguard as candidate

source = subprocess.check_output(["git", "show", "a1c24533fc5e3fe24239f74847064013d100cb76:src/jittest/outputguard.py"], text=True)
baseline = types.ModuleType("jittest.outputguard_baseline")
sys.modules[baseline.__name__] = baseline
exec(compile(source, "baseline-outputguard.py", "exec"), baseline.__dict__)
rows = []
with tempfile.TemporaryDirectory() as tmp:
    root = pathlib.Path(tmp)
    payload = b"x" * (8 * 1024 * 1024)
    expected = hashlib.sha256(payload).hexdigest()
    (root / "proof").write_bytes(payload)
    del payload
    for name, module in [("baseline", baseline), ("candidate", candidate)]:
        for repeat in range(3):
            tracemalloc.start()
            start = time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                snapshots = list(
                    pool.map(lambda _, module=module: module.snapshot_tree(root), range(32))
                )
            elapsed = time.perf_counter() - start
            peak = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            assert all(
                s["proof"][0] == 8 * 1024 * 1024 and s["proof"][1].endswith(expected)
                for s in snapshots
            )
            rows.append(
                dict(
                    variant=name,
                    repeat=repeat,
                    jobs=32,
                    workers=8,
                    bytes_per_file=8 * 1024 * 1024,
                    seconds=elapsed,
                    peak_python_bytes=peak,
                )
            )
print(json.dumps(rows, indent=2))
