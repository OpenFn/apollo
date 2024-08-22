# services/gen_project/gen_project.py
import spacy
import json
import yaml
import os
import sys
import subprocess

# Get the absolute path to the current script
current_dir = os.path.dirname(os.path.abspath(__file__))

# Path to the model wheel file
model_wheel_path = os.path.join(current_dir, "models/en_core_web_sm-3.7.1-py3-none-any.whl")

# Install the model from the wheel file if not already installed
try:
    spacy.load("en_core_web_sm")
except OSError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", model_wheel_path])
    nlp = spacy.load("en_core_web_sm")
else:
    nlp = spacy.load("en_core_web_sm")


# Adaptors dictionary
adaptors = {
    "primero": "@openfn/language-primero@latest",
    "telerivet": "@openfn/language-telerivet@latest",
    "dhis2": "@openfn/language-dhis2@latest",
    "http": "@openfn/language-http@latest",
    "asana": "@openfn/language-asana@latest",
    "azure-storage": "@openfn/language-azure-storage@latest",
    "beyonic": "@openfn/language-beyonic@latest",
    "bigquery": "@openfn/language-bigquery@latest",
    "cartodb": "@openfn/language-cartodb@latest",
    "commcare": "@openfn/language-commcare@latest",
    "common": "@openfn/language-common@latest",
    "dynamics": "@openfn/language-dynamics@latest",
    "facebook": "@openfn/language-facebook@latest",
    "fhir": "@openfn/language-fhir@latest",
    "godata": "@openfn/language-godata@latest",
    "googlehealthcare": "@openfn/language-googlehealthcare@latest",
    "googlesheets": "@openfn/language-googlesheets@latest",
    "hive": "@openfn/language-hive@latest",
    "khanacademy": "@openfn/language-khanacademy@latest",
    "kobotoolbox": "@openfn/language-kobotoolbox@latest",
    "magpi": "@openfn/language-magpi@latest",
    "mailchimp": "@openfn/language-mailchimp@latest",
    "mailgun": "@openfn/language-mailgun@latest",
    "maximo": "@openfn/language-maximo@latest",
    "medicmobile": "@openfn/language-medicmobile@latest",
    "mogli": "@openfn/language-mogli@latest",
    "mongodb": "@openfn/language-mongodb@latest",
    "msgraph": "@openfn/language-msgraph@latest",
    "mssql": "@openfn/language-mssql@latest",
    "mysql": "@openfn/language-mysql@latest",
    "nexmo": "@openfn/language-nexmo@latest",
    "ocl": "@openfn/language-ocl@latest",
    "openfn": "@openfn/language-openfn@latest",
    "openhim": "@openfn/language-openhim@latest",
    "openimis": "@openfn/language-openimis@latest",
    "openmrs": "@openfn/language-openmrs@latest",
    "openspp": "@openfn/language-openspp@latest",
    "postgresql": "@openfn/language-postgresql@latest",
    "progress": "@openfn/language-progress@latest",
    "rapidpro": "@openfn/language-rapidpro@latest",
    "resourcemap": "@openfn/language-resourcemap@latest",
    "salesforce": "@openfn/language-salesforce@latest",
    "satusehat": "@openfn/language-satusehat@latest",
    "sftp": "@openfn/language-sftp@latest",
    "smpp": "@openfn/language-smpp@latest",
    "surveycto": "@openfn/language-surveycto@latest",
    "template": "@openfn/language-template@latest",
    "twilio": "@openfn/language-twilio@latest",
    "vtiger": "@openfn/language-vtiger@latest",
    "zoho": "@openfn/language-zoho@latest"
}

def generate_job_name(step):
    return "-".join(word.capitalize() for word in step.split() if word.lower() not in ["with", "from", "to", "using", "a", "an", "the", "and", "of"])

def extract_adaptor(step):
    doc = nlp(step)
    detected_adaptor = None
    for ent in doc.ents:
        if ent.label_ == "ADAPTER":
            for key in adaptors.keys():
                if key in ent.text.lower():
                    detected_adaptor = adaptors[key]
                    break
    if not detected_adaptor:
        for key in adaptors.keys():
            if key in step.lower():
                detected_adaptor = adaptors[key]
                break
    return detected_adaptor if detected_adaptor else "@openfn/language-common@latest"

def parse_workflow_steps(steps):
    workflow = {
        "workflow-1": {
            "name": "Generated Workflow",
            "jobs": {},
            "triggers": {"webhook": {"type": "webhook", "enabled": True}},
            "edges": [],
        }
    }

    # Add the name and description fields
    workflow["name"] = "open-project"
    workflow["description"] = "Auto-generated workflow based on provided steps."

    previous_job = None

    for step in steps:
        step = step.strip()
        job_name = generate_job_name(step)
        adaptor = extract_adaptor(step)

        workflow["workflow-1"]["jobs"][job_name] = {
            "name": step,
            "adaptor": adaptor,
            "body": "| // Add operations here",
        }

        if previous_job:
            workflow["workflow-1"]["edges"].append({
                "source_job": previous_job,
                "target_job": job_name,
                "condition_type": "on_job_success",
                "enabled": True
            })
        previous_job = job_name

    if previous_job:
        first_job = list(workflow["workflow-1"]["jobs"].keys())[0]
        workflow["workflow-1"]["edges"].insert(0, {
            "source_trigger": "webhook",
            "target_job": first_job,
            "condition_type": "always",
            "enabled": True
        })

    return workflow

def main(data):
    steps = data.get('steps', [])
    output_format = data.get('format', 'yaml')

    workflow = parse_workflow_steps(steps)

    if output_format == 'json':
        workflow_output = json.dumps(workflow, indent=2)
    else:
        workflow_output = yaml.dump(workflow, sort_keys=False)

    return {"files": {"project.yaml" if output_format == 'yaml' else "workflow.json": workflow_output}}
