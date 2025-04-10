from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.utils import secure_filename

from markdown import markdown as md_convert  # only one import for markdown is needed
from dotenv import load_dotenv

import pandas as pd
import matplotlib
matplotlib.use('Agg')  # use non-interactive backend for server environments
import matplotlib.pyplot as plt

import os
import json
import base64
from datetime import datetime, timedelta
import calendar
from datetime import date





load_dotenv()  # This loads the .env file
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



import requests
from requests.auth import HTTPBasicAuth
from collections import defaultdict

# Initialize Flask app
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'supersecretkey'

from flask_session import Session

app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_FILE_DIR'] = './.flask_session/'  # Optional: path to store session files
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
Session(app)



from flask_mail import Mail

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')  # from your .env
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')  # from your .env
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

mail = Mail(app)


# Database and migration setup
db = SQLAlchemy(app)
migrate = Migrate(app, db)

# Jira configuration
JIRA_BASE_URL = "https://upgrad-jira.atlassian.net"
JIRA_EMAIL = "kishore.murkhanad@upgrad.com"
JIRA_API_TOKEN = "REMOVED3xFfGF092uypGX-1LAgIBLo96QhturPWgV-LVLd0rIrxLNFHQmgx-ateg1PbmrjCCR8P7U0uCN8Npa8geSu_3Qya-v_etGvP9bxBSSLAfgNvnMwg8syRhLXtc2kFWzhkzY952N40JHg5MueBKGkUht1OdWOEDnTzgA7lCcb4BQ7VfCyqmA=B9998DF4"  # 🔒 Truncated for security
auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json"}

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    designation = db.Column(db.String(100))
    jira_account_id = db.Column(db.String(100))  # Jira mapping

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    start_date = db.Column(db.Date)
    leave_type = db.Column(db.String(50))
    user = db.relationship('User', backref='leaves')

# Helper functions
def get_time_spent_by_user(date):
    return get_time_spent_by_user_range(date, date)

def get_time_spent_by_user_range(start, end):
    worklog_author_ids = [
        "712020:88fcfc28-...",  # truncated for brevity
        "712020:901af395-...",
        # ... add the rest
    ]
    jql_authors = ",".join(worklog_author_ids)
    jql = f"worklogAuthor in ({jql_authors}) AND worklogDate >= \"{start}\" AND worklogDate <= \"{end}\""
    url = f"{JIRA_BASE_URL}/rest/api/3/search"
    params = {"jql": jql, "fields": "worklog", "maxResults": 100}
    response = requests.get(url, headers=headers, params=params, auth=auth)
    if not response.ok:
        print("Jira API error:", response.text)
        return {}
    issues = response.json().get("issues", [])
    user_time_spent = defaultdict(int)
    for issue in issues:
        for worklog in issue.get("fields", {}).get("worklog", {}).get("worklogs", []):
            started = worklog.get("started", "")
            if start <= started[:10] <= end:
                author = worklog["author"].get("accountId")  # mapped to jira_account_id
                time_spent = worklog.get("timeSpentSeconds", 0)
                user_time_spent[author] += time_spent
    return {account_id: round(seconds / 3600, 2) for account_id, seconds in user_time_spent.items()}


from datetime import datetime

def filter_sprints_this_month(sprints):
    now = datetime.now()
    current_month = now.month
    current_year = now.year

    filtered_events = []
    for sprint in sprints:
        try:
            start_date = datetime.strptime(sprint['startDate'][:10], "%Y-%m-%d")
            end_date = datetime.strptime(sprint['endDate'][:10], "%Y-%m-%d")

            # Include if sprint starts OR ends in the current month/year
            if (start_date.month == current_month and start_date.year == current_year) or \
               (end_date.month == current_month and end_date.year == current_year):

                filtered_events.append({
                    "title": sprint["name"],
                    "start": sprint["startDate"][:10],
                    "end": sprint["endDate"][:10],
                    "color": "gray",
                    "extendedProps": {
                        "status": sprint["state"],
                        "goal": sprint.get("goal", "")
                    }
                })
        except Exception as e:
            print("Skipping sprint due to date parsing error:", e)

    print("📆 Filtered Events for Current Month:", filtered_events)
    return filtered_events


