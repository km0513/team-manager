from flask import Blueprint, request, render_template
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import re
import requests
from openai import OpenAI
from requests.auth import HTTPBasicAuth
import os
import traceback
from docx import Document

load_dotenv()

api_key = os.getenv("OPENAI_API_KEY")
print("🔑 Using OpenAI API Key:", api_key[:8], "..." if api_key else "❌ Not found")
client = OpenAI(api_key=api_key)

testcase_bp = Blueprint('testcase_bp', __name__)

# Helper to convert Jira ADF to plain text
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

# Fetch from Jira
def fetch_jira_description(issue_key):
    url = f"{os.getenv('JIRA_BASE_URL')}/rest/api/3/issue/{issue_key}"
    auth = HTTPBasicAuth(os.getenv("JIRA_EMAIL"), os.getenv("JIRA_API_TOKEN"))
    headers = {"Accept": "application/json"}

    try:
        response = requests.get(url, headers=headers, auth=auth)
        print(f"📡 Jira API GET {url} — Status {response.status_code}")

        if response.status_code != 200:
            print("❌ Jira fetch failed:", response.text)
            return f"(Jira fetch failed: {response.status_code})"

        data = response.json()
        summary = data["fields"].get("summary", "(No Summary)")
        description_field = data["fields"].get("description", {})

        if not description_field:
            print("⚠️ No description field returned")
            return f"{summary}\n\n⚠️ Description not available."

        return f"{summary}\n\n" + parse_jira_description(description_field.get("content", []))

    except Exception as e:
        print("❌ Exception in Jira fetch:", traceback.format_exc())
        return "(Error fetching Jira content)"

# GET form
@testcase_bp.route('/generate-testcases', methods=['GET'])
def get_testcase_form():
    return render_template("generate_testcases.html")

# POST test case generation
@testcase_bp.route('/generate-testcases', methods=['POST'])
def generate_testcases():
    jira_id = request.form.get('jira_id', '').strip()
    story_text = request.form.get('story_text', '').strip()
    uploaded_file = request.files.get('story_doc')
    extracted_text = ""

    try:
        if uploaded_file and uploaded_file.filename:
            filename = secure_filename(uploaded_file.filename)
            filepath = os.path.join('static/uploads', filename)
            uploaded_file.save(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                extracted_text = f.read()

        elif story_text:
            extracted_text = story_text

        elif jira_id:
            extracted_text = fetch_jira_description(jira_id)

        if not extracted_text.strip():
            return render_template("generate_testcases.html", error="❌ Please provide a Jira ID, story text, or upload a document.")

        use_lxp_context = request.form.get('use_lxp_context') == 'yes'
        lxp_context = ''
        if use_lxp_context:
            try:
                doc = Document('lxp-context.docx')
                lxp_context = '\n'.join([para.text for para in doc.paragraphs if para.text.strip()])
            except Exception as e:
                print('❌ Error reading LXP context:', e)
                lxp_context = ''

        prompt_text = (
            f"You are a QA expert. Based on this user story or feature description:\n\n"
            f"{lxp_context + '\n\n' if lxp_context else ''}"
            f"{extracted_text}\n\n"
            "Generate structured functional test cases in the following format:\n\n"
            "### 1: Test Title\n"
            "**Preconditions:** ...\n"
            "**Test Steps:** ...\n"
            "**Expected Results:** ...\n"
            "**Edge Cases:** ...\n\n"
            "Do not include intro or summaries. Return only structured Markdown."
        )

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert QA tester helping with test case generation."},
                {"role": "user", "content": prompt_text}
            ],
            max_tokens=3000
        )

        raw_output = response.choices[0].message.content.strip()

        # Parse Markdown to table rows
        matches = re.findall(
            r"###\s*(\d+):\s*(.*?)\n\*\*Preconditions:\*\*(.*?)\n\*\*Test Steps:\*\*(.*?)\n\*\*Expected Results:\*\*(.*?)\n\*\*Edge Cases:\*\*(.*?)(?=\n###|\Z)",
            raw_output, re.DOTALL
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
                               original_requirement=extracted_text.strip(),
                               jira_base_url=os.getenv("JIRA_BASE_URL"))

    except Exception as e:
        print("❌ Exception in generate_testcases:", traceback.format_exc())
        return render_template("generate_testcases.html", error=f"❌ Error: {str(e)}")
