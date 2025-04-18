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
        if response.status_code != 200:
            return f"(Jira fetch failed: {response.status_code})"
        data = response.json()
        summary = data["fields"].get("summary", "(No Summary)")
        description_field = data["fields"].get("description", {})
        if not description_field:
            return f"{summary}\n\n⚠️ Description not available."
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
        return f"{summary}\n\n" + "".join(parse_node(block) for block in description_field.get("content", []))
    except Exception as e:
        return "(Error fetching Jira content)"

# AJAX endpoint for live Jira fetch
@testcase_bp.route('/get-jira-description', methods=['GET'])
def get_jira_description():
    jira_id = request.args.get('jira_id', '').strip()
    if not jira_id:
        return jsonify({'error': 'No Jira ID provided.'}), 400
    desc = fetch_jira_description(jira_id)
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