def fetch_jira_sprints(board_id):
    url = f"{JIRA_BASE_URL}/rest/agile/1.0/board/{board_id}/sprint"
    response = requests.get(url, auth=auth)

    if response.ok:
        sprints = response.json().get('values', [])
        print("✅ Fetched Sprints:", sprints)
        return sprints
    else:
        print("❌ Jira Sprint Fetch Failed:", response.status_code, response.text)
        return []



# Routes
@app.before_request
def require_login():
    if 'logged_in' not in session and request.endpoint not in ['login', 'static']:
        return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'password':
            session['logged_in'] = True
            return redirect('/')
        return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect('/login')



@app.route('/')
def dashboard():
    today = date.today()

    users_on_leave_today = (
        db.session.query(User.name)
        .join(Leave)
        .filter(Leave.start_date == today)
        .all()
    )

    user_names = [u.name for u in users_on_leave_today]
    total_users = db.session.query(User).count()

    return render_template(
        'dashboard.html',
        users_on_leave=user_names,
        today=today,
        total_users=total_users
    )





@app.route('/users', methods=['GET', 'POST'])
def users():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        designation = request.form['designation']
        user = User(name=name, email=email, designation=designation)
        db.session.add(user)
        db.session.commit()
        return redirect('/users')
    all_users = User.query.all()
    return render_template('users.html', users=all_users)

@app.route('/export-users')
def export_users():
    users = User.query.all()
    data = []
    for user in users:
        leaves = Leave.query.filter_by(user_id=user.id).all()
        total_leave = sum(1 if l.leave_type == 'FD' else 0.5 for l in leaves)
        data.append({
            'ID': user.id,
            'Name': user.name,
            'Email': user.email,
            'Designation': user.designation,
            'Total Leaves': total_leave
        })
    df = pd.DataFrame(data)
    csv_path = f"static/users_export.csv"
    df.to_csv(csv_path, index=False)
    return send_file(csv_path, as_attachment=True, download_name='users_export.csv')

@app.route('/users/edit/<int:user_id>', methods=['GET', 'POST'])
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        user.name = request.form['name']
        user.email = request.form['email']
        user.designation = request.form['designation']
        db.session.commit()
        return redirect('/users')

    return render_template('edit_user.html', user=user)



@app.route('/leave-calendar', methods=['GET', 'POST'])
def leave_calendar():
    users = User.query.all()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))
    month_days = calendar.monthrange(year, month)[1]
    dates = [datetime(year, month, day) for day in range(1, month_days + 1)]

    if request.method == 'POST':
        for user in users:
            Leave.query.filter(
                Leave.user_id == user.id,
                Leave.start_date >= datetime(year, month, 1),
                Leave.start_date <= datetime(year, month, month_days)
            ).delete()

            for day in dates:
                leave_type = request.form.get(f'leave_{user.id}_{day.day}')
                if leave_type and leave_type in ["FD", "HD"]:
                    db.session.add(Leave(user_id=user.id, start_date=day, leave_type=leave_type))

        db.session.commit()
        return redirect(f'/leave-calendar?year={year}&month={month}')

    leaves = {(leave.user_id, leave.start_date.day): leave.leave_type
              for leave in Leave.query.filter(
                  Leave.start_date >= datetime(year, month, 1),
                  Leave.start_date <= datetime(year, month, month_days)
              ).all()}

    prev_month = month - 1 if month > 1 else 12
    next_month = month + 1 if month < 12 else 1
    prev_year = year if month > 1 else year - 1
    next_year = year if month < 12 else year + 1

    return render_template('leave_calendar.html', users=users, dates=dates, leaves=leaves,
                           year=year, month=month, prev_month=prev_month, next_month=next_month,
                           prev_year=prev_year, next_year=next_year)

