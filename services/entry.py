import argparse
import json
import os
import uuid

import sentry_sdk
from dotenv import load_dotenv
from util import ApolloError, install_log_masking, set_apollo_port

load_dotenv()

# Langfuse: init after load_dotenv so env vars are available, before any Anthropic client is created
from opentelemetry.instrumentation.anthropic import AnthropicInstrumentor
from opentelemetry.instrumentation.threading import ThreadingInstrumentor

AnthropicInstrumentor().instrument()
ThreadingInstrumentor().instrument()

from langfuse import Langfuse
from langfuse.span_filter import is_default_export_span
from langfuse_util import mask_secrets


def _should_export_span(span):
    """Drop spans marked as tracing-disabled (user has not opted in)."""
    attrs = getattr(span, "attributes", None) or {}
    if attrs.get("langfuse.trace.metadata.tracing_disabled") == "true":
        return False
    return is_default_export_span(span)


langfuse = Langfuse(
    should_export_span=_should_export_span,
    mask=mask_secrets,
    release=os.getenv("APOLLO_VERSION", "unknown"),
)

env = os.getenv('ENVIRONMENT', 'unknown')
trace_rates = {
    'development': 1,
    'staging': 0.05,
    'production': 0.03,
    'unknown': 0.0,
    }

def _scrub_event(event: dict, _hint: dict) -> dict:
    """Mask keys in what Sentry is about to send.

    Sentry scrubs frame locals by name, but not the exception message, a
    set_context payload, or a breadcrumb - and services raise
    ApolloError(500, str(e)) with the request in scope. The whole event rather
    than a list of sections, so a section nobody thought of is covered too.
    """
    return mask_secrets(event)


sentry_sdk.init(
    dsn=os.getenv('SENTRY_DSN'),
    environment=env,
    sample_rate=1.0,
    traces_sample_rate=trace_rates.get(env, 0.0),
    enable_tracing=True,
    auto_enabling_integrations=False,
    # Frame locals are off. `before_send` scrubs by field name and value shape,
    # but a stack frame carries whole objects: `data` holds `workflow_yaml` and
    # `history`, and `preserved_values` on the workflow_chat stack is the
    # placeholder-to-job-code map for every step. Sentry also walks
    # `__cause__`/`__context__`, so a handler that logs only an exception type
    # and re-raises still ships the original frame chain. Redacting job code
    # from the prompt and then posting it to Sentry is the same leak.
    include_local_variables=False,
    before_send=_scrub_event,
    # before_send covers error events only, and tracing is on.
    before_send_transaction=_scrub_event,
)

def call(
    service: str, *, input_path: str | None = None, output_path: str | None = None, apollo_port: int | None = None,
) -> dict:
    """
    Dynamically imports a module and invokes its main function with input data.

    :param service: The name of the service/module to invoke
    :param input_path: Optional path to the input JSON file
    :param output_path: Optional path to write the output JSON file
    :param apollo_port: Optional port number for Apollo server
    :return: Result from the service as a dictionary
    """
    if apollo_port is not None:
        set_apollo_port(apollo_port)

    module_name = f"{service}.{service}"

    data = {}
    if input_path:
        try:
            with open(input_path) as f:
                data = json.load(f)
        except FileNotFoundError as e:
            # The path is the server's own, so it is for the log, not the
            # caller.
            sentry_sdk.capture_exception(e)
            return _finish(
                ApolloError(
                    code=500, message="Input file not found", type="INTERNAL_ERROR",
                ).to_dict(),
                output_path,
            )
        except json.JSONDecodeError as e:
            sentry_sdk.capture_exception(e)
            return _finish(
                ApolloError(
                    code=500, message="Invalid JSON input", type="INTERNAL_ERROR",
                ).to_dict(),
                output_path,
            )

    try:
        m = __import__(module_name, fromlist=["main"])

        # Again here, after every import has had its chance to install a
        # handler of its own. Some libraries add one that writes to stderr,
        # which the bridge forwards to the caller line for line.
        install_log_masking()

        result = m.main(data)
    except ModuleNotFoundError as e:
        sentry_sdk.capture_exception(e)
        result = ApolloError(
            # Reached only when the service failed to build an ApolloError, and
            # losing the message leaves the caller with nothing at all.
            code=500, message=str(e), type="INTERNAL_ERROR",  # safe-error-text: top-level fallback
        ).to_dict()
    except ApolloError as e:
        sentry_sdk.capture_exception(e)
        result = e.to_dict()
    except Exception as e:
        sentry_sdk.capture_exception(e)
        result = ApolloError(
            # As above.
            code=500, message=str(e), type="INTERNAL_ERROR",  # safe-error-text: top-level fallback
        ).to_dict()

    langfuse.flush()

    return _finish(result, output_path)


def _finish(result: dict, output_path: str | None) -> dict:
    """Mask, write the result where the caller expects it, then hand it back.

    Every path out of `call` comes through here, which buys two things. The
    output file is always written, so the bridge can read an empty one as the
    run having died rather than as a polite failure. And a value the server put
    on the payload cannot leave down a branch someone forgot: most services
    catch broadly and rewrap as `ApolloError(500, str(e))`, so masking
    per-branch would miss the one nearly all of them take.
    """
    result = mask_secrets(result)

    if output_path:
        with open(output_path, "w") as f:
            json.dump(result, f)

    return result


def main():
    """
    Entry point when the script is run directly.
    Reads arguments from stdin and calls the appropriate service.
    """
    parser = argparse.ArgumentParser(description="OpenFn Apollo Service Runner")
    parser.add_argument("service", help="Name of the service to run")
    parser.add_argument("--input", "-i", help="Path to input JSON file")
    parser.add_argument("--output", "-o", help="Path to output JSON file (auto-generated if not provided)")
    parser.add_argument("--port", "-p", type=int, help="Apollo server port number")

    args = parser.parse_args()

    sentry_sdk.set_tag("service", args.service)

    if not args.output:
        id = uuid.uuid4()
        args.output = f"tmp/data/{id}.json"
        print(f"Result will be output to {args.output}")

    if args.port:
        print(f"Setting Apollo port to {args.port}")
        set_apollo_port(args.port)

    print(f"Calling services/{args.service} ...")
    print()

    result = call(service=args.service, input_path=args.input, output_path=args.output, apollo_port=args.port)

    print()
    print("Done!")
    print(result)

    return result


if __name__ == "__main__":
    main()
