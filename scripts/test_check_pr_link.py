#!/usr/bin/env python3
"""Unit tests for scripts/check_pr_link.py (KAN-20, PR <-> Jira link check).

Run from the repository root:  python3 -m unittest -v scripts/test_check_pr_link.py
Fixtures only: no network, no Jira, no GitHub. All inputs are hostile text.
"""

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "check_pr_link.py")

_spec = importlib.util.spec_from_file_location("check_pr_link", SCRIPT)
cpl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cpl)

BRANCH = "feature/KAN-20-pr-link-check"
URL = "https://liferescue.atlassian.net/browse/KAN-20"
TITLE = "feat(KAN-20): check PR links"
BODY = "Jira: " + URL + "\n\nChanges: a script."


def check(title=TITLE, body=BODY, branch=BRANCH):
    return cpl.check_pr_link(title, body, branch)


def codes(result):
    return [code for code, _text in result.problems]


class ValidInputs(unittest.TestCase):
    def test_url_in_body_and_key_in_title(self):
        r = check()
        self.assertTrue(r.ok, r.problems)
        self.assertEqual(r.key, "KAN-20")
        self.assertEqual(r.problems, ())

    def test_bare_key_in_body_is_enough(self):
        self.assertTrue(check(title="Jira link check", body="Implements KAN-20.").ok)

    def test_key_only_in_body_url(self):
        self.assertTrue(check(title="Jira link check", body=URL).ok)

    def test_other_accepted_url_forms(self):
        for body in (
            "HTTPS://LIFERESCUE.ATLASSIAN.NET/browse/KAN-20",  # scheme and host are case-insensitive
            "https://liferescue.atlassian.net:443/browse/KAN-20",
            "<https://liferescue.atlassian.net/browse/KAN-20>",
            "[KAN-20](https://liferescue.atlassian.net/browse/KAN-20).",
            "see https://liferescue.atlassian.net/jira/software/projects/KAN/boards/2?selectedIssue=KAN-20, thanks",
            "https://liferescue.atlassian.net/browse/KAN-20.",  # trailing punctuation
        ):
            with self.subTest(body=body):
                r = check(body=body)
                self.assertTrue(r.ok, r.problems)

    def test_other_keys_may_be_mentioned_next_to_the_branch_key(self):
        self.assertTrue(check(body="KAN-20 follows KAN-19 and KAN-26.").ok)
        self.assertTrue(
            check(
                body="KAN-20; not touching KAN-1 or SAM1-5 (plain text is not a link)"
            ).ok
        )

    def test_multi_line_body_and_prose_mentioning_the_project(self):
        body = "LifeRescue project.\r\nLifeRescue. Next sentence.\n\n- KAN-20\n\ttab\n"
        self.assertTrue(check(body=body).ok)

    def test_other_https_links_are_fine(self):
        body = "KAN-20 https://github.com/example-org/example-repo/pull/12 https://community.atlassian.com/x"
        self.assertTrue(check(body=body).ok)

    def test_all_branch_types(self):
        for t in ("feature", "bugfix", "security", "chore", "docs"):
            self.assertTrue(check(branch=t + "/KAN-20-x").ok, t)

    def test_large_issue_numbers(self):
        self.assertTrue(
            check(title="x", body="KAN-12345", branch="feature/KAN-12345-x").ok
        )


