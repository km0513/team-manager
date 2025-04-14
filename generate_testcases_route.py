from flask import Blueprint, request, render_template
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import re
import requests
from openai import OpenAI
from requests.auth import HTTPBasicAuth

load_dotenv()


import os
api_key = os.getenv("OPENAI_API_KEY")
print("🔑 Using OpenAI API Key:", api_key[:8], "..." if api_key else "❌ Not found")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# Helper to convert Jira's ADF (Atlassian Document Format) to readable text
def parse_jira_description(adf_block):
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

    return "".join(parse_node(block) for block in adf_block)

testcase_bp = Blueprint('testcase_bp', __name__)

# Function to fetch description from Jira
def fetch_jira_description(issue_key):
    url = f"{os.getenv('JIRA_BASE_URL')}/rest/api/3/issue/{issue_key}"
    auth = HTTPBasicAuth(os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN"))
    headers = {"Accept": "application/json"}

    response = requests.get(url, headers=headers, auth=auth)
    if response.status_code == 200:
        data = response.json()
        summary = data["fields"].get("summary", "")
        description_field = data["fields"].get("description", {})

        # Convert Jira ADF description to readable text
        description = parse_jira_description(description_field.get("content", [])) if isinstance(description_field, dict) else str(description_field)

        return f"{summary}\n\n{description}"
    return None


@testcase_bp.route('/generate-testcases', methods=['POST'])
def generate_testcases():
    jira_id = request.form.get('jira_id')
    story_text = request.form.get('story_text')
    uploaded_file = request.files.get('story_doc')

    extracted_text = ""

    if uploaded_file:
        filename = secure_filename(uploaded_file.filename)
        filepath = os.path.join('static/uploads', filename)
        uploaded_file.save(filepath)
        with open(filepath, 'r', encoding='utf-8') as f:
            extracted_text = f.read()
    elif story_text:
        extracted_text = story_text
    elif jira_id:
        extracted_text = fetch_jira_description(jira_id) or ""

    if not extracted_text:
        return "❌ Please provide a Jira ID or paste/upload story content.", 400

    prompt_text = (
        f"You are a QA expert. Based on this user story or feature description:\n\n"
        f"{extracted_text}\n\n"
        "Generate structured functional test cases in the following format:\n\n"
        "### 1: Test Title\n"
        "**Preconditions:** ...\n"
        "**Test Steps:** ...\n"
        "**Expected Results:** ...\n"
        "**Edge Cases:** ...\n\n"
        "Do not include intro or summaries. Return only structured Markdown."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert QA tester helping with test case generation."},
                {"role": "user", "content": prompt_text}
            ],
            max_tokens=3000
        )

        raw_output = response.choices[0].message.content.strip()

        # Use regex to find all test cases
        matches = re.findall(
            r"###\s*(\d+):\s*(.*?)\n\*\*Preconditions:\*\*(.*?)\n\*\*Test Steps:\*\*(.*?)\n\*\*Expected Results:\*\*(.*?)\n\*\*Edge Cases:\*\*(.*?)(?=\n###|\Z)",
            raw_output,
            re.DOTALL
        )

        testcases_rows = ""
        for match in matches:
            num, title, pre, steps, exp, edge = [m.strip().replace("\n", "<br>") for m in match]
            testcases_rows += f"""
                <tr>
                    <td><strong>{num}: {title}</strong></td>
                    <td>{pre}</td>
                    <td>{steps}</td>
                    <td>{exp}</td>
                    <td>{edge}</td>
                </tr>
            """

        return render_template("testcases_result.html",
                               jira_id=jira_id,
                               content=testcases_rows,
                               original_requirement=extracted_text.strip(),jira_base_url=os.getenv("JIRA_BASE_URL"))

    except Exception as e:
        return f"<h4 style='color:red'>❌ Error generating test cases: {str(e)}</h4>", 500
