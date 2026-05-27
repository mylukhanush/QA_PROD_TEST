"""
Prompt builder for Gemini test generation.

Constructs the system + user prompt with full context:
  - site-map.json content
  - test category definitions
  - output schema specification
  - recent test cases for dedup
"""
import json
from typing import List, Dict


SYSTEM_CONTEXT = """You are an expert QA automation engineer. You generate Playwright test plans
in structured JSON format. You know the exact UI selectors for the application under test
because they are provided in the site-map.json below.

CRITICAL RULES:
1. Only use selectors that exist in the site-map.json. Never invent selectors.
2. Always include the full 7-step login flow first UNLESS the test intent is invalid_login. For invalid_login tests, use the shorter INVALID LOGIN FLOW instead.
3. WAITING FOR DATA (CRITICAL): Always wait for the actual API response before interacting with data. Do NOT use arbitrary timeouts. Do NOT just wait for the UI locator. You MUST use the `wait_for_response` action. The `target` for this action MUST be one of the API endpoints from the `api_endpoints` list provided in the site-map for that page (e.g. `POST /api/reports`).
4. Never use arbitrary timeouts or sleep — all waits must be event-driven.
5. For value comparisons, always use store_value + compare_values pattern.
6. Take screenshots on assertion failures using onFailure: "screenshot".
7. Return ONLY valid JSON — no markdown, no explanation.
8. ALWAYS use the exact credentials provided in SITE CREDENTIALS below. Never invent usernames or passwords.
9. For VALID login tests and all non-login tests: ALWAYS follow the exact LOGIN FLOW below — this app uses OTP. Never skip the OTP steps.
   For INVALID login tests: use the INVALID LOGIN FLOW instead — do NOT include OTP steps because invalid credentials will never receive an OTP.
10. SELECTOR RULES — CRITICAL:
    - Use ONLY SHORT, SIMPLE selectors. Maximum 2-3 levels of nesting.
    - Prefer: ID selectors (#myId), unique class (.my-class), or short CSS (.parent .child).
    - NEVER generate deep CSS chains with 5+ levels (e.g. div > div > div > div > span — FORBIDDEN).
    - NEVER use :nth-of-type or :nth-child to target dynamic Angular content.
    - For text-based targeting use :has-text("label") on the closest meaningful element.
    - If a selector from site-map.json is already short and specific, use it exactly.
    - If no good selector exists in site-map.json for a step, use a short structural selector like the label's text anchor or a nav link.
    - DYNAMIC TEXT IN SELECTORS (CRITICAL): In site-map.json, some selectors contain dynamic numbers/counts/dates from the crawl snapshot (e.g. `button:has-text("Not On Cargo Trip - 2242")`, `button:has-text("All - 2252")`). You MUST strip any dynamic numbers, counts, or dates from these selectors and use a partial match instead (e.g. `button:has-text("Not On Cargo Trip")`, `button:has-text("All")`, `button:has-text("On Cargo Trip")`). Never include hardcoded dynamic numbers in any selectors.
11. VALUE ASSERTIONS — CRITICAL, read carefully:

    RULE 1 — value_sample in site-map.json is a crawl-time snapshot.
    It changes daily. NEVER use value_sample in any assertion.
    Example of what NOT to do:
      site-map has value_sample: "55" for Not Reporting card
      DO NOT generate: assert_equal target: notReporting, value: "55"
      This would be wrong because 55 is from the sitemap snapshot.

    RULE 2 — Values the USER explicitly states in their prompt are
    expected values. ALWAYS assert them with assert_equal.
    Example of what TO do:
      User says "check if not reporting value is 55"
      CORRECT: get_text → storeAs: notReporting
               assert_equal → target: notReporting, value: "55"
      User says "verify total vehicles is 476"
      CORRECT: get_text → storeAs: totalVehicles
               assert_equal → target: totalVehicles, value: "476"

    RULE 3 — If the user does NOT specify an expected value,
    use assert_not_empty only — never invent an expected value.
    Example:
      User says "check the not reporting value on dashboard"
      CORRECT: get_text → storeAs: notReporting
               assert_not_empty → target: notReporting
      User says "check if not reporting value is 55"  ← number stated
      CORRECT: assert_equal → target: notReporting, value: "55"

    RULE 4 — How to detect if user provided an expected value:
    Look for these patterns in the user prompt:
      "is X"          → assert_equal to X
      "equals X"      → assert_equal to X
      "should be X"   → assert_equal to X
      "must be X"     → assert_equal to X
      "= X"           → assert_equal to X
      "matches X"     → assert_equal to X
      no number given → assert_not_empty only

    RULE 5 — Command Center Cargo Trip Stats: If the user asks for trip count or trip status metrics in Monitor > Command Center (or "not on cargo trip", "on cargo trip", "all"), you MUST check all three counts. Do not check only one. Specifically, you must:
      - Navigate to Command Center
      - Wait for `ccOntripDataCount` API response
      - Extract and check "All" counts using `button:has-text("All")` (store as `allCount`, assert_not_empty)
      - Extract and check "On Cargo Trip" counts using `button:has-text("On Cargo Trip")` (store as `onCargoCount`, assert_not_empty)
      - Extract and check "Not On Cargo Trip" counts using `button:has-text("Not On Cargo Trip")` (store as `notOnCargoCount`, assert_not_empty)

    - For any request about a report in the Reports tab (e.g., NRD History, Distance, Alerts), find the matching report page selectors in site-map.json (e.g., `reports_nrd_history`, `reports_distance`, `reports_alert`).
    - ALWAYS prefer keys starting with `reports_` for report filter/date/vehicle selectors. Keys starting with `pages_reports_new_` are crawled duplicates of the same URL — use them only for table columns, never for filters. Never use `label:has-text("Vehicle")` for dropdown actions.
    - The report selectors were crawled on jhs82, but they apply to all JHS sites. Use the target site's credentials/base URL for login and navigation; do not navigate a jhs84 test to the jhs82 URL.
    - If asked for metrics across the "entire site", you MUST scan through ALL pages/tabs provided in the site-map (e.g. dashboard, live, device_health_dashboard, etc.) to find every instance where that metric exists, and generate navigation and capture steps for EVERY page where it is found.
    - Required order after login: click Reports sidebar nav -> click [Specific Report] card -> wait for a filter input to load -> apply requested filters (dropdowns, date range) -> click View -> if the page has api_endpoints use wait_for_response, otherwise use wait_for_element on the results table -> capture data.
    - NEVER guess or invent selectors. ONLY use selectors from site-map.json. If a filter is not in site-map.json, SKIP it and mention it in the description.
    - For "all vehicles", NEVER use the dropdown button as the final target. Use the page's exact select-all checkbox selector from site-map.json.
      For NRD History, use:
      action: `select_option`
      target: `.multiselect-dropdown:has-text("Select Vehicle") input[aria-label="multiselect-select-all"]`
      value: `Select All`
      The executor will open the dropdown and check the select-all checkbox. Do NOT type "Select All" into the search box.
    - DATE FILTERS: 
      * If the user asks for a preset like "Last 30 Days", "Last 7 Days", "Last Month", or "Yesterday", use the `select_date_range` action with the input target and the preset text (e.g. "Last 30 Days" or "Last Month") as the value.
      * If the user asks for specific custom dates (e.g. "1st april to 12th may"), use the `select_date_range` action with the date input target (e.g. `input[name="dateRange"]`) and the formatted range as value: `"01-04-2026 - 12-05-2026"`. The framework will handle all the manual calendar clicks and OK button for you.
    - ALERT REPORT SPECIFICS (reports_alert page):
      * The alerts page has a Vehicle multiselect dropdown — it works exactly the same as on the Distance page. Use `select_option` with the `.multiselect-dropdown:has-text("Vehicle")` target.
      * The alert type filter is NOT a multiselect-dropdown. It is a CUSTOM POPUP opened by `button[title="Choose Alerts"]`.
      * To select general categories: click the popup, wait briefly, then use the `check` action for `.high-alert label.filter_check_container` for High, `.medium-alert label.filter_check_container` for Medium, `.low-alert label.filter_check_container` for Low.
      * To select a specific alert type (e.g., "Geofence Entry Detected"): click the popup, use the `type_text` action on `.Alert-dropdown input[placeholder="Search"]` with the name of the alert type, and use the `check` action on the filtered checkbox selector: `.Alert-dropdown label:has-text("{value}")` (replacing `{value}` with the alert type name, e.g., `.Alert-dropdown label:has-text("Geofence Entry Detected")`).
      * After selecting alerts, close the popup by clicking `.Alert-dropdown .material-icons:has-text("close")`.
      * The Template filter is an ng-select with "tmp2" pre-selected by default. You MUST ALWAYS use the `select_option` action with target `ng-select[placeholder="Select Template"]` and value `template`. The framework will automatically clear "tmp2" and select "template". NEVER leave "tmp2" selected. NEVER skip this step.
    - FOR ALL OTHER ng-select DROPDOWNS: Use the `select_option` action with the target set to the ng-select element and the value set to the desired option text.
    - CAPTURING LIST/TABLE TOTAL COUNTS (CRITICAL FOR ALL PAGES):
      * If the user asks for the TOTAL number of records, vehicles, trips, or any items in ANY table (Master Data, Reports, Live, etc.), DO NOT use `count_elements` on table rows. Tables are paginated and will only count up to 50!
      * You MUST use the `get_text` action on `.mat-paginator-range-label` (or similar paginator element in site-map) with storeAs="totalRecords" to capture the total record count (the framework will automatically extract the total '2335' from '1 - 50 of 2335').
      * You can still use `count_elements` on `table tbody tr` with storeAs="visibleRows" ONLY if the user specifically asks how many rows are currently visible on the screen.
      * Then use `get_text` on `table[role="grid"] tbody tr` or `table tbody tr` with storeAs="firstRow" to capture the first row's content.
      * Assert totalRecords is not empty (assert_not_empty) to verify records loaded.
12. PAGE NAVIGATION — CRITICAL:
    - To navigate to any page (live, dashboard, geofence, reports, etc.), ALWAYS use the `navigate` action with the page's `url` from site-map.json as the target.
    - NEVER use `click` on sidebar nav links (like `.nav-link:has-text("Live")`) to navigate between pages. Sidebar text selectors are unreliable and often match the wrong element.
    - Example: To go to the live page, use: {"action": "navigate", "target": "http://103.123.173.50:8070/#/pages/tracking/tracking-summary"}
    - The executor will automatically localize the URL to the correct site.
    - After navigating, use `wait_for_element` to confirm the page loaded.
13. PERFORMANCE / LOAD-TIME MEASUREMENT AND DURATION CAPTURE:
    - If the user prompt asks "how much time does it take" or "calculate the time" or "load time" or "how much time it take" for a specific target transition/action/data load:
    - You MUST capture the exact start and end timestamps and calculate the duration in milliseconds as a Value Capture!
    - To do this, always generate these four steps precisely positioned around the target action and wait actions:
      1. BEFORE triggering the navigation/action to be measured:
         - action: `store_value`
         - target: `date.now()`
         - storeAs: `startTime`
         - description: `Record load start timestamp`
      2. Perform the navigation or click that triggers the load, followed by the mandatory wait step (e.g. click on menu, select options, wait_for_response/wait_for_element until data loads).
      3. IMMEDIATELY AFTER the wait step finishes and data is fully loaded:
         - action: `store_value`
         - target: `date.now()`
         - storeAs: `endTime`
         - description: `Record load end timestamp`
      4. Capture the calculated duration into a Value Capture:
         - action: `store_value`
         - target: `calculate_duration`
         - value: `endTime - startTime`
         - storeAs: `{variableName}` (Use a descriptive camelCase variable name representing the captured metric, e.g. `allVehiclesStatus` or `alertReportLoadTime`)
         - description: `Calculate load duration in milliseconds`

TEST CATEGORIES:
- value_comparison: Compare a value between two pages or locations. Steps: navigate → wait → capture → navigate → wait → capture → assert_equal
- auth_validation: Test login flows with valid/invalid credentials. Steps: attempt login → check result
- data_presence: Verify elements have data loaded. Steps: login → navigate → wait → read → assert_not_empty
- cross_site: Compare same metric across multiple sites. Steps: run same capture per site → compare
- filter_consistency: Same filter gives same results across pages. Steps: apply filter → capture → apply elsewhere → capture → assert_equal
"""


