import sys
import json
import uuid
from dotenv import load_dotenv
from util import set_apollo_port, ApolloError

load_dotenv()


def call(service: str, input_path: str, output_path: str) -> dict:
    """
    Dynamically imports a module and invokes its main function with input data.

    :param service: The name of the service/module to invoke.
    :param input_path: Path to the input JSON file.
    :param output_path: Path to write the output JSON file.
    :return: Result from the service as a dictionary.
    """
    module_name = f"{service}.{service}"

    with open(input_path, "r") as f:
        data = json.load(f)

    try:
        m = __import__(module_name, fromlist=["main"])
        result = m.main(data)
    except ApolloError as e:
        result = e.to_dict()
    except Exception as e:
        result = ApolloError(
            code=500,
            message=str(e),
            type="INTERNAL_ERROR"
        ).to_dict()

    with open(output_path, "w") as f:
        json.dump(result, f)

    return result


def main():
    """
    Entry point when the script is run directly.
    Reads arguments from stdin and calls the appropriate service.
    """
    mod_name = sys.argv[1]
    input_path = sys.argv[2]
    output_path = None

    if len(sys.argv) >= 5:
        output_path = sys.argv[3]
    else:
        print("Auto-generating output path...")
        id = uuid.uuid4()
        output_path = f"tmp/data/{id}.json"
        print(f"Result will be output to {output_path}")

    if len(sys.argv) >= 5:
        apollo_port = sys.argv[4]
        if apollo_port:
            print(f"Setting Apollo port to {apollo_port}")
            set_apollo_port(apollo_port)

    print(f"Calling services/{mod_name} ...")
    print()

    result = call(mod_name, input_path, output_path)

    print()
    print("Done!")
    print(result)


if __name__ == "__main__":
    main()