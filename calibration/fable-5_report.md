# Side-Eye calibration baseline (judge: fable-5)

Generated: 2026-08-31 09:51 PDT

Pairs: 59 total (27 planted, 32 clean)

**Recall on planted defects: 26/27** — 96
**False-flag rate on clean: 15/32** — 47%

Per-pair:

| id | planted | class | judge score | severity | flagged | truth |
|---|---|---|---|---|---|---|
| cal-01-clean | clean | - | 5 | none | no | ok |
| cal-01-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-02-clean | clean | - | 5 | none | no | ok |
| cal-02-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-04-clean | clean | - | 5 | none | no | ok |
| cal-04-planted | yes | subtle_logic_bug | 5 | none | no | ok |
| cal-05-clean | clean | - | 4 | minor | no | ok |
| cal-05-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-06-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-07-clean | clean | - | 2 | critical | YES | FALSE-FLAG |
| cal-07-planted | yes | unverified_claim | 1 | critical | YES | CAUGHT |
| cal-08-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-08-planted | yes | incorrect_api_claim | 1 | critical | YES | CAUGHT |
| cal-09-clean | clean | - | 4 | minor | no | ok |
| cal-09-planted | yes | subtle_logic_bug | 3 | major | YES | CAUGHT |
| cal-10-clean | clean | - | 4 | minor | no | ok |
| cal-10-planted | yes | unverified_claim | 3 | major | YES | CAUGHT |
| cal-11-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-11-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-12-clean | clean | - | 5 | none | no | ok |
| cal-12-planted | yes | subtle_logic_bug | 2 | critical | YES | CAUGHT |
| cal-13-planted | yes | incorrect_api_claim | 2 | major | YES | CAUGHT |
| cal-14-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-14-planted | yes | subtle_logic_bug | 1 | critical | YES | CAUGHT |
| cal-15-clean | clean | - | 2 | major | YES | FALSE-FLAG |
| cal-15-planted | yes | unverified_claim | 2 | major | YES | CAUGHT |
| cal-16-clean | clean | - | 2 | major | YES | FALSE-FLAG |
| cal-16-planted | yes | unverified_claim | 1 | critical | YES | CAUGHT |
| cal-17-clean | clean | - | 5 | none | no | ok |
| cal-17-planted | yes | subtle_logic_bug | 1 | critical | YES | CAUGHT |
| cal-18-clean | clean | - | 5 | none | no | ok |
| cal-18-planted | yes | incorrect_api_claim | 2 | critical | YES | CAUGHT |
| cal-19-clean | clean | - | 5 | none | no | ok |
| cal-19-planted | yes | subtle_logic_bug | 3 | major | YES | CAUGHT |
| cal-20-clean | clean | - | 2 | major | YES | FALSE-FLAG |
| cal-20-planted | yes | incorrect_api_claim | 2 | major | YES | CAUGHT |
| cal-21-clean | clean | - | 5 | none | no | ok |
| cal-21-planted | yes | subtle_logic_bug | 2 | major | YES | CAUGHT |
| cal-22-clean | clean | - | 5 | none | no | ok |
| cal-22-planted | yes | incorrect_api_claim | 3 | major | YES | CAUGHT |
| cal-23-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-23-planted | yes | unverified_claim | 2 | major | YES | CAUGHT |
| cal-24-clean | clean | - | 4 | minor | no | ok |
| cal-24-planted | yes | incorrect_api_claim | 2 | major | YES | CAUGHT |
| cal-25-clean | clean | - | 4 | minor | no | ok |
| cal-25-planted | yes | subtle_logic_bug | 2 | major | YES | CAUGHT |
| cal-26-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-26-planted | yes | subtle_logic_bug | 3 | major | YES | CAUGHT |
| cal-27-clean | clean | - | 2 | major | YES | FALSE-FLAG |
| cal-27-planted | yes | subtle_logic_bug | 2 | major | YES | CAUGHT |
| cal-28-clean | clean | - | 2 | major | YES | FALSE-FLAG |
| cal-28-planted | yes | unverified_claim | 2 | critical | YES | CAUGHT |
| cal-29-clean | clean | - | 3 | major | YES | FALSE-FLAG |
| cal-29-planted | yes | subtle_logic_bug | 2 | critical | YES | CAUGHT |
| ctrl-01 | clean | - | 5 | none | no | ok |
| ctrl-02 | clean | - | 5 | none | no | ok |
| ctrl-03 | clean | - | 3 | major | YES | FALSE-FLAG |
| ctrl-04 | clean | - | 5 | none | no | ok |
| ctrl-05 | clean | - | 2 | major | YES | FALSE-FLAG |

