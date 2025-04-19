print("DEBUG: ai_utils.py loaded in environment")

import os
import openai
import requests
from requests.auth import HTTPBasicAuth
import re
import traceback

class AIUtility:
    def __init__(self, openai_api_key, jira_base_url=None, jira_email=None, jira_token=None):
        self.openai_client = openai.OpenAI(api_key=openai_api_key)
        self.jira_base_url = jira_base_url
        self.jira_email = jira_email
        self.jira_token = jira_token

    def fetch_jira_description(self, jira_id):
        """Fetch Jira issue summary and description as plain text."""
        if not (self.jira_base_url and self.jira_email and self.jira_token):
            return None, "Jira credentials not configured."
        url = f"{self.jira_base_url}/rest/api/3/issue/{jira_id}"
        auth = HTTPBasicAuth(self.jira_email, self.jira_token)
        headers = {"Accept": "application/json"}
        try:
            resp = requests.get(url, headers=headers, auth=auth)
            if resp.status_code != 200:
                return None, f"Jira fetch failed: {resp.status_code}"
            data = resp.json()
            summary = data["fields"].get("summary", "")
            desc = summary + "\n\n"
            description_field = data["fields"].get("description", {})
            # Parse Jira ADF to plain text
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
            if description_field:
                desc += "".join(parse_node(block) for block in description_field.get("content", []))
            return desc.strip(), None
        except Exception as e:
            return None, str(e)

    def generate_testcases(self, requirement_text):
        """Call OpenAI to generate test cases from requirement text."""
        prompt = (
            f"You are a QA expert. Based on this requirement:\n\n"
            f"{requirement_text}\n\n"
            "Generate structured functional test cases in this format:\n"
            "### 1: Test Title\n"
            "**Preconditions:** ...\n"
            "**Test Steps:** ...\n"
            "**Expected Results:** ...\n"
            "**Edge Cases:** ...\n"
            "Return only structured Markdown."
        )
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an expert QA tester."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=3000
            )
            return response.choices[0].message.content.strip(), None
        except Exception as e:
            return None, str(e)

    def parse_testcases(self, raw_output):
        """Parse the AI markdown output into structured table rows (HTML). Handles various field order and formatting."""
        # Improved regex: robust to extra whitespace, missing fields, and flexible order
        testcase_pattern = re.compile(
            r"###\s*\d+[:\.]?\s*(.*?)\s*"  # Title
            r"(?:\*\*Preconditions:?\*\*\s*(.*?)\s*)?"  # Preconditions
            r"(?:\*\*Test Steps:?\*\*\s*(.*?)\s*)?"  # Test Steps
            r"(?:\*\*Expected Results?:?\*\*\s*(.*?)\s*)?"  # Expected Results
            r"(?:\*\*Edge Cases:?\*\*\s*(.*?))?"  # Edge Cases
            r"(?=\n###|\Z)",
            re.DOTALL | re.IGNORECASE
        )
        def clean_field(val):
            if val is None:
                return '-'
            val = val.strip()
            val = re.sub(r'(<br>\s*)+$', '', val)
            val = val.replace("\n", "<br>")
            return val if val else '-'
        table_rows = ""
        matches = testcase_pattern.findall(raw_output)
        for i, match in enumerate(matches, 1):
            # match: (title, preconditions, steps, expected, edge)
            fields = [clean_field(m) for m in match]
            while len(fields) < 5:
                fields.append('-')
            title, pre, steps, exp, edge = fields
            table_rows += f"""
                <tr>
                    <td><strong>{i}: {title}</strong></td>
                    <td>{pre}</td>
                    <td>{steps}</td>
                    <td>{exp}</td>
                    <td>{edge}</td>
                </tr>
            """
        if not matches:
            # Try fallback: parse a single block (even if not in markdown)
            single_pattern = re.compile(
                r"(?:###\s*\d+[:\.]?\s*)?(.*?)\s*"  # Title
                r"\*\*Preconditions:?\*\*\s*(.*?)\s*"
                r"\*\*Test Steps:?\*\*\s*(.*?)\s*"
                r"\*\*Expected Results?:?\*\*\s*(.*?)\s*"
                r"\*\*Edge Cases:?\*\*\s*(.*)",
                re.DOTALL | re.IGNORECASE
            )
            single = single_pattern.search(raw_output)
            if single:
                fields = [clean_field(m) for m in single.groups()]
                while len(fields) < 5:
                    fields.append('-')
                title, pre, steps, exp, edge = fields
                table_rows = f"""
                    <tr>
                        <td><strong>{title}</strong></td>
                        <td>{pre}</td>
                        <td>{steps}</td>
                        <td>{exp}</td>
                        <td>{edge}</td>
                    </tr>
                """
            else:
                table_rows = f"<tr><td colspan='5'><pre>{raw_output}</pre></td></tr>"
        return table_rows

    def run(self, jira_id=None, story_text=None, uploaded_file=None):
        """Unified entrypoint: fetches requirement, generates and parses test cases."""
        extracted_text = None
        if uploaded_file and hasattr(uploaded_file, 'read'):
            extracted_text = uploaded_file.read().decode('utf-8')
        elif story_text:
            extracted_text = story_text
        elif jira_id:
            extracted_text, err = self.fetch_jira_description(jira_id)
            if err:
                return None, err, None, jira_id
        else:
            return None, "No input provided.", None, None
        if not extracted_text or not extracted_text.strip():
            return None, "No requirement text provided.", None, jira_id
        raw_output, err = self.generate_testcases(extracted_text)
        if err:
            return None, err, extracted_text, jira_id
        table_rows = self.parse_testcases(raw_output)
        return table_rows, None, extracted_text, jira_id

    def analyze_image(self, image_bytes):
        """
        Analyze a UI screenshot and return detailed feedback including:
        - UI/UX review (layout, accessibility, color contrast, visual issues)
        - Suggestions for improvements
        - Draft relevant test cases (UI, functional, edge/negative)
        Returns HTML or markdown and error (if any).
        """
        import base64
        from PIL import Image
        import io
        try:
            # Downscale image if too large to reduce token size
            img = Image.open(io.BytesIO(image_bytes))
            max_dim = 512  # Reduce to 512px max (preserves aspect)
            if max(img.size) > max_dim:
                ratio = max_dim / float(max(img.size))
                new_size = (int(img.size[0]*ratio), int(img.size[1]*ratio))
                # Use LANCZOS for high-quality downsampling (ANTIALIAS is deprecated)
                img = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            small_bytes = buf.getvalue()
            b64_image = base64.b64encode(small_bytes).decode('utf-8')
            messages = [
                {"role": "system", "content": "You are an expert QA engineer and UI/UX reviewer. You CAN see and analyze images if they are provided as base64-encoded PNG. When given a base64-encoded screenshot, decode and visually analyze it as an image. Do not say you cannot see images. Instead, provide a detailed UI/UX review, actionable suggestions, and draft relevant test cases as requested."},
                {"role": "user", "content": (
                    "Below is a PNG screenshot of a web or app UI, base64-encoded. "
                    "1. Review the UI for layout, accessibility, color contrast, and usability issues.\n"
                    "2. Suggest clear, actionable improvements.\n"
                    "3. Draft relevant test cases in markdown, organized as:\n"
                    "### UI Test Cases\n### Functional Test Cases\n### Negative/Edge Cases\n"
                    "Each test case should have a title and short description.\n\n"
                    "Screenshot (base64 PNG):\n" + b64_image
                )}
            ]
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=2000
            )
            output = response.choices[0].message.content.strip()
            return output, None
        except Exception as e:
            import traceback
            return None, str(e) + "\n" + traceback.format_exc()

    def analyze_url(self, page_url):
        """
        Analyze a web page via its URL and return detailed feedback including:
        - UI/UX review (layout, accessibility, color contrast, visual issues)
        - Suggestions for improvements
        - Draft relevant test cases (UI, functional, edge/negative)
        Returns HTML or markdown and error (if any).
        """
        import requests
        try:
            resp = requests.get(page_url, timeout=10)
            if resp.status_code != 200:
                return None, f"Failed to fetch URL: {resp.status_code}"
            html_content = resp.text
            messages = [
                {"role": "system", "content": "You are an expert QA engineer and UI/UX reviewer. You CAN see and analyze HTML if it is provided as raw HTML. When given a web page's HTML, analyze it as a rendered page. Provide a detailed UI/UX review, actionable suggestions, and draft relevant test cases as requested."},
                {"role": "user", "content": (
                    f"Below is the raw HTML of a web page.\n"
                    f"1. Review the UI for layout, accessibility, color contrast, and usability issues.\n"
                    f"2. Suggest clear, actionable improvements.\n"
                    f"3. Draft relevant test cases in markdown, organized as:\n"
                    f"### UI Test Cases\n### Functional Test Cases\n### Negative/Edge Cases\n"
                    f"Each test case should have a title and short description.\n\n"
                    f"HTML Content:\n" + html_content[:10000]  # Limit to 10k chars for token safety
                )}
            ]
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=2000
            )
            output = response.choices[0].message.content.strip()
            return output, None
        except Exception as e:
            import traceback
            return None, str(e) + "\n" + traceback.format_exc()