class MissingAndMismatchedKey(unittest.TestCase):
    def test_no_key_anywhere(self):
        r = check(title="no key", body="no key either")
        self.assertFalse(r.ok)
        self.assertIn("KEY_NOT_IN_TITLE_OR_BODY", codes(r))
        self.assertIn("BODY_LACKS_JIRA_REFERENCE", codes(r))

    def test_key_only_in_title_is_not_enough_for_the_body(self):
        r = check(title="KAN-20 x", body="no key in the body")
        self.assertFalse(r.ok)
        self.assertEqual(codes(r), ["BODY_LACKS_JIRA_REFERENCE"])

    def test_different_key(self):
        for title, body in (
            ("KAN-21 x", "KAN-21"),
            ("x", "https://liferescue.atlassian.net/browse/KAN-21"),
        ):
            with self.subTest(title=title, body=body):
                r = check(title=title, body=body)
                self.assertFalse(r.ok)
                self.assertIn("KEY_NOT_IN_TITLE_OR_BODY", codes(r))

    def test_keys_that_only_contain_the_branch_key(self):
        for text in (
            "KAN-200",
            "KAN-2",
            "KAN-2000",
            "XKAN-20",
            "KAN-20x",
            "KAN-20_1",
            "KAN-20-1",
            "KAN-020",
            "KAN--20",
            "KAN 20",
            "KAN20",
            "KAN-2 0",
            "MYKAN-20",
            "_KAN-20",
            "-KAN-20",
            "1KAN-20",
        ):
            with self.subTest(text=text):
                self.assertFalse(check(title=text, body=text).ok, text)

    def test_case_variants_do_not_count(self):
        for text in ("kan-20", "Kan-20", "kAN-20", "KaN-20"):
            with self.subTest(text=text):
                self.assertFalse(check(title=text, body=text).ok)

    def test_lowercase_or_uppercase_branch_is_invalid(self):
        for branch in (
            "feature/kan-20-x",
            "Feature/KAN-20-x",
            "FEATURE/KAN-20-x",
            "feature/KAN-20-X",
            "feature/KAN-20",
        ):
            with self.subTest(branch=branch):
                r = check(branch=branch)
                self.assertFalse(r.ok)
                self.assertIn("BRANCH_INVALID", codes(r))

    def test_unicode_lookalike_keys_do_not_count(self):
        for text in (
            "\uff2b\uff21\uff2e-20",
            "KAN-\uff12\uff10",
            "KAN\u2010 20",
            "KAN\u200b-20",
            "K\u0410N-20",
            "\u212aAN-20",
            "KAN\u2011" + "20",
            "KAN-\u0662\u0660",
        ):
            with self.subTest(text=ascii(text)):
                self.assertFalse(check(title=text, body=text).ok)

    def test_branch_key_with_other_project(self):
        for branch in ("feature/SAM1-5-x", "feature/LR-20-x", "feature/SAM-20-x"):
            self.assertFalse(check(branch=branch).ok, branch)

    def test_branch_number_leading_zero_or_zero(self):
        for branch in ("feature/KAN-020-x", "feature/KAN-0-x"):
            self.assertFalse(check(branch=branch, body="KAN-020 KAN-0").ok, branch)


class ProtectedIssues(unittest.TestCase):
    """PROPOSED ASSUMPTION - REQUIRES HUMAN APPROVAL: KAN-1..KAN-3 and SAM1 are protected."""

    def test_branch_key_kan_1_to_3_is_denied(self):
        for n in (1, 2, 3):
            with self.subTest(n=n):
                r = check(
                    title="KAN-%d x" % n,
                    body="https://liferescue.atlassian.net/browse/KAN-%d" % n,
                    branch="feature/KAN-%d-x" % n,
                )
                self.assertFalse(r.ok)
                self.assertIn("PROTECTED_ISSUE", codes(r))

    def test_kan_4_and_larger_are_not_protected(self):
        for n in (4, 10, 20, 100):
            self.assertTrue(
                check(title="x", body="KAN-%d" % n, branch="feature/KAN-%d-x" % n).ok, n
            )

    def test_jira_url_pointing_at_a_protected_issue_is_denied(self):
        for tail in (
            "browse/KAN-1",
            "browse/KAN-2",
            "browse/KAN-3",
            "browse/SAM1-7",
            "browse/SAM1-1?x=KAN-20",
        ):
            with self.subTest(tail=tail):
                r = check(body=URL + " https://liferescue.atlassian.net/" + tail)
                self.assertFalse(r.ok)
                self.assertIn("PROTECTED_ISSUE_LINK", codes(r))

    def test_protected_key_in_prose_is_not_a_link(self):
        self.assertTrue(
            check(body=BODY + "\nUnrelated to KAN-1, KAN-2, KAN-3 and SAM1-1.").ok
        )

    def test_look_alikes_of_protected_numbers(self):
        # KAN-10 .. KAN-30 contain the digits but are different issues
        for n in (10, 11, 12, 13, 21, 30, 31, 32, 33):
            self.assertTrue(
                check(title="x", body="KAN-%d" % n, branch="feature/KAN-%d-x" % n).ok, n
            )


