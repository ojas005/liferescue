# tests/security/

Security tests for the KAN-45 secret-management slice (`packages/secrets/`). Python standard library `unittest` only.

```bash
python3 -m unittest discover -s tests/security -v
```

Rules (spec section 8.1):

* **No complete realistic credential is ever committed.** Seeded canaries are generated at test runtime (`packages.secrets.testing.make_canary`: a fixed non-provider prefix plus random characters) and are valid for no provider.
* Tests prove redaction by checking for the **absence** of the canary; they never print it.
* `tests/security/fixtures/` is the single path allow-listed in the proposed `.gitleaks.toml`. This slice currently needs no fixtures; do not widen the allow-list.

## Mutation check (tests of the tests)

```bash
python3 tests/security/mutation_check.py -v
```

Copies the package and tests to a temp dir, breaks ONE guard at a time (for example removes the PRODUCTION refusal, the expiry check, or the `SecretValue` print guard), and requires the named tests to fail. A surviving mutation exits non-zero. The working tree is never modified.
