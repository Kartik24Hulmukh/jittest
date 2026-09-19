import concurrent.futures
import contextlib
import json
import os
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path

from jittest.proc import run_bounded


def main():
    before = set(threading.enumerate())
    groups = []
    with tempfile.TemporaryDirectory() as d:
        def journey(i):
            marker = Path(d) / str(i)
            code = "import os,subprocess,sys; from pathlib import Path; Path(sys.argv[1]).write_text(str(os.getpid())); subprocess.Popen([sys.executable,'-c','import threading; threading.Event().wait(30)']); print('parent exited',flush=True)"
            start = time.perf_counter()
            result = run_bounded([sys.executable, '-c', code, str(marker)], timeout=10, grace=0.01)
            groups.append(int(marker.read_text()))
            return {'rc':result.returncode,'wall_ms':(time.perf_counter()-start)*1000,'output':result.stdout}
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=100) as pool:
                results = list(pool.map(journey, range(100)))
            leaked = [t for t in threading.enumerate() if t not in before]
            report = {'journeys':100,'workers':100,'successful_returns':sum(r['rc']==0 for r in results),'owned_threads_surviving_return':len(leaked),'max_wall_ms':max(r['wall_ms'] for r in results),'results':results,'passed':not leaked}
        finally:
            for group in groups:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(group, signal.SIGKILL)
            for thread in list(threading.enumerate()):
                if thread not in before:
                    thread.join(timeout=2)
        report['threads_after_harness_cleanup'] = len(set(threading.enumerate())-before)
    result = run_bounded([sys.executable, '-c', "import sys; sys.stdout.write('x' * (16 * 1024 * 1024))"], timeout=10)
    report['captured_output_chars'] = len(result.stdout)
    Path('adversarial-repro.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k != 'results'},indent=2))
if __name__ == '__main__':
    main()