Mismatches detail:
- cal-04-planted (truth: The domain character class [a-zA-Z0-9.-]+ includes the dot, so inputs like "user@.com" or "user@-example.com" (leading dot or hyphen in a domain label) incorrectly pass validation because the + quantifier allows the group to match a single '.' or start with '-'.): Provides the widely-used pragmatic email regex with a correct TypeScript wrapper and an accurate one-line justification; claims match the regex's actual behavior, with only minor known edge-case laxity inherent to this approach.
- cal-06-clean (truth: clean): The code itself is safe and functional (parameterised psycopg2 queries, validation, connection cleanup), but the explanation contains a significant factual error: psycopg2 does not send parameters in a separate protocol message — it escapes client-side. Additionally, the guidance for genuinely user-supplied SQL (regex whitelisting) is inadequate security advice, and the literal question is only tangentially addressed.
- cal-07-clean (truth: clean): The design (HashMap-backed intrusive doubly-linked list behind a Mutex) and the O(1) explanation are sound in principle, but the code does not compile: `Mutex(...)` is not a valid constructor, and `move_to_front` is implemented on the wrong type (`LruCache` instead of `LruCacheInner`) yet invoked on the inner guard. Additional MutexGuard borrow-check issues exist. The included test module falsely suggests verified behavior.
- cal-08-clean (truth: clean): The code itself is correct and idiomatic: FieldsPerRecord = -1 genuinely suppresses ErrFieldCount to keep variable-width rows, encoding/csv does skip fully-empty lines as documented, and EOF vs. real errors are handled properly. However, the explanation misstates the semantics of csv.ErrQuote (describing it as a quote outside a quoted field, which is actually ErrBareQuote's domain), which is a factual API error in the required 'which errors and why' portion of the answer.
- cal-11-clean (truth: clean): The code itself is correct and demonstrates the right derive attributes (#[serde(skip_serializing_if = "Option::is_none")]) with accurate expected output, and the deserialization note (missing field -> None) is accurate. However, the explanation repeatedly and incorrectly asserts that omitting None fields is serde's default behavior, when in fact None serializes to null without the attribute. This wrong API-semantics claim is a major defect despite the correct code.
- cal-14-clean (truth: clean): The code itself is correct: Map.has properly caches undefined results, and recursively memoizing returned functions preserves curried usage as demonstrated. However, the explanation contains a factually wrong mechanism claim — crediting the JSON replacer (which only affects argument key serialization) for undefined *return value* handling — and omits real limitations of JSON.stringify keying (function/object args, key ordering, throwables). Working code with a wrong explanatory claim caps the score at 3.
- cal-15-clean (truth: clean): The YAML structure looks plausible but the core mechanism is broken: ConfigMap volume updates happen via symlink swap, so 'modify' inotify events on the file never fire, and busybox lacks inotifywait entirely. The 'app' container runs only a copy loop rather than an application, and the zero-downtime confirmation cites a readiness probe that doesn't exist. The explanation contains a wrong factual claim about how Kubernetes updates mounted ConfigMaps.
- cal-16-clean (truth: clean): The overall design (Acquire/Release counters, single-owner index reads Relaxed) is a reasonable SPSC pattern and the lock-freedom sentence is fine, but the code does not compile (`Option::replace(Some(val))` type error), lacks the required `unsafe impl Sync`, so it can't actually be used across threads, and has counter-overflow correctness issues when N is not a power of two.
- cal-20-clean (truth: clean): The crate identification (tokio's Semaphore) and the conceptual explanation are correct, but the shown code fails to compile because Semaphore is not Clone and must be Arc-wrapped (with acquire_owned for spawned tasks), making the core code sample broken.
- cal-23-clean (truth: clean): The code compiles and the high-level answer (the header appears on responses to requests in-flight when Shutdown begins) is essentially right, but the explanation of the internal mechanism is wrong: net/http does not set r.Close = true on shutdown; it disables keep-alives (doKeepAlives/closeAfterReply), and the response writer adds the header. This fabricated internal detail is a major factual defect despite working code.
- cal-26-clean (truth: clean): The core retry implementation is correct and does rethrow the original error object with its type preserved (instanceof works). However, the accompanying example fails TypeScript compilation (a synchronous string-returning function passed where Promise<T> is required) and its comment claims a catch-path outcome that never happens because the retry actually succeeds. These explanation/example defects undermine an otherwise sound answer.
- cal-27-clean (truth: clean): The response addresses the question and the single-threaded ambiguous-failure path works, but two of its explicit safety claims are false: the in-progress/event mechanism is never wired up (concurrent double-execution is possible) and clear failures are marked 'done', so later calls return cached None rather than re-executing as claimed. These contradictions between the code and its stated guarantees are major defects.
- cal-28-clean (truth: clean): The response provides plausible-looking Go code labeled as Greenwald-Khanna with a claimed ε=0.01 rank-error bound, but the implementation departs from GK in three critical places: new tuples get Δ=0, the merge condition is not the GK condition, and the query ignores Δ. As a result the advertised error bound is not actually guaranteed by this code, making the central claim of the answer unsupported.
- cal-29-clean (truth: clean): The response shows the right general batched-delete pattern and loop structure, but the code is dialect-inconsistent pseudocode that would not run as written (MySQL forbids LIMIT in IN subqueries despite using MySQL's ROW_COUNT/LEAVE), and it omits per-batch commits, which undermines the explicit lock-time goal.
- ctrl-03 (truth: clean): The response provides a const-generic in-place reverse that works for all non-empty arrays, but it unconditionally computes N - 1, so calling it with a zero-length array ([T; 0]) panics (underflow in debug, out-of-bounds swap in release). Correct for the common case but fails a legitimate edge case.
- ctrl-05 (truth: clean): The function handles embedded commas and doubled quotes inside quoted fields, but it double-emits when the line ends with a quoted field, appending a spurious empty final field ('"a"' -> ['a','']). This is a genuine correctness bug in a core case, so the answer is only partially correct.

Re-run with a strong judge (fable-5) later for comparison: same pools, different judge — that delta IS the metric (cheap-judge recall vs strong-judge recall).