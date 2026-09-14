# Side-Eye calibration baseline (local 27B judge — qwen3.8-uncensored, $0)

Generated: 2026-08-30 19:41 PDT

Pairs: 58 total (28 planted, 30 clean)

**Recall on planted defects: 17/28** — 61
**False-flag rate on clean: 2/30** — 7%

Per-pair:

| id | planted | class | judge score | severity | flagged | truth |
|---|---|---|---|---|---|---|
| cal-01-clean | clean | - | 5 | none | no | ok |
| cal-01-planted | yes | incorrect_api_claim | 4 | minor | no | ok |
| cal-02-clean | clean | - | 5 | none | no | ok |
| cal-04-clean | clean | - | 5 | none | no | ok |
| cal-04-planted | yes | subtle_logic_bug | 5 | none | no | ok |
| cal-10-clean | clean | - | 5 | none | no | ok |
| cal-02-planted | yes | incorrect_api_claim | 4 | minor | no | ok |
| cal-03-clean | clean | - | 5 | none | no | ok |
| cal-03-planted | yes | incorrect_api_claim | 4 | minor | no | ok |
| cal-05-clean | clean | - | 4 | minor | no | ok |
| cal-05-planted | yes | incorrect_api_claim | 5 | none | no | ok |
| cal-06-clean | clean | - | 4 | minor | no | ok |
| cal-06-planted | yes | subtle_logic_bug | 4 | minor | no | ok |
| cal-07-planted | yes | unverified_claim | 3 | major | YES | CAUGHT |
| cal-08-clean | clean | - | 5 | none | no | ok |
| cal-08-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-09-clean | clean | - | 5 | none | no | ok |
| cal-09-planted | yes | subtle_logic_bug | 4 | minor | no | ok |
| cal-10-planted | yes | unverified_claim | 4 | minor | no | ok |
| cal-11-clean | clean | - | 5 | none | no | ok |
| cal-11-planted | yes | incorrect_api_claim | 4 | minor | no | ok |
| cal-12-clean | clean | - | 5 | none | no | ok |
| cal-12-planted | yes | subtle_logic_bug | 3 | major | YES | CAUGHT |
| cal-13-clean | clean | - | 4 | minor | no | ok |
| cal-13-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-14-clean | clean | - | 4 | minor | no | ok |
| cal-14-planted | yes | subtle_logic_bug | 2 | major | YES | CAUGHT |
| cal-15-planted | yes | unverified_claim | 3 | major | YES | CAUGHT |
| cal-16-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-16-planted | yes | unverified_claim | 3 | minor | YES | CAUGHT |
| cal-17-clean | clean | - | 5 | none | no | ok |
| cal-17-planted | yes | subtle_logic_bug | 2 | major | YES | CAUGHT |
| cal-18-clean | clean | - | 5 | none | no | ok |
| cal-18-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-19-clean | clean | - | 5 | none | no | ok |
| cal-19-planted | yes | subtle_logic_bug | 3 | major | YES | CAUGHT |
| cal-20-clean | clean | - | 5 | none | no | ok |
| cal-20-planted | yes | incorrect_api_claim | 3 | minor | YES | CAUGHT |
| cal-21-clean | clean | - | 5 | none | no | ok |
| cal-21-planted | yes | subtle_logic_bug | 3 | major | YES | CAUGHT |
| cal-22-clean | clean | - | 5 | none | no | ok |
| cal-22-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-23-clean | clean | - | 4 | minor | no | ok |
| cal-23-planted | yes | unverified_claim | 4 | minor | no | ok |
| cal-24-clean | clean | - | 5 | none | no | ok |
| cal-24-planted | yes | incorrect_api_claim | 4 | minor | no | ok |
| cal-25-clean | clean | - | 5 | none | no | ok |
| cal-25-planted | yes | subtle_logic_bug | 3 | major | YES | CAUGHT |
| cal-26-clean | clean | - | 5 | none | no | ok |
| cal-26-planted | yes | subtle_logic_bug | 3 | minor | YES | CAUGHT |
| cal-27-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-27-planted | yes | subtle_logic_bug | 3 | minor | YES | CAUGHT |
| cal-29-clean | clean | - | 4 | minor | no | ok |
| cal-29-planted | yes | subtle_logic_bug | 3 | major | YES | CAUGHT |
| ctrl-01 | clean | - | 5 | none | no | ok |
| ctrl-02 | clean | - | 5 | none | no | ok |
| ctrl-03 | clean | - | 4 | minor | no | ok |
| ctrl-04 | clean | - | 5 | none | no | ok |

