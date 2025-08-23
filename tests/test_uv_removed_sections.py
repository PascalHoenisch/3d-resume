import json
import os
import shutil
import subprocess
import sys
import unittest


class UvRemovedSectionsTest(unittest.TestCase):
    def setUp(self):
        self.repo_root = os.getcwd()
        self.resume_path = os.path.join(self.repo_root, 'resume.json')
        with open(self.resume_path, 'r', encoding='utf-8') as f:
            self._orig_resume = f.read()

    def tearDown(self):
        # Restore original resume.json
        with open(self.resume_path, 'w', encoding='utf-8') as f:
            f.write(self._orig_resume)

    def _write_resume_with_refs(self, references_value):
        data = json.loads(self._orig_resume)
        if references_value is None:
            # Remove key entirely if present
            if 'references' in data:
                del data['references']
        else:
            data['references'] = references_value
        with open(self.resume_path, 'w', encoding='utf-8') as f:
            json.dump(data, f)

    def _generate_with_uv(self):
        # Prefer uv if available; otherwise, skip test (requirement is to use uv)
        uv_path = shutil.which('uv')
        if not uv_path:
            self.skipTest('uv is not installed in this environment')
        # Use uv to run a short python -c that prints only the generated path
        code = (
            'import os, sys;'
            'sys.path.insert(0, os.path.join(os.getcwd(), "src"));'
            'from three_d_resume.server import generate_page_from_template;'
            'print(generate_page_from_template())'
        )
        proc = subprocess.run(
            [uv_path, 'run', 'python', '-c', code],
            cwd=self.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        # Find a line that looks like a generated html path
        out_lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
        # Prefer the last line which should be the printed return value
        if not out_lines:
            self.fail(f'No output from uv run; stderr=\n{proc.stderr}')
        candidate = out_lines[-1]
        # If the last line is not an existing file, try to search any line ending with .html
        if not (candidate.endswith('.html') and os.path.exists(candidate)):
            for ln in reversed(out_lines):
                if ln.endswith('.html') and os.path.exists(ln):
                    candidate = ln
                    break
        self.assertTrue(candidate.endswith('.html') and os.path.exists(candidate),
                        f'Could not determine generated page path from output. stdout=\n{proc.stdout}\nstderr=\n{proc.stderr}')
        return candidate

    def _assert_references_section_absent(self, html):
        self.assertNotIn('<section id="references"', html)
        self.assertNotIn('<h2>Referenzen</h2>', html)

    def _assert_some_other_sections_present(self, html):
        # Ensure the page still has other content (sanity)
        self.assertIn('<section id="skills"', html)
        self.assertIn('<h2>Fähigkeiten</h2>', html)

    def test_removed_references_array_results_in_no_section(self):
        # Case 1: references exists but is empty
        self._write_resume_with_refs([])
        page_path = self._generate_with_uv()
        with open(page_path, 'r', encoding='utf-8') as f:
            html = f.read()
        self._assert_references_section_absent(html)
        self._assert_some_other_sections_present(html)

    def test_missing_references_key_results_in_no_section(self):
        # Case 2: references key removed entirely
        self._write_resume_with_refs(None)
        page_path = self._generate_with_uv()
        with open(page_path, 'r', encoding='utf-8') as f:
            html = f.read()
        self._assert_references_section_absent(html)
        self._assert_some_other_sections_present(html)


if __name__ == '__main__':
    unittest.main()