LOOKALIKE_BODIES = (
    "https://liferescue.atlassian.net.evil.com/browse/KAN-20",
    "https://evil.com/liferescue.atlassian.net/browse/KAN-20",
    "https://evil.com/browse/KAN-20?u=liferescue.atlassian.net",
    "https://evil.com/#liferescue.atlassian.net",
    "https://liferescue-atlassian.net/browse/KAN-20",
    "https://liferescue.atlassian.net.evil.com./browse/KAN-20",
    "https://evil.liferescue.atlassian.net/browse/KAN-20",
    "https://www.liferescue.atlassian.net/browse/KAN-20",
    "https://liferescue.atlassian.net/../x.evil.com",  # tail contains the host only: still exact host, see below
    "https://lifere5cue.atlassian.net/browse/KAN-20",
    "https://other.atlassian.net/browse/KAN-20",
    "https://atlassian.net/browse/KAN-20",
    "https://liferescue.atlassian.com/browse/KAN-20",
    "https://liferescue.atlassian.net@evil.com/browse/KAN-20",
    "https://liferescue.atlassian.net:pass@evil.com/browse/KAN-20",
    "https://evil.com\\@liferescue.atlassian.net/browse/KAN-20",
    "https://liferescue.atlassian.net\\@evil.com/browse/KAN-20",
    "https://user:pass@liferescue.atlassian.net/browse/KAN-20",
    "https://user@liferescue.atlassian.net/browse/KAN-20",
    "http://liferescue.atlassian.net/browse/KAN-20",
    "ftp://liferescue.atlassian.net/browse/KAN-20",
    "https://liferescue.atlassian.net:8443/browse/KAN-20",
    "https://liferescue.atlassian.net:/browse/KAN-20",
    "https://liferescue.atlassian.net.\u200b/browse/KAN-20",
    "https://liferescue.atlassian.net\u200b/browse/KAN-20",
    "https://l\u0456ferescue.atlassian.net/browse/KAN-20",  # Cyrillic i
    "https://liferescue.\u0430tlassian.net/browse/KAN-20",  # Cyrillic a
    "https://xn--liferescue-atlassian-3ob.net/browse/KAN-20",  # punycode
    "https://xn--lferescue-hhb.atlassian.net/browse/KAN-20",
    "https://\uff4cife\uff52escue.atlassian.net/browse/KAN-20",  # full-width letters
    "https://liferescue.atlassian\u3002net/browse/KAN-20",  # ideographic full stop
    "https://liferescue\uff0eatlassian.net/browse/KAN-20",  # full-width full stop
    "https://[liferescue.atlassian.net]/browse/KAN-20",
    "liferescue.atlassian.net.evil.com/browse/KAN-20",  # scheme-less look-alike
    "see liferescue-atlassian.net/browse/KAN-20 KAN-20",
)


