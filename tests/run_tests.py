#!/usr/bin/env python3
"""Tests for qnxbuild-lint.

Run from the repository root:

    python3 tests/run_tests.py

The tests use only the synthetic fixtures in tests/fixtures/ (written
for this project).  They do NOT touch the real QNX fixture repositories
(see README.md, "Validation against real projects").

Test strategy:
  * the good-project tree must produce zero errors and zero warnings;
  * each deliberately broken fixture must produce exactly the check
    IDs listed for it;
  * CLI behaviour (exit codes, JSON output, --fail-on) is tested
    through subprocess.
"""

import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIXTURES = os.path.join(HERE, "fixtures")

sys.path.insert(0, ROOT)

import qnxbuild_lint as qbl


def check_ids_for_file(path, kind=None):
    """Run the checker on one file; return the set of check IDs found."""
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    findings = []
    if kind is None:
        kind = qbl._kind_of(path)
    roots = [os.path.dirname(os.path.abspath(path))]
    index = qbl.build_basename_index(roots)
    if kind == "build":
        qbl.check_build_file(path, text, findings, index,
                             os.path.dirname(path))
    elif kind == "make":
        qbl.check_make_file(path, text, findings, roots[0], 1)
    elif kind == "c":
        qbl.check_c_file(path, text, findings)
    return {f.check_id for f in findings}


def check_ids_for_dir(path):
    """Run the checker over a whole directory; return (ids, findings)."""
    files, roots = qbl.collect_files([path])
    index = qbl.build_basename_index(roots)
    findings = []
    for fpath, kind in files:
        rel = os.path.relpath(fpath, roots[0])
        qbl.check_path(fpath, kind, findings, index, roots[0],
                       rel.count(os.sep))
    return {f.check_id for f in findings}, findings


class TestGoodProject(unittest.TestCase):
    def test_good_project_is_clean(self):
        ids, findings = check_ids_for_dir(
            os.path.join(FIXTURES, "good-project"))
        self.assertEqual(ids, set(),
                         "good project should be clean, got: %s"
                         % [str(f) for f in findings])


class TestBuildChecks(unittest.TestCase):
    def test_unbalanced_braces(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_brackets.build"))
        self.assertEqual(ids, {"B01", "B04"})

    def test_unknown_attributes(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_attrs.build"))
        self.assertEqual(ids, {"B02"})

    def test_missing_boot_section(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_noboot.build"))
        self.assertEqual(ids, {"B03"})

    def test_missing_startup_script(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_noscript.build"))
        self.assertEqual(ids, {"B04"})

    def test_boot_without_startup_or_procnto(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_boot.build"))
        self.assertEqual(ids, {"B05", "B06"})

    def test_missing_host_files(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_paths.build"))
        self.assertEqual(ids, {"B07"})

    def test_bad_symlink(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_symlink.build"))
        self.assertEqual(ids, {"B11"})

    def test_duplicate_targets_and_bad_perms(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_dup_perms.build"))
        self.assertEqual(ids, {"B08", "B09", "B10"})

    def test_inline_script_without_shebang(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_noshebang.build"))
        self.assertEqual(ids, {"B12"})


class TestMakeChecks(unittest.TestCase):
    def test_bad_common_mk(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_common", "common.mk"))
        self.assertEqual(ids, {"M01", "M02", "M03", "M04", "M05"})

    def test_makefile_without_includes(self):
        path = os.path.join(FIXTURES, "m06", "Makefile")
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
        findings = []
        qbl.check_make_file(path, text, findings, FIXTURES, depth=1)
        self.assertEqual({f.check_id for f in findings}, {"M06"})


class TestCChecks(unittest.TestCase):
    def test_api_misuse(self):
        ids = check_ids_for_file(
            os.path.join(FIXTURES, "bad_api.c"))
        self.assertEqual(ids, {"C01", "C03", "C04", "C05", "C06"})


class TestCLI(unittest.TestCase):
    def _run(self, *argv):
        cmd = [sys.executable, os.path.join(ROOT, "qnxbuild-lint")] + list(argv)
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_good_project_exit_zero(self):
        result = self._run(os.path.join(FIXTURES, "good-project"))
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("0 error(s), 0 warning(s)", result.stdout)

    def test_bad_file_exit_one(self):
        result = self._run(os.path.join(FIXTURES, "bad_brackets.build"))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("[B01 error]", result.stdout)

    def test_json_output(self):
        result = self._run("--format", "json",
                           os.path.join(FIXTURES, "good-project"))
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["tool"], "qnxbuild-lint")
        self.assertEqual(data["summary"], {"errors": 0, "warnings": 0,
                                           "info": 0})
        self.assertEqual(data["findings"], [])

    def test_fail_on_warning(self):
        # bad_attrs.build only produces warnings (B02).
        result = self._run(os.path.join(FIXTURES, "bad_attrs.build"))
        self.assertEqual(result.returncode, 0, result.stdout)
        result = self._run("--fail-on", "warning",
                           os.path.join(FIXTURES, "bad_attrs.build"))
        self.assertEqual(result.returncode, 1, result.stdout)

    def test_missing_path_exit_two(self):
        result = self._run(os.path.join(FIXTURES, "does-not-exist"))
        self.assertEqual(result.returncode, 2)

    def test_list_checks(self):
        result = self._run("--list-checks")
        self.assertEqual(result.returncode, 0)
        self.assertIn("B01", result.stdout)
        self.assertIn("M01", result.stdout)
        self.assertIn("C01", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
