from flask import Blueprint, request, render_template, jsonify
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import os
from generate_testcases_core import generate_testcases_core
from openai import OpenAI
from requests.auth import HTTPBasicAuth
import re
import requests
import traceback
from ai_utils import AIUtility

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)

# Instantiate the AI utility once
ai_util = AIUtility(
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    jira_base_url=os.getenv("JIRA_BASE_URL"),
    jira_email=os.getenv("JIRA_EMAIL"),
    jira_token=os.getenv("JIRA_API_TOKEN")
)

testcase_bp = Blueprint('testcase_bp', __name__)

# Fetch from Jira 
def fetch_jira_description(issue_key):
    url = f"{os.getenv('JIRA_BASE_URL')}/rest/api/3/issue/{issue_key}"
    auth = HTTPBasicAuth(os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN"))
    headers = {"Accept": "application/json"}
    try:
        response = requests.get(url, headers=headers, auth=auth)
        print(f"DEBUG: Jira API GET {url} status={response.status_code}")
        print(f"DEBUG: Jira API response text: {response.text}")
        if response.status_code == 404:
            return None, f"Jira ticket '{issue_key}' not found."
        if response.status_code == 401:
            return None, "Unauthorized: Check your Jira credentials."
        if response.status_code != 200:
            return None, f"Jira fetch failed: {response.status_code}"
        data = response.json()
        if "fields" not in data:
            return None, f"Unexpected Jira API response: {data}"
        summary = data["fields"].get("summary", "(No Summary)")
        description_field = data["fields"].get("description", {})
        if not description_field:
            return f"{summary}\n(No Description)", None
        def parse_node(node):
            if node["type"] == "text":
                return node.get("text", "")
            elif node["type"] == "paragraph":
                return "".join(parse_node(child) for child in node.get("content", [])) + "\n"
            elif node["type"] in ("orderedList", "bulletList"):
                return "\n".join(parse_node(item) for item in node.get("content", [])) + "\n"
            elif node["type"] == "listItem":
                return "- " + "".join(parse_node(child) for child in node.get("content", []))
            elif "content" in node:
                return "".join(parse_node(child) for child in node["content"])
            return ""
        return f"{summary}\n\n" + "".join(parse_node(block) for block in description_field.get("content", [])), None
    except Exception as e:
        print(f"DEBUG: Exception in fetch_jira_description: {e}")
        return None, f"Error fetching Jira content: {e}"  

def validate_jira_ticket(issue_key):
    url = f"{os.getenv('JIRA_BASE_URL')}/rest/api/3/search"
    auth = HTTPBasicAuth(os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN"))
    headers = {"Accept": "application/json"}
    params = {
        "jql": f"issuekey={issue_key}",
        "maxResults": 1,
        "fields": "summary"
    }
    try:
        response = requests.get(url, headers=headers, auth=auth, params=params)
        print(f"DEBUG: Jira search API GET {url} status={response.status_code}")
        data = response.json()
        print(f"DEBUG: Jira API response data: {data}")
        if response.status_code == 401:
            return None, "Unauthorized: Check your Jira credentials."
        if response.status_code != 200:
            return None, f"Jira search failed: {response.status_code}"
        issues = data.get("issues", [])
        if not issues:
            return None, f"Jira ticket '{issue_key}' not found."
        summary = issues[0]["fields"].get("summary", "(No Summary)")
        return summary, None
    except Exception as e:
        print(f"DEBUG: Exception in validate_jira_ticket: {e}")
        return None, f"Error validating Jira ticket: {e}"

# AJAX endpoint for live Jira fetch
@testcase_bp.route('/get-jira-description', methods=['GET'])
def get_jira_description():
    jira_id = request.args.get('jira_id', '').strip()
    print(f"DEBUG: /get-jira-description called with jira_id='{jira_id}'")
    if not jira_id:
        print("DEBUG: No Jira ID provided.")
        return jsonify({'error': 'No Jira ID provided.'}), 400
    desc, error = validate_jira_ticket(jira_id)
    print(f"DEBUG: validate_jira_ticket returned desc={repr(desc)}, error={repr(error)}")
    # Treat any error, missing/empty desc, or desc starting with 'error' as an error
    if error or not desc or (isinstance(desc, str) and desc.strip().lower().startswith('error')):
        print(f"DEBUG: Returning error: {error or desc or 'Unknown error'}")
        return jsonify({'error': error or desc or 'Unknown error'}), 400
    print(f"DEBUG: Returning description: {desc}")
    return jsonify({'description': desc})

# GET form
testcase_bp.route('/generate-testcases', methods=['GET'])(lambda: render_template("generate_testcases.html"))

# POST test case generation
@testcase_bp.route('/generate-testcases', methods=['POST'])
def generate_testcases():
    jira_id = request.form.get('jira_id', '').strip()
    story_text = request.form.get('story_text', '').strip()
    uploaded_file = request.files.get('story_doc')
    testcases_rows, error, extracted_text, jira_id_out = ai_util.run(
        jira_id=jira_id,
        story_text=story_text,
        uploaded_file=uploaded_file
    )
    if error:
        return render_template("generate_testcases.html", error=error)
    return render_template(
        "testcases_result.html",
        jira_id=jira_id_out,
        content=testcases_rows,
        original_requirement=extracted_text,
        jira_base_url=os.getenv("JIRA_BASE_URL")
    )