class LookalikeHosts(unittest.TestCase):
    def test_lookalikes_are_denied(self):
        for body in LOOKALIKE_BODIES:
            if body == "https://liferescue.atlassian.net/../x.evil.com":
                continue  # exact host: accepted form, tested separately
            with self.subTest(body=ascii(body)):
                r = check(body=body)
                self.assertFalse(r.ok, r.problems)

    def test_lookalike_next_to_a_good_link_still_denies(self):
        for bad in LOOKALIKE_BODIES[:8]:
            with self.subTest(bad=bad):
                self.assertFalse(check(body=BODY + "\n" + bad).ok)

    def test_lookalike_in_the_title_denies(self):
        for bad in LOOKALIKE_BODIES[:8]:
            with self.subTest(bad=bad):
                self.assertFalse(check(title="KAN-20 " + bad).ok)

    def test_specific_reason_codes(self):
        self.assertIn(
            "LOOKALIKE_HOST",
            codes(
                check(body="https://liferescue.atlassian.net.evil.com/browse/KAN-20")
            ),
        )
        self.assertIn(
            "LOOKALIKE_HOST",
            codes(
                check(body="https://evil.com/liferescue.atlassian.net/browse/KAN-20")
            ),
        )
        self.assertIn(
            "USERINFO_IN_URL",
            codes(
                check(body="https://user:pass@liferescue.atlassian.net/browse/KAN-20")
            ),
        )
        self.assertIn(
            "NON_HTTPS_JIRA_URL",
            codes(check(body="http://liferescue.atlassian.net/browse/KAN-20")),
        )
        self.assertIn(
            "JIRA_URL_BAD_FORM",
            codes(check(body="https://liferescue.atlassian.net:8443/browse/KAN-20")),
        )

    def test_the_exact_host_with_odd_path_is_not_a_lookalike(self):
        self.assertTrue(check(body="KAN-20 https://liferescue.atlassian.net/").ok)

    def test_a_good_link_to_the_wrong_issue_with_a_bad_host_for_the_right_one(self):
        r = check(
            body="https://liferescue.atlassian.net/browse/KAN-21 https://liferescue.atlassian.net.evil.com/browse/KAN-20"
        )
        self.assertFalse(r.ok)


