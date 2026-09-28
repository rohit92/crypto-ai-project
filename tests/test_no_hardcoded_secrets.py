"""
Security regression test.

The API key used to be hardcoded in several modules.
It has been externalised to the GEMINI_API_KEY environment variable. This test
scans the source tree to make sure a raw key literal never sneaks back in, and
that the key is read from the environment.

Run:  python3 -m unittest tests.test_no_hardcoded_secrets
"""
import glob
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Google API keys start with "AIza" followed by 35 URL-safe chars.
GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_\-]{35}")


def _source_files():
    for path in glob.glob(os.path.join(ROOT, "*.py")):
        yield path


class TestNoHardcodedSecrets(unittest.TestCase):
    def test_no_google_api_key_literal(self):
        offenders = []
        for path in _source_files():
            with open(path, encoding="utf-8") as f:
                if GOOGLE_KEY_RE.search(f.read()):
                    offenders.append(os.path.basename(path))
        self.assertEqual(
            offenders, [],
            f"Hardcoded Google API key found in: {offenders}. "
            "Use os.environ['GEMINI_API_KEY'] instead.",
        )

    def test_key_is_read_from_environment(self):
        # Every module that talks to Gemini must read its key from the environment.
        names = [n for n in os.listdir(ROOT) if n.endswith(".py")]
        users = []
        for name in names:
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                if "genai.configure" in f.read():
                    users.append(name)
        self.assertTrue(users, "expected at least one module that configures Gemini")
        for name in users:
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                src = f.read()
            self.assertIn(
                "os.environ", src,
                f"{name} should read the API key from the environment",
            )


if __name__ == "__main__":
    unittest.main()
