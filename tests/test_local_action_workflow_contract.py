"""Local-action workflows may not silently pass unsupported generation inputs."""
import re
import unittest
from pathlib import Path


class LocalActionWorkflowContractTests(unittest.TestCase):
    def test_all_local_action_inputs_exist(self):
        root = Path(__file__).parents[1]
        schema = (root / 'action.yml').read_text().split('inputs:', 1)[1].split('\noutputs:', 1)[0].split('\nruns:', 1)[0]
        allowed = set(re.findall(r'^  ([\w-]+):', schema, re.M))
        errors = []
        for path in (root / '.github/workflows').glob('*.yml'):
            lines = path.read_text().splitlines()
            for i, line in enumerate(lines):
                m = re.match(r'^( *)(- )?uses: [\'"]?\./[\'"]?\s*$', line)
                if not m:
                    continue
                step_indent = len(m[1]) if m[2] else len(m[1]) - 2
                in_with = False
                for child in lines[i + 1:]:
                    if not child.strip() or child.lstrip().startswith('#'):
                        continue
                    indent = len(child) - len(child.lstrip())
                    if indent <= step_indent:
                        break
                    if child.strip() == 'with:':
                        in_with = True
                        continue
                    if in_with and indent == step_indent + 4:
                        key = child.strip().split(':', 1)[0]
                        if key not in allowed:
                            errors.append(f'{path.name}: unsupported {key}')
        self.assertFalse(errors, '\n'.join(errors))