@app.route('/capacity', methods=['GET'])
def capacity():
    users = User.query.all()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))

    first_day = datetime(year, month, 1)
    month_days = calendar.monthrange(year, month)[1]
    last_day = datetime(year, month, month_days)

    capacity_data = []
    for user in users:
        working_days = [d for d in (first_day + timedelta(days=i) for i in range(month_days)) if d.weekday() < 5]
        leaves = Leave.query.filter(
            Leave.user_id == user.id,
            Leave.start_date >= first_day,
            Leave.start_date <= last_day
        ).all()
        leave_sum = sum([1 if l.leave_type == 'FD' else 0.5 for l in leaves])
        leave_sum = min(leave_sum, len(working_days))
        available_hours = max(0, (len(working_days) - leave_sum) * 8)
        capacity_data.append({
            'user': user,
            'total_days': len(working_days),
            'leaves': leave_sum,
            'capacity_hours': available_hours
        })

    return render_template("capacity.html", capacity_data=capacity_data, year=year, month=month)

@app.route('/daily-capacity', methods=['GET'])
def daily_capacity():
    users = User.query.all()
    selected_date = request.args.get("date")

    if not selected_date:
        return render_template("daily_capacity.html", data=None, total_capacity=None, date=None)

    day = datetime.strptime(selected_date, "%Y-%m-%d")
    total_capacity = 0
    data = []

    jira_logged_hours = get_time_spent_by_user(selected_date)

    for user in users:
        if day.weekday() >= 5:
            available_hours = 0
            leave_type = "Weekend"
        else:
            leave = Leave.query.filter_by(user_id=user.id, start_date=day.date()).first()
            if leave:
                leave_factor = 1 if leave.leave_type == 'FD' else 0.5
                available_hours = max(0, 8 * (1 - leave_factor))
                leave_type = leave.leave_type
            else:
                available_hours = 8
                leave_type = "Present"

        logged_hours = jira_logged_hours.get(user.email, 0)
        total_capacity += available_hours

        data.append({
            "name": user.name,
            "leave_type": leave_type,
            "capacity_hours": available_hours,
            "logged_hours": logged_hours
        })

    return render_template("daily_capacity.html",
                           data=data,
                           total_capacity=total_capacity,
                           date=day)


@app.route('/sprint-capacity', methods=['GET', 'POST'])
def sprint_capacity():
    users = User.query.all()
    start_date = request.form.get("start") or request.args.get("start")
    end_date = request.form.get("end") or request.args.get("end")
    start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None

    sprint_data = []
    total_capacity = 0

    if start and end and start <= end:
        for user in users:
            working_days = [d for d in (start + timedelta(days=i) for i in range((end - start).days + 1)) if d.weekday() < 5]

            leaves = Leave.query.filter(
                Leave.user_id == user.id,
                Leave.start_date >= start.date(),
                Leave.start_date <= end.date()
            ).all()

            leave_map = {(leave.start_date, leave.leave_type) for leave in leaves}
            leave_sum = sum([1 if l_type == 'FD' else 0.5 for (l_date, l_type) in leave_map if l_date in [d.date() for d in working_days]])

            available_hours = max(0, (len(working_days) - leave_sum) * 8)
            sprint_data.append({
                'user': user,
                'total_days': len(working_days),
                'leaves': leave_sum,
                'capacity_hours': available_hours
            })
            total_capacity += available_hours

    return render_template("sprint_capacity.html", users=users, sprint_data=sprint_data,
                           total_capacity=total_capacity, start=start, end=end)


