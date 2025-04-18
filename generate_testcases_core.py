import os
import re
import traceback
from werkzeug.utils import secure_filename

def clean_field(val):
    # Remove leading/trailing whitespace and excessive <br>
    val = val.strip()
    val = re.sub(r'(<br>\s*)+$', '', val)
    return val if val else '-'

def generate_testcases_core(jira_id, story_text, uploaded_file, fetch_jira_description, client):
    """
    Unified core logic for test case generation from Jira, story text, or upload.
    Returns: (table_rows, error, extracted_text, jira_id_out)
    """
    extracted_text = ""
    jira_id_out = jira_id
    try:
        # Priority: Uploaded file > Story text > Jira ID
        if uploaded_file and hasattr(uploaded_file, 'filename') and uploaded_file.filename:
            filename = secure_filename(uploaded_file.filename)
            filepath = os.path.join('static/uploads', filename)
            uploaded_file.save(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                extracted_text = f.read()
        elif story_text:
            extracted_text = story_text
        elif jira_id:
            extracted_text = fetch_jira_description(jira_id)
            jira_id_out = jira_id
        if not extracted_text.strip():
            return None, "❌ Please provide a Jira ID, story text, or upload a document.", None, None
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
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert QA tester helping with test case generation."},
                {"role": "user", "content": prompt_text}
            ],
            max_tokens=3000
        )
        raw_output = response.choices[0].message.content.strip()
        # Improved regex: robust to extra whitespace, optional colons, and multiline fields
        matches = re.findall(
            r"###\s*\d+[:\.]?\s*(.*?)\s*\n\*\*Preconditions:?\*\*\s*\n(.*?)\s*\n\*\*Test Steps:?\*\*\s*\n(.*?)\s*\n\*\*Expected Results:?\*\*\s*\n(.*?)\s*\n\*\*Edge Cases:?\*\*\s*\n(.*?)(?=\n###|\Z)",
            raw_output, re.DOTALL | re.IGNORECASE
        )
        testcases_rows = ""
        for i, match in enumerate(matches, 1):
            # Ensure exactly 5 fields, clean each field
            fields = [clean_field(m) for m in match]
            while len(fields) < 5:
                fields.append('-')
            title, pre, steps, exp, edge = fields
            testcases_rows += f"""
                <tr>
                    <td><strong>{i}: {title}</strong></td>
                    <td>{pre}</td>
                    <td>{steps}</td>
                    <td>{exp}</td>
                    <td>{edge}</td>
                </tr>
            """
        # If no matches, show raw output as Markdown rendered to HTML
        if not matches:
            try:
                import markdown2
                html_output = markdown2.markdown(raw_output)
            except ImportError:
                html_output = f"<pre>{raw_output}</pre>"
            testcases_rows = f"<tr><td colspan='5'>{html_output}</td></tr>"
        return testcases_rows, None, extracted_text.strip(), jira_id_out
    except Exception as e:
        print("❌ Exception in generate_testcases_core:", traceback.format_exc())
        return None, f"❌ Error: {str(e)}", None, None