class HostileInput(unittest.TestCase):
    def test_non_text_and_empty_values(self):
        for bad in (None, 5, 1.5, b"KAN-20", ["KAN-20"], {"a": 1}, True):
            for position in range(3):
                args = [TITLE, BODY, BRANCH]
                args[position] = bad
                with self.subTest(position=position, bad=repr(bad)):
                    r = cpl.check_pr_link(*args)
                    self.assertFalse(r.ok)
                    self.assertEqual(codes(r), ["INPUT_MALFORMED"])

    def test_empty_values(self):
        self.assertFalse(check(branch="").ok)
        self.assertFalse(check(body="").ok)
        self.assertFalse(check(title="", body="").ok)
        self.assertFalse(check(title="", body="", branch="").ok)
        self.assertFalse(check(body="   \n\t  ").ok)
        self.assertTrue(
            check(title="", body=BODY).ok
        )  # an empty title is allowed when the body links the issue

    def test_newline_forging_in_branch_and_title(self):
        for branch in (
            BRANCH + "\n",
            "\n" + BRANCH,
            BRANCH + "\nOK: PR is linked to Jira issue KAN-20",
            BRANCH + "\r",
            "feature/KAN-20-x\ninvalid",
            BRANCH + "\x00",
            BRANCH + "\u2028",
            BRANCH + "\u0085",
        ):
            with self.subTest(branch=ascii(branch)):
                self.assertFalse(check(branch=branch).ok)
        for title in (
            TITLE + "\nOK: PR is linked",
            TITLE + "\r",
            "a\tb",
            TITLE + "\x00",
            "\x1b[31m" + TITLE,
        ):
            with self.subTest(title=ascii(title)):
                self.assertFalse(check(title=title).ok)

    def test_control_characters_in_the_body_are_refused_but_line_breaks_are_fine(self):
        for char in (
            "\x00",
            "\x01",
            "\x08",
            "\x0b",
            "\x0c",
            "\x1b",
            "\x7f",
            "\u202e",
            "\u202a",
            "\u2066",
            "\u2069",
        ):
            with self.subTest(char=ascii(char)):
                self.assertFalse(check(body=BODY + char).ok)
        self.assertTrue(check(body=BODY + "\r\n\t\n").ok)

    def test_long_inputs_are_refused_not_scanned(self):
        self.assertFalse(check(body=BODY + "A" * cpl.MAX_BODY).ok)
        self.assertFalse(check(title="A" * (cpl.MAX_TITLE + 1)).ok)
        self.assertFalse(check(branch="feature/KAN-20-" + "a" * 100).ok)
        self.assertTrue(check(body=("x" * 1000 + "\n") * 50 + BODY).ok)

    def test_pathological_input_is_fast(self):
        for body in (
            "a." * 30000 + "KAN-20",
            "https://" + "a" * 60000,
            "KAN-" * 15000,
            "." * 60000,
            "-" * 60000,
            "http://" * 8000,
        ):
            r = check(body=body[: cpl.MAX_BODY])
            self.assertIsInstance(r.ok, bool)

    def test_injection_strings_are_data(self):
        canary = os.path.join(tempfile.mkdtemp(), "canary")
        payloads = [
            "$(touch %s)" % canary,
            "`touch %s`" % canary,
            "; touch %s" % canary,
            "__import__('os').system('touch %s')" % canary,
            "{{7*7}}",
            "${jndi:ldap://x/a}",
            "<script>alert(1)</script>",
            "'; DROP TABLE x; --",
            "../../etc/passwd",
            "--help",
            "-h",
            "::set-output name=x::y",
            "::error::boom",
            "%s%s%n",
        ]
        for p in payloads:
            with self.subTest(payload=p):
                check(title=p, body=p + "\nKAN-20", branch=BRANCH)
                check(title=TITLE, body=BODY, branch=p)
        self.assertFalse(os.path.exists(canary))

    def test_unicode_and_homoglyph_noise_does_not_crash(self):
        noise = "\u202e\u200b\u200d\ufeff\U0001f600\u0301\ud7ff \uff0f" * 50
        r = check(title=noise, body=noise + "KAN-20")
        self.assertIsInstance(r.ok, bool)

    def test_unpaired_surrogates_do_not_crash(self):
        r = check(title="\ud800", body="\udc00 KAN-20", branch=BRANCH)
        self.assertIsInstance(r.ok, bool)

    def test_result_never_contains_input_text(self):
        secret = "token-" + uuid.uuid4().hex
        r = check(
            title="KAN-20 " + secret,
            body=secret + " https://evil.com/liferescue.atlassian.net",
            branch="feature/KAN-20-x\n" + secret,
        )
        self.assertNotIn(secret, repr(r.problems))  # reasons are fixed texts
        self.assertEqual(
            r.branch_note, cpl.escaped("feature/KAN-20-x\n" + secret)
        )  # the only echo: escaped branch

    def test_branch_validator_unavailable_fails_closed(self):
        original = cpl.BRANCH_VALIDATOR_PATH
        cpl._BRANCH_MODULE = None
        try:
            cpl.BRANCH_VALIDATOR_PATH = "/nonexistent/check-branch-name.py"
            r = check()
            self.assertFalse(r.ok)
            self.assertIn("BRANCH_VALIDATOR_UNAVAILABLE", codes(r))
        finally:
            cpl.BRANCH_VALIDATOR_PATH = original
            cpl._BRANCH_MODULE = None
        self.assertTrue(check().ok)

    def test_unexpected_exception_is_a_denial(self):
        original = cpl._check

        def boom(*_a):
            raise RuntimeError("boom")

        cpl._check = boom
        try:
            r = check()
        finally:
            cpl._check = original
        self.assertFalse(r.ok)
        self.assertEqual(codes(r), ["INPUT_MALFORMED"])


def run_main(environ, argv=()):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cpl.main(list(argv), environ)
    return code, out.getvalue(), err.getvalue()


def good_env():
    return {"PR_TITLE": TITLE, "PR_BODY": BODY, "PR_BRANCH": BRANCH}


