import time
import sentry_sdk
from guidelines import render_for_prompt
from util import create_logger, ApolloError, AdaptorSpecifier, get_db_connection
from .retrieve_docs import retrieve_knowledge
from search_adaptor_docs.search_adaptor_docs import fetch_signatures

logger = create_logger("job_chat.prompt")

system_role = """
You are a software engineer helping a non-expert user write a job for our platform.
We are OpenFn (Open Function Group) the world's leading digital public good for workflow automation.

Where reasonable, assume questions are related to workflow automation, 
professional platforms or programming. You may provide general information around these topics, 
e.g. general programming assistance unrelated to job writing.
If a question is entirely irrelevant, do not answer it.

You MUST keep your responses concise. Do not explain your answers unless
the user explicitly asks you to. When generating code, always use the simplest
possible code to achieve the task.

Do not thank the user or be obsequious. Address the user directly.

You are embedded in our app for building workflows. Our app will provide the
history of each chat session to you. Our app will send you the user's code and
tell you which adaptor (library) is being used.
Chat sessions are saved to each job, so any user who can see the workflow can see the chat.

Your chat panel is embedded in a web based IDE, which lets users build a Workflow with a number
of steps (or jobs). There is a code editor next to you, which users can copy and paste code into.
Users must set or select an input in the Input tab, and can then run the current job.

Users can Flag any answers that are not helpful, which will help us build a better prompt for you.
"""

job_writing_summary = f"\n{render_for_prompt('job')}\n"


class Context:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

    def has(self, key):
        return hasattr(self, key) and getattr(self, key) is not None


def generate_system_message(context_dict, search_results, download_adaptor_docs=True):
    context = context_dict if isinstance(context_dict, Context) else Context(**(context_dict or {}))

    message = [system_role]
    message.append(f"<job_writing_guide>{job_writing_summary}</job_writing_guide>")
    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if search_results:
        search_results = format_search_results(search_results)
        message.append(f"<retrieved_documentation>Search results for the user query, which may or may not be relevant:\n\n{search_results}</retrieved_documentation>")
        message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if context.has("adaptor"):
        adaptor_string = (
            f"<adaptor>The user is using the OpenFn {context.adaptor} adaptor. Use functions provided by its API.\n\n"
        )

        try:
            conn = get_db_connection()

            try:
                try:
                    adaptor = AdaptorSpecifier(context.adaptor)

                    signatures = fetch_signatures(adaptor, conn, auto_load=download_adaptor_docs)

                    if signatures:
                        adaptor_string += "These are the available functions in the adaptor:\n\n"
                        for func_name, signature in signatures.items():
                            adaptor_string += f"{signature}\n"
                    else:
                        msg = f"No adaptor signatures returned from search_adaptor_docs for {adaptor.specifier}"
                        logger.warning(msg)
                        sentry_sdk.capture_message(msg, level="warning")
                        sentry_sdk.set_context("adaptor_context", {
                            "adaptor_name": adaptor.name,
                            "version": adaptor.version,
                            "parsed_from": context.adaptor
                        })
                except Exception as parse_error:
                    msg = f"Failed to parse adaptor string '{context.adaptor}': {parse_error}"
                    logger.warning(msg)
                    sentry_sdk.capture_message(msg, level="warning")
                    sentry_sdk.set_context("adaptor_context", {
                        "parsed_from": context.adaptor,
                        "error": str(parse_error)
                    })
            finally:
                conn.close()
        except ApolloError as e:
            logger.warning(f"Database not available: {e.message}")
            adaptor_string += "The user is using an OpenFn Adaptor to write the job."
        except Exception as e:
            logger.warning(f"Could not fetch adaptor docs for {context.adaptor}: {e}")
            adaptor_string += "The user is using an OpenFn Adaptor to write the job."

        if len(adaptor_string) >= 40000:
          adaptor_string = adaptor_string[:40000]
          adaptor_string += "(...)"

        adaptor_string += "</adaptor>"

        message.append(adaptor_string)
    else:
        message.append("The user is using an OpenFn Adaptor to write the job.")

    message.append({"type": "text", "text": ".", "cache_control": {"type": "ephemeral"}})

    if context.has("expression"):
        message.append(f"<user_code>{context.expression}</user_code>")

    if context.has("input"):
        message.append(f"<input>The user's input data is :\n\n```{context.input}```</input>")

    if context.has("output"):
        message.append(f"<output>The user's last output data was :\n\n```{context.output}```</output>")

    if context.has("log"):
        message.append(f"<log>The user's last log output was :\n\n```{context.log}```</log>")

    return list(map(lambda text: text if isinstance(text, dict) else {"type": "text", "text": text}, message))

def format_search_results(search_results):
    return '\n'.join([
        f'search result: "{result.get("text")}", source: "{result.get("metadata", {}).get("doc_title", "")} {result.get("medatada", {}).get("docs_type", "")}"'
        for result in search_results
    ])

def build_old_prompt(content, history, context, rag=None, api_key=None, download_adaptor_docs=True, refresh_rag=False):
    retrieved_knowledge = {
        "search_results": [],
        "search_results_sections": [],
        "search_queries": [],
        "config_version": "",
        "prompts_version": "",
        "usage": {
            "needs_docs": {},
            "generate_queries": {}
        }
    }

    # Run RAG if: (a) no RAG data provided, OR (b) refresh_rag flag is True
    if rag and not refresh_rag:
        retrieved_knowledge = rag
    else:
      try:
          retrieved_knowledge = retrieve_knowledge(
              content=content,
              history=history,
              code=context.get("expression", ""),
              adaptor=context.get("adaptor", ""),
              api_key=api_key
          )
      except Exception as e:
          logger.error(f"Error retrieving knowledge: {str(e)}")

    system_message = generate_system_message(
        context_dict=context,
        search_results=retrieved_knowledge.get("search_results") if retrieved_knowledge is not None else None,
        download_adaptor_docs=download_adaptor_docs)

    prompt = []
    prompt.extend(history)
    prompt.append({"role": "user", "content": content})

    return (system_message, prompt, retrieved_knowledge)