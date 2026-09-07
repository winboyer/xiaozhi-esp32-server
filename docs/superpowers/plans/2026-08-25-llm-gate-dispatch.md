# LLM Gate Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Chaobai River gate-dispatch request call the LLM with available monitoring context and return a seven-section analysis.

**Architecture:** Keep keyword routing in the HTTP API, but replace the fixed estimate formatter response with a synchronous LLM call. A small context builder reads only the latest water-level and flow records from `DataQueryEngine`, marks unmatched records as generic data, and passes fixed gate specifications plus missing-data boundaries to the model prompt.

**Tech Stack:** Python 3, `requests`, existing OpenAI-compatible LLM API, `unittest`.

## Global Constraints

- Each gate-dispatch request must invoke `call_llm_sync` exactly once.
- The LLM prompt must include the seven required Chinese section titles verbatim.
- Never represent sample or unmatched database records as real Xinggezhuang gate data.
- Never issue an automatic control command; require manual review.
- On LLM failure, return a service-unavailable message and data summary, never the former fixed seven-section rule template.

---

### Task 1: Add monitoring-context and prompt tests

**Files:**
- Modify: `test_gate_opening_plan.py`
- Modify: `intent_api_server.py`

**Interfaces:**
- Produces: `build_gate_dispatch_monitoring_context(engine) -> dict`
- Produces: `build_llm_gate_dispatch_prompt(user_query, parameters, monitoring_context) -> tuple[str, str]`

- [ ] **Step 1: Write a failing context test**

```python
def test_monitoring_context_marks_unmatched_data_as_generic():
    context = build_gate_dispatch_monitoring_context(engine)
    assert context["data_scope"] == "generic_monitoring_data"
    assert "gate_openings" in context["missing_data"]
```

- [ ] **Step 2: Run the test and confirm the missing-helper failure**

Run: `python -m unittest -v test_gate_opening_plan.py`

- [ ] **Step 3: Implement the context builder and prompt builder**

Read latest records from `flow_radar_level` and `flow_tof_meter`; include field values, timestamps, device names, locations, data-scope label and missing data list. Build a system prompt that mandates all seven headings, evidence labels, manual review, and no invented gate identifiers or control commands.

- [ ] **Step 4: Run the test and confirm it passes**

Run: `python -m unittest -v test_gate_opening_plan.py`

### Task 2: Route dispatch requests through the LLM

**Files:**
- Modify: `intent_api_server.py:_handle_analyze`
- Modify: `test_gate_opening_plan.py`

**Interfaces:**
- Consumes: `build_gate_dispatch_monitoring_context()` and `build_llm_gate_dispatch_prompt()`.
- Produces: SSE response whose summary is the LLM output.

- [ ] **Step 1: Write a failing LLM-call routing test**

```python
def test_gate_dispatch_handler_calls_llm_once(monkeypatch):
    # Patch call_llm_sync and assert one call with the raw user query,
    # the seven headings, and monitoring context in the prompt.
```

- [ ] **Step 2: Run the test and confirm fixed formatter behavior fails it**

Run: `python -m unittest -v test_gate_opening_plan.py`

- [ ] **Step 3: Replace fixed formatter response in the HTTP branch**

Call `call_llm_sync` once with the dispatch prompt. Return its content through `_send_sse_done`. If it raises, return a short unavailable message plus the monitoring data-scope and missing-data statement.

- [ ] **Step 4: Run regression tests**

Run: `python -m unittest -v test_gate_opening_plan.py`

### Task 3: Verify live API behavior

**Files:**
- Modify: none

- [ ] **Step 1: Compile source files**

Run: `python -m py_compile intent_api_server.py`

- [ ] **Step 2: Restart the port 8005 service with `/opt/miniconda3/bin/python`**

Run: `nohup /opt/miniconda3/bin/python intent_api_server.py > /tmp/intent-api.log 2>&1 < /dev/null &`

- [ ] **Step 3: Submit the target query to the live API**

Run:

```bash
curl -sN -X POST http://127.0.0.1:8005/api/v1/intent/analyze \
  -H 'Content-Type: application/json' \
  -d '{"query":"现在过流 300m³/s，请给我推广闸门调度方案"}'
```

- [ ] **Step 4: Inspect response and logs**

Confirm the response has all seven headings, and the log includes the LLM dispatch call. Confirm it does not claim database sample values are Xinggezhuang gate data.
