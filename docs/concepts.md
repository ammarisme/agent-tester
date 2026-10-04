# Concepts

Agents are non-deterministic. One request per case with a single pass/fail answer hides what matters: how often the agent is right, how uncertain that estimate is, how slow the tail is, and whether the same input gets the same answer twice. Agent Tester reports those distributions.

## Agents and contracts

An **agent** is anything reachable over HTTP. Agent Tester does not need an SDK or adapter; it needs a **contract** that says:

- **invoke**: how to build the HTTP request for one case (method, URL, headers, body, timeout);
- **poll** (optional): for agents that accept work and finish later, how to poll a status URL until the work is done;
- **extract**: which response fields to pull out with JSONPath. The field named `final_text` is what expectations are checked against. Numeric extracted fields become metrics.

An agent also has **params**, a free-form object referenced in templates as `{{ agent.params.<name> }}`. Keep environment-specific values (base URL, model id) in params so one contract can target several environments.

See [Agent contracts](agent-contracts.md).

## Datasets and cases

A **dataset** is a list of **cases**. Each case has:

- `id`: unique within the dataset;
- `input`: any JSON value, available to templates as `{{ input }}`;
- `expected` (optional): deterministic checks such as `contains`, `regex` or `max_latency_ms`;
- `tags` (optional): labels for the per-tag breakdown.

See [Datasets](datasets.md).

## Runs and trials

A **run** evaluates one or more agents on every case of one dataset. Each (agent, case) pair is evaluated `repeats` times; each repetition is a **trial**, numbered from 0 in the results (the UI and JUnit show trial numbers from 1). The number of results in a run is:

```
agents × cases × trials
```

Every result records the outcome class, whether it passed, the reasons for any failure, latency, HTTP status, extracted fields, metrics, the final text, and the full **trajectory**: every request and response (secrets redacted), including each poll step.

Run statuses in the controller are `queued`, `running`, `completed`, `failed` and `cancelled`.

## Outcome classes

Every result has exactly one outcome class. They are ordered from best to worst:

| Class | Meaning | What to do |
| --- | --- | --- |
| `success` | The agent responded and every expectation (if any) held. | Nothing. |
| `failed_assert` | The agent responded, but at least one expectation failed. | Read `failures` on the result. This is a quality problem in the answer, or an expectation that is too strict. |
| `agent_error` | The agent returned a non-2xx status (HTTP 400 or above) or, when polling, reported a terminal failure state (`failed_when`). | Look at the status code and response body in the trajectory. Frequent 429 or 503 responses often mean the concurrency is too high for the agent. |
| `timeout` | The request exceeded `invoke.timeout_s`, or polling did not reach `done_when` within `poll.timeout_s`. | Check whether the agent is slow or stuck. Raise the timeout if the work is legitimately long. |
| `transport_error` | The runner could not reach the agent: DNS failure, connection refused, TLS error. | Check the URL and network path from the runner. Inside Docker, `localhost` is the container itself. |
| `config_error` | The request could not be built: a template error, a missing or disallowed secret, or another contract problem. | Read `error`; it names the field that failed, such as `invoke.headers.Authorization`. Fix the contract or set the environment variable. |

`agent_error`, `timeout`, `transport_error` and `config_error` are **error classes**. Expectations are only evaluated when the request itself succeeded, so a result is `failed_assert` only if the agent answered.

## Pass rate, success rate and error rate

These three rates answer different questions:

| Rate | Numerator | Denominator |
| --- | --- | --- |
| `pass_rate` | Scored results that passed | Scored results |
| `success_rate` | Results with outcome `success` | All results |
| `error_rate` | Results in an error class | All results |

A result is **scored** when expectation checking is on for the run and its case has a non-empty `expected` block. A scored result that ended in an error class counts as **not passed** (its failure reason is `not scored: <class>`), so errors lower the pass rate. Cases without expectations are left out of the pass rate entirely.