@app.route('/sprint-capacity-export', methods=['POST'])
def sprint_capacity_export():
    start_date = datetime.strptime(request.form['start'], '%Y-%m-%d').date()
    end_date = datetime.strptime(request.form['end'], '%Y-%m-%d').date()
    users = User.query.all()
    data = []
    total_capacity = 0
    for user in users:
        total_days = sum(1 for n in range((end_date - start_date).days + 1)
                         if (start_date + timedelta(n)).weekday() < 5)
        leaves = Leave.query.filter(
            Leave.user_id == user.id,
            Leave.start_date >= start_date,
            Leave.start_date <= end_date
        ).all()
        full_days = sum(1 for l in leaves if l.leave_type == 'FD')
        half_days = sum(0.5 for l in leaves if l.leave_type == 'HD')
        available_days = total_days - (full_days + half_days)
        available_capacity = available_days * 8
        total_capacity += available_capacity
        data.append({
            'User': user.name,
            'Total Working Days': total_days,
            'Leaves (FD + HD)': full_days + half_days,
            'Available Capacity (Hours)': available_capacity
        })
    data.append({
        'User': 'TOTAL',
        'Total Working Days': '',
        'Leaves (FD + HD)': '',
        'Available Capacity (Hours)': total_capacity
    })
    df = pd.DataFrame(data)
    filename = f"sprint_{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.csv"
    csv_path = f'static/{filename}'
    df.to_csv(csv_path, index=False)
    return send_file(csv_path, as_attachment=True, download_name=filename)
@app.route('/timelog', methods=['GET', 'POST'])
def timelog():
    users = User.query.all()
    summary_data = []
    detailed_data = defaultdict(list)
    ordered_detailed_data = {}
    total_logged_by_user = {}
    start = end = selected_function = None

    work_functions = sorted(set([u.designation for u in users if u.designation]))

    if request.method == 'POST':
        start = request.form.get('start')
        end = request.form.get('end')
        selected_function = request.form.get('work_function')

        filtered_users = [u for u in users if u.jira_account_id and (selected_function == 'All' or u.designation == selected_function)]

        if start and end:
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")

            assignee_ids = [u.jira_account_id for u in filtered_users]
            jql = f"""
                issuetype = Sub-task AND
                assignee in ({','.join(assignee_ids)}) AND
                worklogDate >= "{start}" AND
                worklogDate <= "{end}"
            """

            url = f"{JIRA_BASE_URL}/rest/api/2/search"
            params = {
                "jql": jql,
                "fields": "summary,parent,assignee,worklog",
                "maxResults": 1000
            }

            response = requests.get(url, headers=headers, params=params, auth=auth)

            if not response.ok:
                return render_template("timelog.html", summary_data=[], detailed_data={}, start=start, end=end, work_functions=work_functions, selected_function=selected_function)

            issues = response.json().get("issues", [])
            user_map = {u.jira_account_id: u.name for u in filtered_users}
            user_order = [u.name for u in filtered_users]
            ordered_detailed_data = {name: [] for name in user_order}

            for issue in issues:
                issue_key = issue.get("key")
                summary = issue["fields"].get("summary", "")
                parent = issue["fields"].get("parent", {}).get("fields", {}).get("summary", "")
                assignee_id = issue["fields"].get("assignee", {}).get("accountId")

                worklog_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/worklog"
                worklog_resp = requests.get(worklog_url, headers=headers, auth=auth)
                if not worklog_resp.ok:
                    continue

                for worklog in worklog_resp.json().get("worklogs", []):
                    started = worklog.get("started", "")[:10]
                    if start <= started <= end:
                        time_spent = worklog.get("timeSpentSeconds", 0)
                        user_name = user_map.get(worklog["author"].get("accountId"))
                        if user_name:
                            ordered_detailed_data[user_name].append({
                                "issue_key": issue_key,
                                "summary": summary,
                                "parent_summary": parent,
                                "hours": round(time_spent / 3600, 2),
                                "link": f"{JIRA_BASE_URL}/browse/{issue_key}"
                            })
                        if user_name:
                            total_logged_by_user[user_name] = total_logged_by_user.get(user_name, 0) + time_spent / 3600

            working_days = sum(1 for d in (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)) if d.weekday() < 5)

            for name in user_order:
                entries = ordered_detailed_data.get(name, [])
                total_hours = round(sum(item["hours"] for item in entries), 2)
                expected = working_days * 8
                status = "good" if total_hours >= expected else "low"
                filter_url = f"{JIRA_BASE_URL}/issues/?jql=assignee%20in%20({','.join([u.jira_account_id for u in filtered_users if u.name == name])})%20AND%20worklogDate%3E%3D{start}%20AND%20worklogDate%3C%3D{end}"
                summary_data.append({
                    "user": name,
                    "total_hours": total_hours,
                    "expected": expected,
                    "status": status,
                    "link": filter_url,
                    "anchor": name.replace(' ', '_').replace('.', '').lower()
                })

    return render_template("timelog.html", summary_data=summary_data, detailed_data=ordered_detailed_data, start=start, end=end, work_functions=work_functions, selected_function=selected_function)




