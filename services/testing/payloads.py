"""Payload builders for acceptance tests.

The function signatures are deliberately closer to user-facing concepts
(`current_job_code`, `current_adaptor`, `previous_page`) than the underlying
JSON shape (`context.expression`, `context.adaptor`, `meta.last_page`). The
goal is that a contributor who has not memorised every service's payload spec
can still author a test from these signatures alone.

Each builder is "set if not None" — pass only the fields a test cares about.
"""

from typing import Any, Optional


def build_global_chat_payload(
    *,
    user_message: str,
    history: Optional[list[dict]] = None,
    workflow_yaml: Optional[str] = None,
    page: Optional[str] = None,
    attachments: Optional[list[dict]] = None,
    api_key: Optional[str] = None,
    stream: bool = False,
) -> dict:
    """Build a global_chat service payload.

    global_chat is the orchestrator entry point — it routes to workflow_chat,
    job_chat, or the planner depending on context. For workflow scenarios pass
    `workflow_yaml`; for job-code scenarios the planner will extract the
    relevant job from the YAML using `page`.
    """
    payload: dict[str, Any] = {
        "content": user_message,
        "history": history or [],
    }
    if workflow_yaml is not None:
        payload["workflow_yaml"] = workflow_yaml
    if page is not None:
        payload["page"] = page
    if attachments is not None:
        payload["attachments"] = attachments
    if api_key is not None:
        payload["api_key"] = api_key
    if stream:
        payload["options"] = {"stream": True}
    return payload


def build_workflow_chat_payload(
    *,
    user_message: Optional[str] = None,
    existing_yaml: str = "",
    history: Optional[list[dict]] = None,
    errors: Optional[str] = None,
    current_page: Optional[str] = None,
    previous_page: Optional[dict] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Build a workflow_chat service payload.

    Args:
        user_message: The user's latest message. Required unless `errors` is set.
        existing_yaml: Current workflow YAML the user is editing.
        history: Chat history as a list of {role, content} dicts.
        errors: An error string. When set, replaces `content` to put the
            service in error-correction mode.
        current_page: The page the user is currently on (e.g. workflow name).
            Threaded into `context.page_name`.
        previous_page: Where the user navigated from. Threaded into
            `meta.last_page`. Shape: {"type": "job_code" | "workflow", "name": str, "adaptor": str}.
        api_key: Optional Anthropic API key override.
    """
    payload: dict[str, Any] = {
        "existing_yaml": existing_yaml,
        "history": history or [],
    }
    if user_message is not None:
        payload["content"] = user_message
    if errors is not None:
        payload["errors"] = errors

    context: dict[str, Any] = {}
    if current_page is not None:
        context["page_name"] = current_page
    if context:
        payload["context"] = context

    meta: dict[str, Any] = {}
    if previous_page is not None:
        meta["last_page"] = previous_page
    if meta:
        payload["meta"] = meta

    if api_key is not None:
        payload["api_key"] = api_key
    return payload


def build_job_chat_payload(
    *,
    user_message: str,
    history: Optional[list[dict]] = None,
    current_job_code: Optional[str] = None,
    current_adaptor: Optional[str] = None,
    project_adaptors: Optional[list[str]] = None,
    current_page: Optional[str] = None,
    project_id: Optional[str] = None,
    job_id: Optional[str] = None,
    input_data: Any = None,
    output_data: Any = None,
    log_data: Any = None,
    rag_results: Optional[list[dict]] = None,
    rag_queries: Optional[list[str]] = None,
    previous_page: Optional[dict] = None,
    suggest_code: Optional[bool] = None,
    api_key: Optional[str] = None,
    stream: Optional[bool] = None,
    download_adaptor_docs: Optional[bool] = None,
) -> dict:
    """Build a job_chat service payload.

    Args:
        user_message: The user's latest message.
        history: Chat history as a list of {role, content} dicts.
        current_job_code: The job code currently in the editor. → context.expression
        current_adaptor: The adaptor specifier (e.g. "@openfn/language-http@6.5.4"). → context.adaptor
        project_adaptors: Other adaptors used in the project. → context.adaptors
        current_page: Current page / job name. → context.page_name
        project_id: → context.projectId
        job_id: → context.jobId
        input_data / output_data / log_data: Sample data the user has available.
        rag_results: Pre-injected RAG search results. → meta.rag.search_results
        rag_queries: Pre-injected RAG search queries. → meta.rag.search_queries
        previous_page: Where the user navigated from. → meta.last_page
        suggest_code: Enable code-suggestion mode (returns suggested_code in response).
        api_key: Optional Anthropic API key override.
        stream: Enable streaming.
        download_adaptor_docs: Whether to load adaptor docs (default True in service).
    """
    payload: dict[str, Any] = {
        "content": user_message,
        "history": history or [],
    }

    context: dict[str, Any] = {}
    if current_job_code is not None:
        context["expression"] = current_job_code
    if current_adaptor is not None:
        context["adaptor"] = current_adaptor
    if project_adaptors is not None:
        context["adaptors"] = project_adaptors
    if current_page is not None:
        context["page_name"] = current_page
    if project_id is not None:
        context["projectId"] = project_id
    if job_id is not None:
        context["jobId"] = job_id
    if input_data is not None:
        context["input"] = input_data
    if output_data is not None:
        context["output"] = output_data
    if log_data is not None:
        context["log"] = log_data
    if context:
        payload["context"] = context

    meta: dict[str, Any] = {}
    if rag_results is not None or rag_queries is not None:
        rag: dict[str, Any] = {}
        if rag_results is not None:
            rag["search_results"] = rag_results
        if rag_queries is not None:
            rag["search_queries"] = rag_queries
        meta["rag"] = rag
    if previous_page is not None:
        meta["last_page"] = previous_page
    if meta:
        payload["meta"] = meta

    if api_key is not None:
        payload["api_key"] = api_key
    if suggest_code is not None:
        payload["suggest_code"] = suggest_code
    if stream is not None:
        payload["stream"] = stream
    if download_adaptor_docs is not None:
        payload["download_adaptor_docs"] = download_adaptor_docs
    return payload