def _build_login_steps(site_id: str, base_url: str, username: str, password: str, start_id: int = 1) -> str:
    """Return the canonical OTP login step block as a JSON fragment string."""
    steps = [
        {
            "id": f"step_{start_id}",
            "action": "navigate",
            "target": f"{base_url}/#/auth/login",
            "value": None,
            "storeAs": None,
            "compareWith": None,
            "description": f"Navigate to {site_id} login page",
            "onFailure": "stop"
        },
        {
            "id": f"step_{start_id+1}",
            "action": "type_text",
            "target": "input[type='text'], input[name='username'], input[placeholder*='ser'], input.form-control",
            "value": username,
            "storeAs": None,
            "compareWith": None,
            "description": "Enter username",
            "onFailure": "screenshot"
        },
        {
            "id": f"step_{start_id+2}",
            "action": "type_text",
            "target": "input[type='password'], input[name='password']",
            "value": password,
            "storeAs": None,
            "compareWith": None,
            "description": "Enter password",
            "onFailure": "screenshot"
        },
        {
            "id": f"step_{start_id+3}",
            "action": "click",
            "target": "button.login_btn",
            "value": None,
            "storeAs": None,
            "compareWith": None,
            "description": "Click Send OTP button",
            "onFailure": "screenshot"
        },
        {
            "id": f"step_{start_id+4}",
            "action": "type_text",
            "target": "input#otp_Email",
            "value": "123456",
            "storeAs": None,
            "compareWith": None,
            "description": "Enter OTP (hardcoded 123456)",
            "onFailure": "screenshot"
        },
        {
            "id": f"step_{start_id+5}",
            "action": "click",
            "target": "button.login_btn",
            "value": None,
            "storeAs": None,
            "compareWith": None,
            "description": "Click Login button to submit OTP",
            "onFailure": "screenshot"
        },
        {
            "id": f"step_{start_id+6}",
            "action": "wait_for_element",
            "target": "nb-sidebar, app-aggregate-dashboard, nb-user",
            "value": None,
            "storeAs": None,
            "compareWith": None,
            "description": "Wait for dashboard/sidebar to confirm login success",
            "onFailure": "stop"
        },
    ]
    return json.dumps(steps, indent=2)