class CommandLineContract(unittest.TestCase):
    def test_ok(self):
        code, out, err = run_main(good_env())
        self.assertEqual(
            (code, out, err), (0, "OK: PR is linked to Jira issue KAN-20\n", "")
        )

    def test_invalid_exit_1_with_fixed_codes_on_stderr(self):
        env = good_env()
        env["PR_BODY"] = "nothing"
        code, out, err = run_main(env)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("INVALID BODY_LACKS_JIRA_REFERENCE:", err)
        for line in err.splitlines():
            self.assertTrue(line.startswith("INVALID "), line)

    def test_every_documented_code_has_fixed_text(self):
        self.assertEqual(
            set(cpl.CODES),
            {
                "INPUT_MALFORMED",
                "BRANCH_INVALID",
                "BRANCH_VALIDATOR_UNAVAILABLE",
                "PROTECTED_ISSUE",
                "PROTECTED_ISSUE_LINK",
                "KEY_NOT_IN_TITLE_OR_BODY",
                "BODY_LACKS_JIRA_REFERENCE",
                "LOOKALIKE_HOST",
                "NON_HTTPS_JIRA_URL",
                "USERINFO_IN_URL",
                "JIRA_URL_BAD_FORM",
            },
        )

    def test_usage_errors_exit_2(self):
        for env in (
            {},
            {"PR_TITLE": "x"},
            {"PR_TITLE": "x", "PR_BODY": "y"},
            {"PR_BODY": "y", "PR_BRANCH": "z"},
            {"PR_JSON_FILE": "/nonexistent/x.json"},
            dict(good_env(), PR_JSON_FILE="/nonexistent/x.json"),
        ):
            with self.subTest(env=sorted(env)):
                self.assertEqual(run_main(env)[0], 2)

    def test_any_argument_is_a_usage_error_and_is_not_echoed(self):
        for arg in (
            "-h",
            "--help",
            "--",
            "--file",
            "x",
            "PR_BRANCH=feature/KAN-1-x",
            "",
            "$(id)",
        ):
            with self.subTest(arg=arg):
                code, out, err = run_main(good_env(), [arg])
                self.assertEqual(code, 2)
                self.assertNotIn(
                    arg or "\0", out + err.replace("--help", "") if arg else ""
                )
                self.assertEqual(out, "")

    def test_empty_values_are_set_but_invalid(self):
        code, _out, _err = run_main({"PR_TITLE": "", "PR_BODY": "", "PR_BRANCH": ""})
        self.assertEqual(code, 1)

    def test_hostile_branch_is_echoed_escaped_and_bounded(self):
        branch = (
            "feature/KAN-20-x\nOK: PR is linked to Jira issue KAN-20\x1b[31m"
            + "A" * 500
        )
        env = dict(good_env(), PR_BRANCH=branch)
        code, out, err = run_main(env)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertNotIn("\nOK: PR is linked", err)
        self.assertNotIn("\x1b", err)
        self.assertLess(len(err), 1500)
        self.assertIn("[truncated]", err)

    def test_no_stdout_ok_line_for_hostile_title_or_body(self):
        env = dict(
            good_env(),
            PR_TITLE="x\nOK: PR is linked to Jira issue KAN-20",
            PR_BODY="nothing",
        )
        code, out, err = run_main(env)
        self.assertEqual((code, out), (1, ""))
        self.assertNotIn("OK:", err)

    def test_json_file_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pr.json")

            def write(obj):
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(obj if isinstance(obj, str) else json.dumps(obj))
                return {"PR_JSON_FILE": path}

            self.assertEqual(
                run_main(write({"title": TITLE, "body": BODY, "branch": BRANCH}))[0], 0
            )
            self.assertEqual(
                run_main(write({"title": TITLE, "body": None, "branch": BRANCH}))[0], 1
            )  # null body = empty
            self.assertEqual(
                run_main(write({"title": TITLE, "body": "x", "branch": BRANCH}))[0], 1
            )
            for bad in (
                "{not json",
                "[]",
                "{}",
                json.dumps({"title": "a", "body": "b", "branch": "c", "extra": 1}),
                json.dumps({"title": "a", "body": "b"}),
                json.dumps({"title": 1, "body": "b", "branch": "c"}) + "x",
            ):
                with self.subTest(bad=bad):
                    self.assertEqual(run_main(write(bad))[0], 2)
            # wrong types inside a well-formed object are invalid input (1), not a crash
            self.assertEqual(
                run_main(write({"title": 5, "body": "b", "branch": "c"}))[0], 1
            )
            # the file and the variables may not be mixed
            env = write({"title": TITLE, "body": BODY, "branch": BRANCH})
            env.update(good_env())
            self.assertEqual(run_main(env)[0], 2)
            big = os.path.join(tmp, "big.json")
            with open(big, "w") as fh:
                fh.write(" " * (cpl.MAX_FILE_BYTES + 1))
            self.assertEqual(run_main({"PR_JSON_FILE": big})[0], 2)

    def test_real_process_exit_codes_and_no_option_parsing(self):
        def run(env_extra, args=()):
            env = {"PATH": os.environ.get("PATH", ""), "HOME": tempfile.gettempdir()}
            env.update(env_extra)
            return subprocess.run(
                [sys.executable, SCRIPT] + list(args),
                capture_output=True,
                text=True,
                env=env,
                cwd=tempfile.gettempdir(),
            )

        r = run(good_env())
        self.assertEqual(
            (r.returncode, r.stdout.strip()),
            (0, "OK: PR is linked to Jira issue KAN-20"),
        )
        r = run(dict(good_env(), PR_BODY="none"))
        self.assertEqual(r.returncode, 1)
        r = run({})
        self.assertEqual(r.returncode, 2)
        r = run(good_env(), ["--help"])
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("usage:", r.stdout + r.stderr.lower())
        # values that look like options or shell syntax are only data
        r = run(
            {
                "PR_TITLE": "--help",
                "PR_BODY": "-h $(id) KAN-20",
                "PR_BRANCH": "feature/KAN-20-x",
            }
        )
        self.assertEqual(r.returncode, 0)

    def test_other_environment_variables_are_not_read_or_printed(self):
        canary = "KAN20_CANARY_" + uuid.uuid4().hex
        env = dict(good_env(), PR_BODY="none")
        env["SOME_OTHER_VAR"] = canary
        code, out, err = run_main(env)
        self.assertNotIn(canary, out + err)


