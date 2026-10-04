# Datasets

A dataset is a list of cases. Each case is sent to every agent in a run, once per trial. Datasets can be JSON, JSONL or CSV files, stored in the controller, or fetched from a URL at run time.

Print the authoritative JSON Schema for one case with:

```bash
agent-tester schema case
```

## Case format

```json
{
  "id": "refund-policy",
  "input": { "message": "What is your refund policy?", "locale": "en-GB" },
  "expected": {
    "contains": ["30 days"],
    "not_contains": ["I'm not sure"],
    "max_latency_ms": 5000
  },
  "tags": ["support", "policy"]
}
```

| Field | Type | Description |
| --- | --- | --- |
| `id` | string | Unique within the dataset. Numbers are converted to strings. If missing or empty, `case_id` is used; if both are missing, an id is generated (see [Automatic ids](#automatic-ids)). |
| `input` | any JSON | Available to contract templates as `{{ input }}`. Usually an object such as `{"message": "..."}`. |
| `expected` | object | Optional checks, described below. `{}`, `""` and `null` mean no checks. |
| `tags` | list of strings, or a string | Labels for the [per-tag breakdown](concepts.md#per-tag-breakdown). A string is split on `,`, `;` or `\|`. |

Other keys are allowed. They are kept on the case (including in datasets stored in the controller) and available to templates as `{{ case.<key> }}`.

## Expectations

Expectations are deterministic checks run against a result when the request succeeded. If any check fails, the result's outcome is `failed_assert` and each failure is listed with a reason. Unknown keys are rejected (for example, `contain` is reported as `unknown check 'contain' in expected (use one of: ...)`).

Most checks look at the result's **final text**: the extracted `final_text` field, or the raw response body if the contract does not extract one (see [`extract`](agent-contracts.md#extract)). A missing final text is treated as an empty string.

| Check | Value | Passes when |
| --- | --- | --- |
| `equals` | any JSON | If the value is a string: the final text equals it exactly (no trimming, case-sensitive). Otherwise the final text is parsed as JSON and compared to the value, so `{"equals": {"ok": true}}` matches a final text of `{"ok": true}` regardless of formatting or key order. If the final text is not valid JSON, the check fails. |
| `contains` | string or list of strings | Every string is a substring of the final text. Case-sensitive. |
| `not_contains` | string or list of strings | None of the strings is a substring of the final text. Case-sensitive. |
| `regex` | string | Python regular expression; `re.search` finds a match anywhere in the final text. Matching uses `DOTALL`, so `.` also matches newlines. Case-sensitive unless you add `(?i)`. Invalid expressions are rejected at import. |
| `jsonpath_equals` | object of path to value | For each entry, the value found equals the expected value. See below. |
| `max_latency_ms` | number greater than 0 | The result's latency is at most this many milliseconds. For async agents latency includes polling. |

### `jsonpath_equals`

Keys are resolved in one of two ways:

- **A key starting with `$`** is a JSONPath evaluated against the parsed body of the **last response**: the invoke response for synchronous agents, the last poll response for async agents. The first match is compared.
- **A bare key** names an **extracted field** from the contract's `extract` or `poll.extract`.

```json
{
  "expected": {
    "jsonpath_equals": {
      "$.result.status": "approved",
      "$.items[0].sku": "A-100",
      "status": "COMPLETED"
    }
  }
}
```

A path that matches nothing fails with `not found`. An extracted field that matched nothing has the value `null`, so a bare key for it compares `null` with the expected value. Comparison is exact and type-sensitive.

### When checks are not run

- Expectation checking is turned off for the run (**Check expectations** in the UI, `score_expectations: false` in options, `--no-score` in the CLI). Results then have `passed: null` and only outcome classes are reported.
- The request did not succeed (`agent_error`, `timeout`, `transport_error`, `config_error`). A case with expectations then counts as **not passed** with the failure `not scored: <class>`. See [Pass rate](concepts.md#pass-rate-success-rate-and-error-rate).

## File formats

The format is chosen from the file extension: `.jsonl` or `.ndjson` for JSONL, `.csv` for CSV, `.json` for JSON. Without a recognised extension (for example, pasted text), the content decides: text starting with `[` or `{` that parses as one JSON document is JSON; text starting with `{` that does not parse is treated as JSONL; anything else is CSV.

Files must be UTF-8. A leading byte-order mark is accepted on upload.

### JSONL

One case object per line.

```jsonl
{"id": "greet", "input": {"message": "Hello agent"}, "expected": {"contains": ["Hello agent"]}, "tags": ["smoke"]}
// Lines starting with // are comments.
{"id": "unicode", "input": {"message": "Grüße aus Zürich"}, "expected": {"regex": "Z(ü|u)rich"}, "tags": ["edge"]}
```

Blank lines and lines starting with `//` are skipped. Errors are reported with their line number.

### JSON

Any of:

- an array of case objects: `[{...}, {...}]`;
- an object with a `cases` array: `{"cases": [{...}]}`;
- a single case object.

Errors inside a JSON document are reported by position (`case #3: ...`), except JSON syntax errors, which carry a line number.

### CSV

The first row is the header. Header names are trimmed. Columns map to cases as follows:

| Column | Becomes |
| --- | --- |
| `id` or `case_id` | The case id. |
| `input` | If present and non-empty in a row: parsed as JSON if it looks like JSON. An object or array is used as the input; anything else becomes `{"message": <value>}`. |
| any other column | When the row has no `input` value, every column except `id`, `case_id`, `input`, `expected` and `tags` becomes a field of `input`. |
| `expected` | Parsed as JSON if it looks like JSON. An object is used as the expectations; any other value becomes `{"contains": [<value>]}`. |
| `tags` | Split on `,`, `;` or `\|`. |

A cell "looks like JSON" if it starts with `{`, `[` or `"`, or is exactly `true`, `false` or `null`. Other cells, including numbers, stay strings.

Example (`datasets/samples/smoke.csv`):

```csv
id,message,expected,tags
greet,Hello agent,Hello agent,smoke
arithmetic,What is 2+2?,2+2,smoke
refund-policy,What is your refund policy?,"{""not_contains"": [""I'm not sure""]}",support
```

The first row becomes:

```json
{"id": "greet", "input": {"message": "Hello agent"}, "expected": {"contains": ["Hello agent"]}, "tags": ["smoke"]}
```

Errors are reported with the line number of the record.

## Automatic ids

A case without an `id` (or `case_id`) gets `case-<n>`, where `n` is its 1-based position in the file. Ids must be unique: a repeated id is an error that names the position where it was first seen, for example `duplicate id 'greet' (first seen in case #1)`.

## Error reporting

Parsing does not stop at the first problem. Every problem in the file is collected (the first 50 are reported), each with a line number where one is available, so a large file can be fixed in one pass. Nothing is imported unless the whole file is valid.

- In the UI, the import preview lists the problems before you save.
- `POST /api/datasets/parse` returns them in `errors` without saving; imports fail with HTTP 422 and the same list (see [API errors](api.md#errors)).
- `agent-tester validate --dataset file.jsonl` prints them and exits with code 2.

An empty file parses to zero cases. The CLI refuses to run an empty dataset, and the controller refuses to start a run on a stored dataset with no cases.

## Stored datasets and URL datasets

In the controller, a dataset has one of two sources:

| Source | Cases live | Notes |
| --- | --- | --- |
| Stored (`source_type: "local"`) | In the controller database | Import files with **replace** (default) or **append**. Append fails with HTTP 409 if any imported id already exists. Upload size is limited by `MAX_UPLOAD_MB` (20 MB by default). |
| URL (`source_type: "uri"`) | At an `http://` or `https://` URL | Fetched fresh when each run starts, and when you browse or export the dataset. Cannot be imported into. |

A run can also use a one-off URL without creating a dataset (`dataset_uri` in `POST /api/runs`).

The controller only accepts `http://` and `https://` dataset URLs. It never reads dataset files from its own filesystem. The CLI additionally accepts local paths and `file://` URLs.

Stored datasets can be exported as JSONL (`GET /api/datasets/{id}/export`).