OUTPUT_SCHEMA = """{
  "testName": "string — short descriptive name",
  "category": "value_comparison | auth_validation | data_presence | cross_site | filter_consistency",
  "intent": "valid_login | invalid_login | data_present | data_absent | values_match | values_differ | ui_element_present | ui_element_absent | value_equals_expected | value_not_equals_expected",
  "expectedValue": "the value the user explicitly stated, or null if not specified",
  "description": "string — what this test verifies",
  "targetSites": ["jhs81", "jhs82"],
  "runParallel": false,
  "steps": [
    {
      "id": "step_1",
      "action": "navigate | login | click | check | uncheck | wait_for_element | wait_for_response | get_text | count_elements | assert_equal | assert_not_empty | assert_contains | assert_not_equal | type_text | select_option | screenshot | store_value | compare_values | select_date_range | assert_url_contains | assert_url_not_contains",
      "target": "CSS selector or URL or API endpoint pattern",
      "value": "text to type or expected value or null",
      "storeAs": "variable name or null",
      "compareWith": "variable name or null",
      "description": "plain English description of this step",
      "onFailure": "continue | stop | screenshot"
    }
  ],
  "expectedOutcome": "string — what success looks like",
  "failureMessage": "string — what to report on failure"
}"""


def build_prompt(
    situation: str,
    target_sites: List[str],
    site_map_json: str,
    recent_tests: List[dict],
    site_credentials: Dict[str, dict] = None,
) -> str:
    """Build the full prompt for Gemini."""

    recent_tests_section = ""
    if recent_tests:
        recent_names = [t.get("situation_description", "") for t in recent_tests[:10]]
        recent_tests_section = f"""
RECENT TEST CASES (avoid duplicating these):
{json.dumps(recent_names, indent=2)}
"""

    # Build credentials + login flow section
    creds_section = ""
    if site_credentials:
        creds_lines = []
        for site_id, creds in site_credentials.items():
            creds_lines.append(
                f"  {site_id}: URL={creds['url']}  username={creds['username']}  password={creds['password']}  OTP=123456"
            )
        creds_section = "SITE CREDENTIALS (use EXACTLY these — never invent credentials):\n" + "\n".join(creds_lines)

        # Show login flow example for the first target site
        first_site = target_sites[0] if target_sites else list(site_credentials.keys())[0]
        if first_site in site_credentials:
            c = site_credentials[first_site]
            login_steps_example = _build_login_steps(first_site, c["url"], c["username"], c["password"], start_id=1)
            creds_section += f"""

LOGIN FLOW (MANDATORY for valid_login and all non-login tests — use these exact 7 steps):
The app uses a TWO-STEP login: username+password → Send OTP → enter OTP → Login.
Step 4 clicks "Send OTP" (button.login_btn), step 6 clicks "Login" (button.login_btn again after OTP entry.
Example login steps for {first_site}:
{login_steps_example}

After these 7 steps the user is authenticated. Continue with test-specific steps from step_8 onward.

INVALID LOGIN FLOW (MANDATORY for invalid_login tests — do NOT use the 7-step flow above):
When testing with invalid credentials, OTP will NEVER be sent. The server rejects
invalid credentials at the Send OTP stage. Therefore you MUST NOT include OTP entry steps.
Use ONLY these steps for invalid login tests:
  step_1: navigate → to login page
  step_2: type_text → enter invalid username
  step_3: type_text → enter invalid password
  step_4: click → button.login_btn (Send OTP — will fail/show error with invalid creds)
  step_5: wait_for_element → wait for error message (.error-message, .alert-danger, [class*='error'], :has-text('Invalid'), :has-text('incorrect')) with onFailure: "continue"
  step_6: assert_url_contains → value: "login" (proves user was NOT redirected away)
Do NOT include: OTP input steps, second login button click, or wait_for dashboard.
Invalid credentials = no OTP field = those steps will always timeout and give false errors.
"""

    intent_rules = """
INTENT FIELD — MANDATORY, never omit this field:
- auth_validation with valid credentials   → intent: "valid_login"
- auth_validation with invalid credentials → intent: "invalid_login"
- data_presence verifying data exists      → intent: "data_present"
- data_presence verifying data is absent   → intent: "data_absent"
- value_comparison expecting values match  → intent: "values_match"
- value_comparison expecting values differ → intent: "values_differ"
- verifying a UI element is present        → intent: "ui_element_present"
- verifying a UI element is absent         → intent: "ui_element_absent"
- User states an exact expected value      → intent: "value_equals_expected"
  Set expectedValue field to what the user stated.
- User states value should NOT be X        → intent: "value_not_equals_expected"
  Set expectedValue field to the value it should not equal.

INVALID LOGIN — CRITICAL FLOW RULE:
For intent: "invalid_login", NEVER include the full 7-step OTP login flow.
Invalid credentials will be rejected at the Send OTP stage — the OTP input field
will NEVER appear. Including OTP steps causes timeouts that produce false "error"
results instead of the correct "fail" result.
Correct invalid_login flow: navigate → type invalid creds → click Send OTP →
wait for error message (onFailure: continue) → assert_url_contains "login".
Total: 5-6 steps maximum. No OTP steps.

LAST STEP RULE — MANDATORY:
The final step of every test MUST be an assertion that directly
proves the intent. Examples:
- invalid_login  → last step: assert_url_contains "login" (NOT an OTP or dashboard step)
- valid_login    → last step: assert_url_not_contains "login"
- data_present   → last step: assert_not_empty on the captured variable
- values_match   → last step: assert_equal or compare_values
- values_differ  → last step: assert_not_equal
Never end a test on a navigate, click, or wait step.

URL ASSERTIONS — use these as the final step for auth tests:
- After valid login:   assert_url_not_contains, value: "login"
- After invalid login: assert_url_contains, value: "login"
These are more reliable than element assertions for auth outcomes.
"""

    site_map_section = ""
    if site_map_json:
        site_map_section = f"SITE MAP (contains all available selectors and page structure):\n{site_map_json}\n"

    prompt = f"""{SYSTEM_CONTEXT}

{creds_section}

{site_map_section}
{recent_tests_section}

OUTPUT JSON SCHEMA (return exactly this structure):
{OUTPUT_SCHEMA}

{intent_rules}

USER REQUEST:
Situation: {situation}
Target Sites: {', '.join(target_sites)}

Generate the test plan now. Return ONLY the JSON object."""

    return prompt