@app.route('/generate-ai-summary', methods=['POST'])
def generate_ai_summary():
    from openai import OpenAI
    import json

    print("🔍 Debug: Checking session contents...")
    print("session keys:", list(session.keys()))
    print("summary_data (raw):", session.get('summary_data'))
    print("detailed_data (raw):", session.get('detailed_data'))

    # Get from session first
    raw_summary_data = session.get('summary_data', [])
    raw_detailed_data = session.get('detailed_data', {})

    try:
        # If they are strings, parse them
        summary_data = json.loads(raw_summary_data) if isinstance(raw_summary_data, str) else raw_summary_data
        detailed_data = json.loads(raw_detailed_data) if isinstance(raw_detailed_data, str) else raw_detailed_data
    except Exception as e:
        print("❌ JSON parsing error:", str(e))
        return "Failed to parse session data", 500

    if not summary_data or not detailed_data:
        print("⚠️ No data found to summarize.")
        return "No data to summarize.", 400

    # Build prompt
    prompt = (
        "Create a detailed but concise summary of the following Jira worklogs:\n\n"
        "Each entry includes: user, hours logged, expected hours, and their task breakdown.\n"
        "Use bullet points for each user, and show their status (OK/LOW), top tasks (if any), and total hours.\n\n"
    )

    for row in summary_data:
        status = "LOW" if row['status'] == 'low' else "OK"
        logs = detailed_data.get(row['user'], [])
        task_summaries = ", ".join([item['summary'] for item in logs[:3]]) if logs else "No tasks"
        prompt += (
            f"- {row['user']}: Logged {row['total_hours']} hrs, "
            f"Expected {row['expected']} hrs — Status: {status}. "
            f"Top Tasks: {task_summaries}\n"
        )

    # Call OpenAI
    client = OpenAI()
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a helpful assistant that summarizes Jira time logs for a team manager. "
                    "Make the summary easy to read, formatted, and insightful."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        max_tokens=1000,
    )

    ai_summary = response.choices[0].message.content.strip()
       

    # Format line breaks and bullets for HTML
    formatted = ai_summary.replace("\n", "<br>").replace("•", "&#8226;").replace("-", "&#8211;")

    html_output = f"""
    <div class="card mt-3 border-success">
        <div class="card-header bg-success text-white fw-bold">
            AI-Generated Jira Timelog Summary
        </div>
        <div class="card-body" style="max-height: 500px; overflow-y: auto;">
            <p style="white-space: pre-wrap;">{formatted}</p>
        </div>
    </div>
    """

    return html_output




@app.route('/update-jira-id', methods=['GET', 'POST'])
def update_jira_id():
    users = User.query.all()
    
    if request.method == 'POST':
        for user in users:
            jira_id = request.form.get(f'jira_{user.id}')
            if jira_id is not None:
                user.jira_account_id = jira_id
        db.session.commit()
        return redirect('/update-jira-id')

    return render_template('update_jira_id.html', users=users)

@app.route("/reset-session")
def reset_session():
    session.clear()
    return "Session cleared!"