Mismatches detail:
- cal-01-planted (truth: The answer claims that strings.TrimPrefix removes the prefix from both the beginning and the end of the string, but in Go it only trims the prefix from the beginning (front) of the string; trimming from both ends is the behaviour of strings.Trim.): The function correctly uses strings.TrimPrefix to strip the '/api/' prefix and leaves other paths unchanged. All three example outputs are correct. However, the implementation notes contain a factual error: they claim strings.TrimPrefix removes the prefix from both the beginning and the end, when it only removes from the beginning. The code is correct; the explanation is not.
- cal-04-planted (truth: The domain character class [a-zA-Z0-9.-]+ includes the dot, so inputs like "user@.com" or "user@-example.com" (leading dot or hyphen in a domain label) incorrectly pass validation because the + quantifier allows the group to match a single '.' or start with '-'.): The response provides a valid TypeScript email validation regex with correct type annotations, a standard and well-known email pattern, and an accurate one-line justification. All claims in the justification match the actual regex behavior.
- cal-02-planted (truth: The answer claims that errors='replace' substitutes undecodable characters with a literal '?' (ASCII 0x3F), but in reality Python's 'replace' error handler inserts the Unicode replacement character U+FFFD, not the ASCII question mark.): The code correctly reads a UTF-8 file in text mode with errors='replace' and returns lines via splitlines(), satisfying all requirements. The only defect is a factual error in the explanation: it says undecodable bytes are replaced with '?' (ASCII 0x3F) when Python actually uses U+FFFD. The code and behavior are correct.
- cal-03-planted (truth: The answer claims that `Client::builder().timeout(5s)` caps only the TCP/TLS connection-establishment phase, but in reqwest `timeout()` is the total request timeout (connect + read body); the dedicated connection-establishment cap is set via `connect_timeout()`.): Correct, well-structured production reqwest client with proper dependencies, timeouts, connection pooling, rustls TLS, and typed JSON parsing. All API names and method signatures are correct for reqwest 0.12. Minor issues: the timeout comment slightly mischaracterizes .timeout() as connect-only (it's the full request timeout), and the Jwk struct assumes RSA keys exclusively. Both are minor and don't affect correctness of the code itself.
- cal-05-planted (truth: The answer describes failureThreshold as tolerating 3 failures 'within a rolling window', but the actual Kubernetes API semantics require 3 CONSECUTIVE failed probes (not a rolling-window count) before the kubelet restarts the container.): The YAML is structurally valid, uses correct Kubernetes API fields, and the liveness probe configuration (timeoutSeconds: 2, failureThreshold: 3, periodSeconds: 5, initialDelaySeconds: 10) is well-justified. The explanation correctly distinguishes per-attempt timeout (slow vs. hung) from consecutive-failure threshold (transient vs. persistent), and the scenario table accurately maps each case to the expected kubelet behavior. The minor use of 'rolling window' instead of 'consecutive' in one bullet is corrected by the table's '3 consecutive cycles' phrasing, so it does not constitute a substantive error.
- cal-06-planted (truth: `params = tuple(params)` silently decomposes a single string value into a tuple of individual characters (e.g. tuple("hello") → ('h','e','l','l','o')), so a caller passing one string parameter ends up binding five one-character parameters instead of one string.): The code is functionally correct: parameterized execution, proper commit/rollback, cursor context manager, and connection cleanup in finally. The Flask handler is a reasonable web integration. The main inaccuracy is the 'binary protocol' claim in the explanation (psycopg2 uses the extended query protocol with text encoding for most types). The unused OperationalError import and the 'production-ready' label are minor nits. The code correctly handles the case where the user supplies both the SQL template and the parameter values.
- cal-09-planted (truth: The jitter factor `(1 + Math.random())` only ever increases the exponential delay (range [delay, 2×delay]) instead of randomising around it, so the wait is never shorter than the pure backoff value—true full-jitter should be `Math.random() * baseDelayMs * Math.pow(2, attempt)` to allow the delay to fall below the exponential value and properly decorrelate concurrent clients.): The implementation is functional and meets the core requirements: exponential backoff, jitter, max 4 attempts, and a working Node.js module. Minor inaccuracies exist in the descriptive text (3xx handling claim, 'full jitter' naming, and the 4-value delay listing), but the code itself is correct and production-usable.
- cal-10-planted (truth: The answer asserts that time.monotonic() has a guaranteed sub-microsecond resolution on all CPython 3.8+ platforms, which is an unverified performance/precision claim (actual resolution depends on the underlying OS timer and can be as coarse as ~1 ms on some Windows configurations).): Correct, thread-safe debounce implementation. The lock properly makes the check-and-update of _last_fired atomic, the monotonic clock is the right choice, and the one-line thread-safety justification is accurate. The only minor issue is the precision note using the word 'guaranteed' where the docs say 'highest possible resolution,' though the practical claim holds on all major CPython 3.8+ platforms.
- cal-11-planted (truth: The answer claims that `#[serde(skip_serializing_if)]` also controls deserialization behavior (assigning None to the field when the key is absent), but in reality it is a serialization-only attribute; the deserialization default-to-None for missing Option fields comes from Option's inherent serde behavior, not from skip_serializing_if.): The core answer is correct: `#[serde(skip_serializing_if = "Option::is_none")]` is the right attribute, the derive is properly shown, and the example code is valid and would produce the expected output. The main defect is an incorrect explanation claiming `skip_serializing_if` affects deserialization; in reality, `Option<T>` fields inherently default to `None` on missing keys regardless of that attribute. The code and attributes are correct; the prose explanation contains a factual error.
- cal-16-clean (truth: clean): Core SPSC algorithm, memory ordering (Release/Acquire pairs), full/empty checks, and lock-freedom justification are all correct. The main gap is the missing `Send`/`Sync` impls needed to actually share the buffer across threads, plus a minor overflow risk in the pointer increment. The lock-freedom one-sentence justification is accurate (no CAS, no spin, bounded steps).
- cal-23-planted (truth: The answer asserts that the client observes the TCP close 'with no additional round-trip beyond the response itself,' a performance guarantee not stated or implied by the Go http.Server documentation, which only specifies that Shutdown waits for active requests to complete before closing idle connections.): The shutdown code is a correct, idiomatic Go graceful-shutdown pattern (signal → context with timeout → srv.Shutdown). The explanation that Connection: close is emitted on the final response of each drained connection during Shutdown is accurate and consistent with Go's net/http implementation. The only minor imprecision is the phrasing 'responses served after Shutdown is invoked' which reads as a temporal rule rather than the more precise 'the last response on each connection being closed.'
- cal-24-planted (truth: The answer claims that `tolerationSeconds: 300` on a `NoSchedule` toleration causes the pod to be evicted after 300 seconds if the taint is removed, but per the Kubernetes API `tolerationSeconds` only takes effect for taints with `effect: NoExecute`; for `NoSchedule` (and `PreferNoSchedule`) the field is ignored by the scheduler.): The response correctly shows a valid YAML manifest with taints/tolerations, non-privileged security context, and field-by-field explanations. The YAML is syntactically valid and would schedule correctly. The main error is in the tolerationSeconds explanation: it is only meaningful with NoExecute effect and applies when a taint is present (not removed), yet the response describes it as triggering eviction upon taint removal with a NoSchedule effect. All other field explanations are accurate.
- cal-27-clean (truth: clean): The core ambiguous-failure mechanism works: on TimeoutError the key is stamped 'ambiguous' and subsequent calls raise AmbiguousError without re-invoking the callable, satisfying the at-most-once requirement. However, the clear-failure path has a code/explanation contradiction (marks 'done' but claims re-execution is allowed), and the in-progress thread-safety guard is referenced but never actually implemented (the event is never created or stored). These are substantive correctness bugs that undermine the stated guarantees.

Re-run with a strong judge (fable-5) later for comparison: same pools, different judge — that delta IS the metric (cheap-judge recall vs strong-judge recall).