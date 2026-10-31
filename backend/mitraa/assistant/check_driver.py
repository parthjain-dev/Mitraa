"""Trusted stdlib-only test entry point. Wait for the parent's resource limits."""
import importlib.util
import json
from pathlib import Path
import runpy
import sys
import unittest


def main():
    # -I -S prevents selected files/site packages from loading before this gate.
    recipe=json.loads(sys.stdin.buffer.readline(100_000))
    root=Path(recipe['root']).resolve()
    path=(root/recipe['file']).resolve()
    if not path.is_relative_to(root) or path.suffix.lower()!='.py':return 5
    sys.path.insert(0,str(root))
    sys.path.insert(0,str(path.parent))
    if recipe['kind']=='output':
        sys.argv=[str(path)]
        runpy.run_path(str(path),run_name='__main__')
        (root/'.mitraa-check-result.json').write_text(json.dumps({'completed':True,'kind':'output'}),encoding='utf-8')
        return 0
    spec=importlib.util.spec_from_file_location('mitraa_selected_test',path)
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    suite=unittest.defaultTestLoader.loadTestsFromModule(module)
    if suite.countTestCases()==0:
        print('No unittest test cases found.',file=sys.stderr)
        return 4
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    (root/'.mitraa-check-result.json').write_text(json.dumps({'completed':True,'kind':'unittest',
        'tests_run':result.testsRun,'skipped':len(result.skipped)}),encoding='utf-8')
    return 0 if result.wasSuccessful() and result.testsRun>len(result.skipped) else 1


if __name__=='__main__':
    sys.exit(main())