`pass_rate` is `null` when nothing was scored: when no case has expectations, or when the run was started with expectation checking off. In that case the report is about reachability and latency, and CLI gates use `success_rate` instead (see [Quality gates](cli.md#quality-gates)).

The report also includes `outcome_counts` and `outcome_rates` for every class that occurred.

## Confidence intervals

A pass rate from 20 results is much less certain than one from 2,000. Each agent's pass rate is reported with a **Wilson score 95% interval** (`pass_rate_ci95`), computed over the scored results.

The Wilson interval behaves well at small sample sizes and at rates near 0 or 1, where the textbook normal approximation gives impossible or overconfident bounds. For example, 9 passes out of 10 gives a pass rate of 90% with an interval of roughly 60% to 98%.

How to read intervals when comparing agents:

- **Intervals do not overlap**: the difference is very likely real.
- **Intervals overlap**: the data does not establish a difference. It may exist, but you need more evidence. Add cases, or add trials per case.
- **An interval is wide**: the estimate is imprecise. Width shrinks roughly with the square root of the number of scored results, so halving it takes about four times as many.

Trials of the same case are not independent samples of the agent's overall quality (a case that is hard is hard every time), so more distinct cases tighten the estimate more honestly than more trials of the same cases.

## Consistency: pass^k, pass@k and flaky cases

When a run has more than one trial per case, each agent gets a `consistency` block:

| Field | Meaning |
| --- | --- |
| `pass_all_trials_rate` | Share of cases that passed on **every** trial. Often written pass^k. This is what a user who asks the same thing k times experiences. |
| `pass_any_trial_rate` | Share of cases that passed on **at least one** trial. Often written pass@k. This is the agent's ceiling if you could retry and pick the best answer. |
| `flaky_cases` | Number of cases that passed on some trials and failed on others. |
| `flaky_case_ids` | The ids of those cases, sorted, up to 50. |
| `basis` | `passed` if any of the agent's results were scored; otherwise `success`. Informational only. |

A large gap between pass@k and pass^k means the agent can do the task but not reliably. Flaky cases are the best place to start investigating.

Each trial is judged on its own terms: a scored trial passes when its checks held, and an unscored trial (a case without expectations) passes when the outcome is `success`. Datasets that mix both kinds are counted fairly.

## Latency

Latency (`latency_ms`) is measured by the runner from the start of the invoke request to the end of the last request, **including all polling** for async agents. It is recorded for every result, including errors and timeouts.

Each agent's `scalars.latency_ms` contains `count`, `mean`, `std`, `min`, `max`, `p50`, `p90`, `p95` and `p99`. Percentiles use linear interpolation between the closest ranks (the same method as NumPy's default). The p99 of a small sample is essentially the maximum; read tail percentiles only when you have hundreds of results.

`latency_histogram` has 24 equal-width bins from the minimum to the **p99**. Results slower than p99 are counted in `overflow` rather than stretching the axis, so one pathological request does not flatten the chart. The histogram contains `edges` (25 bin boundaries), `counts` and `overflow`.

## Metrics

Every result has a `metrics` object with `latency_ms`, `n_polls` for async agents that polled, and every **numeric** extracted field (booleans excluded). Extracting `$.usage.completion_tokens` as `completion_tokens`, for example, adds it to `metrics`. Each metric gets the same statistics as latency under `scalars.<name>`.

## Per-tag breakdown

`by_tag` groups results by the case's tags. A case with several tags contributes to each. For each tag:

| Field | Meaning |
| --- | --- |
| `n` | Number of results with this tag |
| `pass_rate` | Pass rate over the scored results with this tag (`null` if none were scored) |
| `error_rate` | Share of results with this tag in an error class |
| `latency_p50` | Median latency of results with this tag |

Per-tag numbers come from fewer results than the overall numbers and are correspondingly less certain.

## The summary object

The run summary maps each agent id to an object with these fields: `agent_id`, `agent_name`, `n_results`, `n_cases`, `trials`, `outcome_counts`, `outcome_rates`, `n_scored`, `pass_rate`, `pass_rate_ci95` (`[low, high]` or `null`), `success_rate`, `error_rate`, `scalars`, `latency_histogram`, `consistency` (`null` for a single trial), and `by_tag`. The full schema is printed by `agent-tester schema results`.