import requests
import base64
from flask import Flask, request, render_template, url_for
from werkzeug.utils import secure_filename
import os


@app.route('/visual-feedback', methods=['GET', 'POST'])
def visual_feedback():
    feedback_html = None
    image_url = None
    page_url = None

    if request.method == 'POST':
        input_type = request.form.get('input_type')
        access_key = '8akGljPIc5sEfw'  # Replace with your actual ScreenshotOne access key

        image_b64 = None

        if input_type == "url":
            page_url = request.form.get('page_url')
            if page_url:
                screenshot_url = f"https://api.screenshotone.com/take?access_key={access_key}&url={page_url}&format=png"

                response = requests.get(screenshot_url)
                if response.status_code == 200:
                    filename = secure_filename(f"{page_url.replace('https://', '').replace('/', '_')}.png")
                    filepath = os.path.join('static/uploads', filename)
                    os.makedirs(os.path.dirname(filepath), exist_ok=True)
                    with open(filepath, 'wb') as f:
                        f.write(response.content)

                    image_url = url_for('static', filename=f"uploads/{filename}")
                    with open(filepath, "rb") as f:
                        image_b64 = base64.b64encode(f.read()).decode()
                else:
                    feedback_html = f"❌ Failed to capture screenshot. Status code: {response.status_code}"

        elif input_type == "upload":
            image = request.files.get('screenshot')
            if image:
                filename = secure_filename(image.filename)
                filepath = os.path.join('static/uploads', filename)
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                image.save(filepath)

                image_url = url_for('static', filename=f"uploads/{filename}")
                with open(filepath, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode()

        # Proceed with AI analysis if image_b64 is available
        if image_b64:
            prompt_text = (
                "Please analyze this UI screenshot thoroughly:\n\n"
                "1. Check for **UI layout and alignment issues** — spacing, padding, misalignments, responsiveness.\n"
                "2. Identify any **spelling or grammatical mistakes**.\n"
                "3. Suggest improvements or best practices where applicable.\n\n"
                "Format the response with markdown sections like:\n"
                "### Summary\n### Layout Issues\n### Spelling Errors\n### Suggestions"
            )

            try:
                client = OpenAI()
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a helpful UI reviewer analyzing screenshots. Use markdown formatting."},
                        {"role": "user", "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"}}
                        ]}
                    ],
                    max_tokens=800
                )
                feedback = response.choices[0].message.content if response.choices else "No feedback returned."
                feedback_html = md_convert(feedback)

            except Exception as e:
                feedback_html = f"❌ Error during AI analysis: {str(e)}"

    return render_template("visual_feedback.html", image_url=image_url, page_url=page_url, feedback=feedback_html)





@app.route('/sprint-calendar')
def sprint_calendar():
    board_id = 332  # ✅ Make sure this is your correct board ID
    sprints = fetch_jira_sprints(board_id)

    now = datetime.now()
    current_month = now.month
    current_year = now.year

    events = []
    for s in sprints:
        if "startDate" in s and "endDate" in s:
            try:
                start_date = datetime.strptime(s["startDate"][:10], "%Y-%m-%d")
                end_date = datetime.strptime(s["endDate"][:10], "%Y-%m-%d")

                # ✅ Filter: show sprints that start or end this month
                if (start_date.month == current_month and start_date.year == current_year) or \
                   (end_date.month == current_month and end_date.year == current_year):

                    events.append({
                        "title": s["name"],
                        "start": s["startDate"][:10],
                        "end": s["endDate"][:10],
                        "color": "blue" if s["state"] == "active" else "gray",
                        "extendedProps": {
                            "status": s["state"],
                            "goal": s.get("goal", "No goal set")
                        }
                    })
            except Exception as e:
                print("⚠️ Date parsing error:", e)

    print("🔍 Filtered Events:", events)
    current_month_label = now.strftime('%B %Y')
    return render_template("sprint_calendar.html", events=events, current_month=current_month_label)








if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)

