import os
import json
import argparse
import requests

# Use the command `poetry run python services/gen_job/job_processor.py -i tmp/input.json -o tmp/output.md` to run this script
# The input is a JSON file with a list of inputs.

# Apollo service configuration
APOLLO_PORT = 3000
SERVICE_NAME = "gen_job"
APOLLO_URL = f"http://127.0.0.1:{APOLLO_PORT}/services/{SERVICE_NAME}"

def apollo(payload: dict) -> str:
    """Send a POST request to the Apollo service with the given payload.
    
    Args:
        payload (dict): The payload to send in the request.
    
    Returns:
        str: The response text from Apollo, or None if the request fails.
    """
    try:
        response = requests.post(APOLLO_URL, json=payload)
        response.raise_for_status()  # Raise an error for bad responses
        return response.text
    except requests.exceptions.RequestException as e:
        print(f"Error communicating with Apollo service: {e}")
        return None

def process_inputs(input_file: str, output_file: str) -> None:
    """Process inputs from a JSON file and generate outputs based on Apollo responses.
    
    Args:
        input_file (str): Path to the input JSON file.
        output_file (str): Path to the output markdown file.
    """

    # Delete the output file if it already exists
    if os.path.exists(output_file):
        try:
            os.remove(output_file)
            print(f"Existing output file '{output_file}' has been deleted.")
        except OSError as e:
            print(f"Error deleting the file {output_file}: {e}")
            return

    print(f"Processing inputs from {input_file}...")
    
    # Read the input JSON file
    try:
        with open(input_file, 'r') as f:
            inputs = json.load(f)  # Expecting the JSON file to contain a list of inputs
    except (IOError, json.JSONDecodeError) as e:
        print(f"Failed to read or parse input file {input_file}: {e}")
        return

    # Open the output file for writing
    try:
        with open(output_file, 'w') as f_out:
            for idx, input_data in enumerate(inputs):
                print(f"Processing input {idx + 1}...")
                print("Calling Apollo...")
                
                # Call Apollo service to process each input
                output = apollo(input_data)
                
                if output is None:
                    print(f"Skipping input {idx + 1} due to an error.")
                    continue

                # Log and write the output to the file
                print(f"Output for input {idx + 1} received.\n")
                f_out.write(f"## Input {idx + 1}:\n### Instruction: \n{input_data.get('instruction', 'N/A')}\n\n")
                f_out.write("## Generated Job Expression:\n")
                f_out.write(output)
                f_out.write("\n\n" + "="*50 + "\n\n")  # Add a separator between outputs

        print(f"Job expressions have been successfully written to {output_file}")
    
    except IOError as e:
        print(f"Failed to write to output file {output_file}: {e}")

if __name__ == "__main__":
    # Use argparse to handle command-line arguments
    parser = argparse.ArgumentParser(description="Process job inputs and generate outputs.")
    parser.add_argument("--input", "-i", default="tmp/input.json", help="Path to the input JSON file")
    parser.add_argument("--output", "-o", default="tmp/output.md", help="Path to the output file")

    # Parse the arguments and process the inputs
    args = parser.parse_args()
    process_inputs(input_file=args.input, output_file=args.output)
