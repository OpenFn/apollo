import json
import ruamel.yaml
import sys

def lint_yaml(input_json_file, output_yaml_file):
    # Read the JSON file
    with open(input_json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Extract the YAML content from the JSON structure
    yaml_content = data.get("files", {}).get("project.yaml", "")

    if not yaml_content:
        print(f"No 'project.yaml' content found in {input_json_file}.")
        return

    # Load the YAML content using ruamel.yaml
    yaml = ruamel.yaml.YAML()
    yaml.allow_duplicate_keys = True
    try:
        yaml_data = yaml.load(yaml_content)
    except ruamel.yaml.YAMLError as e:
        print(f"Error loading YAML content: {e}")
        return

    # Write the formatted YAML content to the output file
    with open(output_yaml_file, 'w', encoding='utf-8') as f:
        yaml.dump(yaml_data, f)

    print(f"Linted YAML has been written to {output_yaml_file}.")

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python lint_yaml.py <input_json_file> <output_yaml_file>")
        sys.exit(1)

    input_json_file = sys.argv[1]
    output_yaml_file = sys.argv[2]
    lint_yaml(input_json_file, output_yaml_file)
