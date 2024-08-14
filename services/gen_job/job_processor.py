import json
import argparse
import requests

# Use command `poetry run python services/gen_job/job_processor.py -i tmp/input.json -o tmp/output.md` to run this script
# the input is a json file with a list of inputs

# This was done because there seems to be a problem with importing apollo from the util file as this file runs with a different command.
apollo_port = 3000
service_name = "gen_job"
url = f"http://127.0.0.1:{apollo_port}/services/{service_name}"

def apollo(payload):
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()  # Raise an error for bad responses
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error: {e}")
        return None
def process_inputs(input_file, output_file):
    print(f"Processing inputs from {input_file}...")
    # Read the input JSON file
    with open(input_file, 'r') as f:
        inputs = json.load(f)  # Assuming the JSON file contains a list of inputs

    # Open the output file for writing
    with open(output_file, 'w') as f_out:
        for idx, input_data in enumerate(inputs):
            print(f"Processing input {idx + 1}...")
            print("Calling Apollo...")
            # Process each input using the main() function
            output = apollo(input_data)
            
            print(f"Output for {idx + 1}: {output}\n")
            # Write the output to the file
            f_out.write(f"Input {idx + 1}:\n")
            f_out.write(f"Generated Job Expression:\n{output}\n")
            f_out.write("="*50 + "\n\n")  # Add a separator between outputs

    print(f"Job expressions have been written to {output_file}")

if __name__ == "__main__":
    # Use argparse to handle command-line arguments
    parser = argparse.ArgumentParser(description="Process job inputs and generate outputs.")
    parser.add_argument("--input", "-i", default="tmp/input.json", help="Path to the input JSON file")
    parser.add_argument("--output", "-o", default="tmp/output.md", help="Path to the output file")

    args = parser.parse_args()

    # Process the inputs and write outputs
    process_inputs(input_file=args.input, output_file=args.output)