class StaticProperties(unittest.TestCase):
    def test_no_shell_network_eval_or_option_parsing(self):
        with open(SCRIPT, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "subprocess",
            "os.system",
            "socket",
            "urllib.request",
            "http.client",
            "eval(",
            "exec(",
            "__import__",
            "argparse",
            "getopt",
            "optparse",
            "os.popen",
            "shell=True",
        ):
            self.assertNotIn(forbidden, source, forbidden)

    def test_python_38_compatible_syntax(self):
        with open(SCRIPT, encoding="utf-8") as fh:
            source = fh.read()
        for forbidden in (
            "match ",
            "removeprefix",
            "removesuffix",
            " | None",
            "list[",
            "dict[",
            "tuple[",
        ):
            if forbidden == "match ":
                self.assertNotRegex(source, r"(?m)^\s*match\s+\w+:\s*$")
            else:
                self.assertNotIn(forbidden, source, forbidden)


# ---------------------------------------------------------------------------------------------
# mutation checks: guard tests must FAIL when the guard is removed
# ---------------------------------------------------------------------------------------------

PROTECTED_GUARD = "    if number in PROTECTED_KAN_NUMBERS:\n"
LOOKALIKE_GUARD = '            if "liferescue" in host_l or "atlassian.net" in host_l or mentions_jira_in_tail:\n'
KEY_GUARD = "    if not (in_title or in_body or title_urls or body_urls):\n"
BODY_GUARD = "    if not (in_body or body_urls):\n"
HOSTLIKE_GUARD = (
    "        if token == JIRA_HOST:\n            continue  # HOSTLIKE_GUARD\n"
)
USERINFO_GUARD = '        if "@" in rawnet:\n'


