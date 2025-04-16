@app.route('/generate-testcases', methods=['GET'])
def get_testcase_form():
    return render_template("generate_testcases.html")

@app.route('/generate-testcases', methods=['POST'])
def generate_testcases():
    jira_id = request.form.get('jira_id', '').strip()
    story_text = request.form.get('story_text', '').strip()
    uploaded_file = request.files.get('story_doc')

    extracted_text = ""

    try:
        if uploaded_file and uploaded_file.filename:
            filename = secure_filename(uploaded_file.filename)
            filepath = os.path.join('static/uploads', filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            uploaded_file.save(filepath)
            with open(filepath, 'r', encoding='utf-8') as f:
                extracted_text = f.read()

        elif story_text:
            extracted_text = story_text

        elif jira_id:
            extracted_text = fetch_jira_description(jira_id) or ""

        if not extracted_text.strip():
            return render_template("generate_testcases.html", error="❌ Please provide a Jira ID, story text, or upload a document.")

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

        matches = re.findall(
            r"###\\s*(\\d+):\\s*(.*?)\n\\*\\*Preconditions:\\*\\*(.*?)\n\\*\\*Test Steps:\\*\\*(.*?)\n\\*\\*Expected Results:\\*\\*(.*?)\n\\*\\*Edge Cases:\\*\\*(.*?)(?=\n###|\\Z)",
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
                               original_requirement=extracted_text.strip(),
                               jira_base_url=os.getenv("JIRA_BASE_URL"))

    except Exception as e:
        print("❌ Exception:", traceback.format_exc())
        return render_template("generate_testcases.html", error=f"❌ Error: {str(e)}")
