"""Adaptor-knowledge probes: 30 cases, one doc fact each.

Each case asks job_chat something whose correct answer lives in a specific,
named place in an adaptor's documentation, then asserts on the answer with
plain regexes. No LLM judge — a case passes or fails on a string match, so a
run is a scoreboard you read in one glance rather than 30 verdicts you read
in full.

`doc_ref` names the exact source of truth. When a case fails, that is where
the missing information lives; it is the spec for whatever retrieval method
you are building.

Fields
------
group     Which doc location the case probes. Also the pytest sub-id.
adaptor   Full specifier, pinned to a version on purpose. Version-sensitive
          cases in the `version` group depend on the exact pin.
prompt    The user's message.
expression  Optional starting job code, as if already in the editor.
target    Where the assertions look:
            "code" — the suggested code, plus any fenced blocks in the reply.
            "text" — the whole reply.
          Use "code" whenever the case asks for code; prose about a key name
          ("you could pass text:...") would otherwise trip the `forbid` list.
expect    Regexes, at least one must match. Empty means "nothing required".
forbid    Regexes, none may match.
doc_ref   Where the answer is documented. Free text, shown on failure.
why       What the model is expected to get wrong, and why.

All cases run with suggest_code=True. That is what Lightning sends, and it
keeps every case on one prompt path (suggest_code=False builds a different
prompt via old_prompt.py, which would confound the results).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Case:
    id: str
    group: str
    adaptor: str
    prompt: str
    doc_ref: str
    why: str
    expression: str | None = None
    target: str = "code"
    expect: list[str] = field(default_factory=list)
    forbid: list[str] = field(default_factory=list)
    empty_target_passes: bool = False


# --------------------------------------------------------------------------
# A. signatures — the function list job_chat already injects today.
# These are controls. They SHOULD pass. If one fails, the baseline is worse
# than we think and that is worth knowing before measuring any improvement.
# --------------------------------------------------------------------------

SIGNATURES = [
    Case(
        id="sig.gmail-send-function",
        group="signatures",
        adaptor="@openfn/language-gmail@3.2.0",
        prompt="Which function do I use to send an email with this adaptor? Just name it.",
        target="text",
        expect=[r"sendMessage"],
        forbid=[r"\bsendEmail\b", r"\bsendMail\b"],
        doc_ref="Functions > sendMessage (in the injected signature list)",
        why="Control: the signature list already contains sendMessage(message).",
    ),
    Case(
        id="sig.dhis2-destroy-function",
        group="signatures",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="What function deletes a resource in DHIS2? Just name it.",
        target="text",
        expect=[r"\bdestroy\b"],
        forbid=[r"\bdelete\(", r"\bremove\("],
        doc_ref="Functions > destroy (in the injected signature list)",
        why="Control: destroy() is in the signature list; 'delete' is the natural guess.",
    ),
    Case(
        id="sig.http-request-function",
        group="signatures",
        adaptor="@openfn/language-http@7.3.2",
        prompt="I need to send a HEAD request. Which function supports an arbitrary HTTP method?",
        target="text",
        expect=[r"\brequest\b"],
        forbid=[r"\bhead\("],
        doc_ref="Functions > request (in the injected signature list)",
        why="Control: request(method, path, options) is in the signature list.",
    ),
]


# --------------------------------------------------------------------------
# B. Functions section — parameter names, order and examples. The signature
# gives bare parameter names; everything that disambiguates them is dropped.
# --------------------------------------------------------------------------

FUNCTIONS = [
    Case(
        id="fn.http-post-data-positional",
        group="functions",
        adaptor="@openfn/language-http@7.3.2",
        prompt="POST the records in state.data to /patients as JSON.",
        expect=[r"post\("],
        forbid=[r"body\s*:"],
        doc_ref="Functions > post — post(path, data, options); data is positional in 7.x",
        why="In 6.x the payload went in an options object as `body`. The v7 "
            "signature post(path, data, options) does not reveal that `body:` is now wrong.",
    ),
    Case(
        id="fn.dhis2-get-no-callback",
        group="functions",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="Fetch all trackedEntities for program IpHINAT79UW and log how many came back.",
        expect=[r"get\("],
        forbid=[r"callback"],
        doc_ref="Functions > get — get(path, params); callbacks removed in 7.0.0",
        why="get(path, params) does not say callbacks were removed. Older DHIS2 "
            "job code passed a callback as the last argument.",
    ),
    Case(
        id="fn.salesforce-create-takes-array",
        group="functions",
        adaptor="@openfn/language-salesforce@9.1.5",
        prompt="Create three Contact records from state.contacts in a single call.",
        expect=[r"create\("],
        forbid=[r"each\s*\("],
        doc_ref="Functions > create — create(sObjectName, records); records is an Array",
        why="The signature says `records` but not that it accepts an array, so the "
            "model reaches for each() to loop instead of one bulk-ish call.",
    ),
    Case(
        id="fn.gmail-getcontents-query-key",
        group="functions",
        adaptor="@openfn/language-gmail@3.2.0",
        prompt="Fetch the messages whose subject is 'weekly report'.",
        expect=[r"query\s*:"],
        # NOT `subject:` — that's legitimate Gmail search syntax *inside* the
        # query string, exactly as the docs example writes it.
        forbid=[r"\bsearch\s*:", r"\bq\s*:", r"\bfilter\s*:"],
        doc_ref="Functions > getContentsFromMessages, Example: query: 'subject:my+test+message'",
        why="getContentsFromMessages(options) hides that the search string goes "
            "under `query` in Gmail search syntax.",
    ),
    Case(
        id="fn.gmail-getcontents-contents-key",
        group="functions",
        adaptor="@openfn/language-gmail@3.2.0",
        prompt="Download the .xlsx attachment from messages received after 2026/07/01.",
        expect=[r"contents\s*:"],
        forbid=[r"attachments\s*:"],
        doc_ref="Functions > getContentsFromMessages, Example with contents: [{type:'file', file:/\\.xlsx$/}]",
        why="`attachments` is the correct key on sendMessage but wrong here — a "
            "plausible cross-contamination when neither option object is documented.",
    ),
    Case(
        id="fn.dhis2-create-resource-first-arg",
        group="functions",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="Create a new dataValueSet from state.payload.",
        expect=[r"create\(\s*['\"]"],
        forbid=[r"create\(\s*\{"],
        doc_ref="Functions > create — create(path, data, params); path is a resource-type string",
        why="`create(path, data)` reads ambiguously; the model may pass a single "
            "config object instead of a resource string first.",
    ),
]


# --------------------------------------------------------------------------
# C. Interfaces — @typedef property names. Dropped entirely at ingest by
# load_adaptor_docs.filter_function_docs, so none of this reaches the prompt.
# --------------------------------------------------------------------------

INTERFACES = [
    Case(
        id="iface.gmail-sendmessage-body",
        group="interfaces",
        adaptor="@openfn/language-gmail@3.2.0",
        prompt="Email a summary of state.failed to data-team@example.org with subject 'Nightly sync failures'.",
        expect=[r"\bbody\s*:"],
        forbid=[r"\btext\s*:", r"\bmessage\s*:", r"\bhtml\s*:", r"\bcontent\s*:"],
        doc_ref="Interfaces > SendMessageOptions > body",
        why="The reported bug. Nodemailer/SendGrid priors supply `text` or `message`.",
    ),
    Case(
        id="iface.gmail-attachment-filename",
        group="interfaces",
        adaptor="@openfn/language-gmail@3.2.0",
        prompt="Send report.csv to ops@example.org, attaching the CSV string in state.csv.",
        expect=[r"filename\s*:"],
        # `forbid` is case-sensitive, so `fileName` here would be a distinct
        # (wrong) identifier — but `\bname\s*:` already covers the camelCase
        # variant's tail, and listing it separately only invites confusion.
        forbid=[r"\bname\s*:", r"\bpath\s*:"],
        doc_ref="Interfaces > SendMessageOptions > attachments: Array<{filename, content}>",
        why="`name` and `path` are the common conventions in other mail libraries.",
    ),
    Case(
        id="iface.http-query-not-params",
        group="interfaces",
        adaptor="@openfn/language-http@7.3.2",
        prompt="GET /patients with a query string of page=2 and size=50.",
        expect=[r"query\s*:"],
        forbid=[r"params\s*:", r"searchParams\s*:", r"qs\s*:"],
        doc_ref="Interfaces > RequestOptions > query",
        why="axios and requests both call this `params`, and 6.x used `params` too.",
    ),
    Case(
        id="iface.http-parseas",
        group="interfaces",
        adaptor="@openfn/language-http@7.3.2",
        prompt="GET /export.csv and keep the response as plain text rather than parsing it as JSON.",
        expect=[r"parseAs"],
        forbid=[r"responseType\s*:", r"\bformat\s*:", r"\bparse\s*:"],
        doc_ref="Interfaces > RequestOptions > parseAs",
        why="`responseType` is the axios name for the same concept.",
    ),
    Case(
        id="iface.salesforce-bulk-failonerror",
        group="interfaces",
        adaptor="@openfn/language-salesforce@9.1.5",
        prompt="Bulk insert state.rows as Contact records, but don't abort the whole job if some rows fail.",
        expect=[r"failOnError"],
        forbid=[r"continueOnError", r"allOrNone", r"ignoreErrors"],
        doc_ref="Interfaces > Bulk1Options / Bulk2LoadOptions > failOnError",
        why="`allOrNone` is the Salesforce API's own name for this, so the model "
            "reaches for the platform term over the adaptor's.",
    ),
    Case(
        id="iface.openmrs-getoptions-pagesize",
        group="interfaces",
        adaptor="@openfn/language-openmrs@5.4.2",
        prompt="Fetch patients 100 at a time.",
        expect=[r"pageSize", r"\bmax\s*:"],
        forbid=[r"\blimit\s*:", r"\bcount\s*:", r"perPage"],
        doc_ref="Interfaces > GetOptions > pageSize, max",
        why="`limit` is the near-universal convention for this parameter.",
    ),
    Case(
        id="iface.dhis2-apiversion-option",
        group="interfaces",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="Call GET on dataElements but pin this one request to API version 40.",
        expect=[r"apiVersion"],
        forbid=[r"\bversion\s*:", r"\bapi_version\s*:"],
        doc_ref="Interfaces > RequestOptions > apiVersion",
        why="Nothing in `get(path, params)` hints that a per-request apiVersion exists.",
    ),
]


# --------------------------------------------------------------------------
# D. Namespaces — operations under `## <namespace>` on the docs page. Present
# in 31 of 107 adaptors and never injected today.
# --------------------------------------------------------------------------

NAMESPACES = [
    Case(
        id="ns.dhis2-tracker-import",
        group="namespaces",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="Import the tracked entities in state.payload through the tracker endpoint.",
        expect=[r"tracker\.import"],
        forbid=[r"create\(\s*['\"]tracker"],
        doc_ref="## tracker > tracker.import",
        why="tracker.* is the documented route; create('tracker') explicitly throws in 7.x+.",
    ),
    Case(
        id="ns.dhis2-tracker-import-strategy",
        group="namespaces",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="Import state.payload into the tracker, creating new records and updating existing ones.",
        expect=[r"CREATE_AND_UPDATE"],
        doc_ref="## tracker > tracker.import — import(strategy, payload, options); "
                "strategy is CREATE | UPDATE | CREATE_AND_UPDATE | DELETE",
        why="The strategy is the first positional argument and its allowed values "
            "appear only in the namespace section.",
    ),
    Case(
        id="ns.salesforce-bulk2-insert",
        group="namespaces",
        adaptor="@openfn/language-salesforce@9.1.5",
        prompt="Bulk load 50,000 Contact records from state.rows using the Bulk API.",
        expect=[r"bulk2\.insert", r"bulk1\.insert"],
        forbid=[r"(?<![12])\bbulk\("],
        doc_ref="## bulk2 > bulk2.insert (and ## bulk1)",
        why="The old top-level bulk() was split into bulk1/bulk2 namespaces in 9.x.",
    ),
    Case(
        id="ns.dhis2-util-findattributevalue",
        group="namespaces",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="Inside an fn block, pull the 'first name' attribute off state.data.",
        expect=[r"util\.findAttributeValue"],
        doc_ref="## util > util.findAttributeValue",
        why="Moved from top level into the util namespace in 7.0.0.",
    ),
    Case(
        id="ns.http-util-uuid",
        group="namespaces",
        adaptor="@openfn/language-http@7.3.2",
        prompt="Generate a UUID to use as an idempotency key on a POST to /orders.",
        expect=[r"util\.uuid"],
        forbid=[r"crypto\.randomUUID", r"uuidv4", r"require\("],
        doc_ref="## util > util.uuid",
        why="The adaptor ships a uuid helper; without it the model hand-rolls one "
            "or reaches for a Node API that isn't available in the job DSL.",
    ),
    Case(
        id="ns.salesforce-http-request",
        group="namespaces",
        adaptor="@openfn/language-salesforce@9.1.5",
        prompt="Call a custom Apex REST endpoint at /services/apexrest/MyService using the Salesforce session.",
        expect=[r"http\.(get|post|request)"],
        doc_ref="## http > http.get / http.post / http.request",
        why="Without the namespace the model suggests a raw fetch or the http "
            "adaptor instead of Salesforce's authenticated http.* passthrough.",
    ),
]


# --------------------------------------------------------------------------
# E. Other sections — configuration-schema and README. Neither is on the docs
# page and neither is fetched today.
# --------------------------------------------------------------------------

OTHER = [
    Case(
        id="other.dhis2-config-apiversion",
        group="other",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="Where does the DHIS2 API version come from if I don't pass one per request?",
        target="text",
        expect=[r"apiVersion"],
        forbid=[r"hard.?cod", r"in your job code"],
        doc_ref="configuration-schema > properties.apiVersion (credential field)",
        why="apiVersion is a credential field, not a job-code concern. The model "
            "has never seen the credential schema.",
    ),
    Case(
        id="other.salesforce-config-securitytoken",
        group="other",
        adaptor="@openfn/language-salesforce@9.1.5",
        prompt="My Salesforce credential keeps failing to authenticate from a new IP. What's likely missing?",
        target="text",
        expect=[r"securityToken", r"security token"],
        doc_ref="configuration-schema > properties.securityToken",
        why="The fix is a specific named credential field the model cannot see.",
    ),
    Case(
        id="other.gmail-attachment-archive",
        group="other",
        adaptor="@openfn/language-gmail@3.2.0",
        prompt="Pull the CSV out of the zipped attachment on messages with subject 'daily export'.",
        expect=[r"archive"],
        forbid=[r"unzip", r"jszip", r"require\("],
        doc_ref="Interfaces > MessageContent > archive; README > getContentsFromMessages "
                "> options.contents > 'Attachment: archived file'",
        why="The adaptor unpacks zips natively via type:'archive'. Without that the "
            "model suggests an unzip library that isn't available.",
    ),
]


# --------------------------------------------------------------------------
# F. Versions — the same question has different right answers per version.
# Each pin is a real breaking change, confirmed against the adaptor's own
# changelog and against published type declarations for both versions.
# --------------------------------------------------------------------------

VERSIONS = [
    Case(
        id="ver.http6-post-body-option",
        group="version",
        adaptor="@openfn/language-http@6.5.4",
        prompt="POST the records in state.data to /patients as JSON.",
        expect=[r"body\s*:"],
        doc_ref="http 6.x: post(path, options) with the payload under options.body. "
                "Changed in 7.0.0 — see changelog 7.0.0 'Updated put, patch and post signatures'",
        why="Inverse of fn.http-post-data-positional. On 6.x the `body:` key is "
            "correct; a latest-only view of the docs makes it look wrong.",
    ),
    Case(
        id="ver.dhis2-6-findattributevalue-toplevel",
        group="version",
        adaptor="@openfn/language-dhis2@6.3.4",
        prompt="Inside an fn block, pull the 'first name' attribute off state.data.",
        expect=[r"findAttributeValue"],
        forbid=[r"util\.findAttributeValue"],
        doc_ref="dhis2 6.x: findAttributeValue is top-level. Moved to util.* in 7.0.0 "
                "— see changelog 7.0.0 'Many non-operation functions have moved to the util. namespace'",
        why="Inverse of ns.dhis2-util-findattributevalue. On 6.x the util. prefix is wrong.",
    ),
    Case(
        id="ver.dhis2-8-discover-removed",
        group="version",
        adaptor="@openfn/language-dhis2@8.2.1",
        prompt="I want to use discover() to inspect the schema for dataElements before I post. How do I call it?",
        # Asserted as a negative on purpose. "It's gone" has unbounded phrasings
        # — removed, isn't available, doesn't have one — and chasing them
        # produced two false failures before this rewrite. What actually
        # matters is bounded: the model must not emit a discover call.
        # Answering in prose with no code at all is a pass.
        target="code",
        expect=[],
        forbid=[r"discover\s*\("],
        empty_target_passes=True,
        doc_ref="dhis2 changelog 7.0.0: 'The discover() function has been removed.'",
        why="The model should say it's gone rather than invent a call signature for it.",
    ),
    Case(
        id="ver.salesforce4-bulk-toplevel",
        group="version",
        adaptor="@openfn/language-salesforce@4.8.6",
        prompt="Bulk load 50,000 Contact records from state.rows using the Bulk API.",
        expect=[r"\bbulk\("],
        forbid=[r"bulk1\.", r"bulk2\."],
        doc_ref="salesforce 4.x: top-level bulk(). Split into bulk1.*/bulk2.* namespaces later.",
        why="Inverse of ns.salesforce-bulk2-insert. On 4.x the namespaced calls do not exist.",
    ),
    Case(
        id="ver.gmail2-no-getmessagebyid",
        group="version",
        adaptor="@openfn/language-gmail@2.1.2",
        prompt="Fetch one specific message using the Gmail message id in state.data.messageId.",
        expect=[r"getContentsFromMessages"],
        forbid=[r"getMessageById"],
        doc_ref="gmail: getMessageById was added in 3.1.0. It does not exist in 2.x.",
        why="A latest-only view offers a function this version does not have.",
    ),
]


ALL_CASES: list[Case] = SIGNATURES + FUNCTIONS + INTERFACES + NAMESPACES + OTHER + VERSIONS

GROUPS = ["signatures", "functions", "interfaces", "namespaces", "other", "version"]
