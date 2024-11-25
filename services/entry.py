import sys
import json
from dotenv import load_dotenv
from util import set_apollo_port
import uuid

# This will load from the ../.env file (at root)
load_dotenv()


# This module is a sort of "router"
# Given a module name (ie, inference)
# it will import it dynamically and invoke the main
# function with the second argument
# args is a list of the form (serviceName, args)
def call(service, input_path, output_path):
    module_name = "{0}.{0}".format(service)

    f = open(input_path, "r")
    data = json.load(f)
    f.close()

    m = __import__(module_name, fromlist=["main"])
    result = m.main(data)

    f = open(output_path, "w")
    f.write(json.dumps(result))
    f.close()

    return result


# When called from main, read the input and output path from stdin
# If output is not present, generate it
if __name__ == "__main__":
    mod_name = sys.argv[1]
    input_path = sys.argv[2]
    output_path = None

    if len(sys.argv) == 4:
        output_path = sys.argv[3]
    else:
        print("auto-generating output path")
        id = uuid.uuid4()
        output_path = "tmp/data/{}.json".format(id)
        print("Result will be output to {}".format(output_path))

    if len(sys.argv) >= 5:
        apollo_port = sys.argv[4]
        if apollo_port is not None:
            print("Setting apollo port to {}".format(apollo_port))
            set_apollo_port(apollo_port)

    print("Calling services/{} ...".format(mod_name))

    print()
    result = call(mod_name, input_path, output_path)
    print()
    print("Done!")
    print(result)
