import sys
import json
import uuid
import argparse
from dotenv import load_dotenv
from util import set_apollo_port, ApolloError

load_dotenv()


def call(
    service: str, *, input_path: str | None = None, output_path: str | None = None, apollo_port: int | None = None
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
            with open(input_path, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            return ApolloError(code=500, message=f"Input file not found: {input_path}", type="INTERNAL_ERROR").to_dict()
        except json.JSONDecodeError:
            return ApolloError(code=500, message="Invalid JSON input", type="INTERNAL_ERROR").to_dict()

    try:
        m = __import__(module_name, fromlist=["main"])
        result = m.main(data)
    except ModuleNotFoundError as e:
        return ApolloError(code=500, message=str(e), type="INTERNAL_ERROR").to_dict()
    except ApolloError as e:
        result = e.to_dict()
    except Exception as e:
        result = ApolloError(code=500, message=str(e), type="INTERNAL_ERROR").to_dict()

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