def load_mutant(replacements):
    with open(SCRIPT, encoding="utf-8") as fh:
        source = fh.read()
    for old, new in replacements:
        if source.count(old) != 1:
            raise AssertionError("mutation target not found exactly once: %r" % old)
        source = source.replace(old, new)
    module = types.ModuleType("check_pr_link_mutant")
    module.__file__ = SCRIPT
    exec(compile(source, SCRIPT, "exec"), module.__dict__)
    return module


def guard_protected(test, m):
    test.assertFalse(m.check_pr_link("KAN-1", "KAN-1", "feature/KAN-1-x").ok)


def guard_lookalike(test, m):
    # only the URL scan catches a Jira host name inside another URL's path
    test.assertFalse(
        m.check_pr_link(
            TITLE,
            "KAN-20 https://evil.com/liferescue.atlassian.net/browse/KAN-20",
            BRANCH,
        ).ok
    )
    test.assertFalse(
        m.check_pr_link(
            TITLE,
            "KAN-20 https://liferescue.atlassian.net.evil.com/browse/KAN-20",
            BRANCH,
        ).ok
    )


def guard_hostlike(test, m):
    # a scheme-less look-alike is caught only by the host-like token scan
    test.assertFalse(
        m.check_pr_link(
            TITLE, "KAN-20 see liferescue.atlassian.net.evil.com/browse/KAN-20", BRANCH
        ).ok
    )


def guard_key(test, m):
    r = m.check_pr_link("x", "https://liferescue.atlassian.net/browse/KAN-21", BRANCH)
    test.assertFalse(r.ok)
    test.assertIn("KEY_NOT_IN_TITLE_OR_BODY", [c for c, _t in r.problems])


def guard_body(test, m):
    test.assertFalse(m.check_pr_link("KAN-20", "no key in the body", BRANCH).ok)


def guard_userinfo(test, m):
    test.assertFalse(
        m.check_pr_link(
            TITLE, "https://user:pass@liferescue.atlassian.net/browse/KAN-20", BRANCH
        ).ok
    )


class MutationChecks(unittest.TestCase):
    def test_unmutated_module_passes_every_guard_test(self):
        for guard in (
            guard_protected,
            guard_lookalike,
            guard_hostlike,
            guard_key,
            guard_body,
            guard_userinfo,
        ):
            guard(self, cpl)

    def test_removing_the_protected_issue_guard_is_caught(self):
        with self.assertRaises(AssertionError):
            guard_protected(self, load_mutant([(PROTECTED_GUARD, "    if False:\n")]))

    def test_removing_the_lookalike_host_guard_is_caught(self):
        with self.assertRaises(AssertionError):
            guard_lookalike(
                self, load_mutant([(LOOKALIKE_GUARD, "            if False:\n")])
            )

    def test_removing_the_scheme_less_lookalike_scan_is_caught(self):
        mutant = load_mutant(
            [(HOSTLIKE_GUARD, "        if True:\n            continue\n")]
        )
        with self.assertRaises(AssertionError):
            guard_hostlike(self, mutant)

    def test_removing_the_key_match_guard_is_caught(self):
        with self.assertRaises(AssertionError):
            guard_key(self, load_mutant([(KEY_GUARD, "    if False:\n")]))

    def test_removing_the_body_reference_guard_is_caught(self):
        with self.assertRaises(AssertionError):
            guard_body(self, load_mutant([(BODY_GUARD, "    if False:\n")]))

    def test_removing_the_userinfo_guard_is_caught(self):
        with self.assertRaises(AssertionError):
            guard_userinfo(self, load_mutant([(USERINFO_GUARD, "        if False:\n")]))

    def test_harness_rejects_a_stale_target(self):
        with self.assertRaises(AssertionError):
            load_mutant([("this text is not in the script", "x")])


if __name__ == "__main__":
    unittest.main()
