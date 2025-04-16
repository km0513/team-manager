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

import re
import os
import json
import base64
from datetime import datetime, timedelta
import calendar
from datetime import date




import requests
from requests.auth import HTTPBasicAuth
from collections import defaultdict

# Initialize Flask app
app = Flask(__name__)
app.config['SERVER_NAME'] = 'teammanagerqai.herokuapp.com'
from generate_testcases_route import testcase_bp
app.register_blueprint(testcase_bp)





load_dotenv()  # This loads the .env file
print(" OpenAI Key begins with:", os.getenv("OPENAI_API_KEY")[:8])
from openai import OpenAI
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
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
JIRA_API_TOKEN = os.getenv('JIRA_API_TOKEN')
auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json"}

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100))
    designation = db.Column(db.String(100))
    jira_account_id = db.Column(db.String(100)) 
    role = db.Column(db.String(50), default='Team Member')

class Leave(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    start_date = db.Column(db.Date)
    leave_type = db.Column(db.String(50))
    user = db.relationship('User', backref='leaves')

class Holiday(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    description = db.Column(db.String(200))







# Helper functions
def get_time_spent_by_user(date):
    return get_time_spent_by_user_range(date, date)

import logging
logging.basicConfig(level=logging.INFO)

def fetch_jira_account_id(email):
    url = f"{JIRA_BASE_URL}/rest/api/3/user/search?query={email}"
    response = requests.get(url, headers=headers, auth=auth)
    if response.ok:
        results = response.json()
        logging.info(f"JIRA SEARCH for {email}: {results}")
        if results:
            return results[0].get("accountId")
    return None




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

    print(" Filtered Events for Current Month:", filtered_events)
    return filtered_events


def fetch_jira_sprints(board_id):
    url = f"{JIRA_BASE_URL}/rest/agile/1.0/board/{board_id}/sprint"
    response = requests.get(url, auth=auth)

    if response.ok:
        sprints = response.json().get('values', [])
        print(" Fetched Sprints:", sprints)
        return sprints
    else:
        print(" Jira Sprint Fetch Failed:", response.status_code, response.text)
        return []



# Routes

@app.template_filter('round_half')
def round_half(value):
    return round(float(value) * 2) / 2

@app.before_request
def require_login():
    if 'logged_in' not in session and request.endpoint not in ['login', 'static','HelperQA_AI','generate_testcases','timelog_today']:
        return redirect('/login')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'Supersecure2025':
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

    # Calculate available capacity per function
    function_capacity = {}
    standard_hours = 8
    for user in User.query.all():
        # Check if user is on leave today
        leave = Leave.query.filter_by(user_id=user.id, start_date=today).first()
        available_hours = 0 if leave else standard_hours
        func = user.designation or 'Unknown'
        function_capacity.setdefault(func, 0)
        function_capacity[func] += available_hours

    # Sort by function name for display
    function_capacity = dict(sorted(function_capacity.items()))

    return render_template(
        'dashboard.html',
        users_on_leave=user_names,
        today=today,
        total_users=total_users,
        function_capacity=function_capacity
    )




@app.route('/users', methods=['GET', 'POST'])
def users():
    page = int(request.args.get('page', 1))
    per_page = 10

    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        designation = request.form['designation']

        if User.query.filter_by(email=email).first():
            return " User with this email already exists."

        jira_account_id = fetch_jira_account_id(email)
        user = User(name=name, email=email, designation=designation, jira_account_id=jira_account_id)
        db.session.add(user)
        db.session.commit()
        return redirect('/users')

    pagination = User.query.paginate(page=page, per_page=per_page)
    return render_template('users.html', users=pagination.items, pagination=pagination)







from flask import send_file
from io import BytesIO

@app.route('/import-users', methods=['POST'])
def import_users():
    file = request.files.get('excel_file')
    if not file or file.filename == '':
        return "No file selected", 400

    try:
        df = pd.read_excel(file)
        existing_emails = {u.email.lower() for u in User.query.all()}
        skipped_rows = []

        for index, row in df.iterrows():
            name = str(row.get('Name')).strip()
            email = str(row.get('Email')).strip().lower()
            designation = str(row.get('Designation')).strip()

            if not name or not email or not designation:
                skipped_rows.append(f"Row {index + 2}: Missing required fields.")
                continue

            if email in existing_emails:
                skipped_rows.append(f"Row {index + 2}: Duplicate email '{email}'")
                continue

            jira_account_id = fetch_jira_account_id(email)
            if not jira_account_id:
                skipped_rows.append(f"Row {index + 2}: Jira ID not found for '{email}'")
                continue

            user = User(name=name, email=email, designation=designation, jira_account_id=jira_account_id)
            db.session.add(user)
            existing_emails.add(email)

        db.session.commit()

        if skipped_rows:
            # Create Excel with skipped rows
            skipped_df = pd.DataFrame({'Issue': skipped_rows})
            output = BytesIO()
            filename = f"user_import_errors_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                skipped_df.to_excel(writer, index=False, sheet_name='Skipped Users')
            output.seek(0)
            return send_file(output, download_name=filename, as_attachment=True)

        return redirect('/users')

    except Exception as e:
        return str(e), 500



@app.route('/export-timelog-links')
def export_timelog_links():
    users = User.query.all()
    rows = []
    for user in users:
        rows.append({
            'Name': user.name,
            'Email': user.email,
            'Designation': user.designation,
            'Timelog Link': request.url_root.strip('/') + url_for('timelog_today', user_email=user.email)
        })

    df = pd.DataFrame(rows)
    csv_path = 'static/timelog_links.csv'
    df.to_csv(csv_path, index=False)
    return send_file(csv_path, as_attachment=True, download_name='timelog_links.csv')


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

@app.route('/users/delete/<int:user_id>', methods=['GET'])
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()
    return redirect('/users')


@app.route('/holidays', methods=['GET', 'POST'])
def manage_holidays():
    if request.method == 'POST':
        date_str = request.form['date']
        description = request.form['description']
        holiday_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        # Avoid duplicates
        if not Holiday.query.filter_by(date=holiday_date).first():
            db.session.add(Holiday(date=holiday_date, description=description))
            db.session.commit()

    holidays = Holiday.query.order_by(Holiday.date).all()
    return render_template('holidays.html', holidays=holidays)


@app.route('/leave-calendar', methods=['GET', 'POST'])
def leave_calendar():
    users = User.query.all()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))
    month_days = calendar.monthrange(year, month)[1]
    dates = [datetime(year, month, day) for day in range(1, month_days + 1)]

    # Handle saving leave data
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

    # Load existing leaves
    leaves = {(leave.user_id, leave.start_date.day): leave.leave_type
              for leave in Leave.query.filter(
                  Leave.start_date >= datetime(year, month, 1),
                  Leave.start_date <= datetime(year, month, month_days)
              ).all()}

    # Previous & next month/year values for navigation
    prev_month = month - 1 if month > 1 else 12
    next_month = month + 1 if month < 12 else 1
    prev_year = year if month > 1 else year - 1
    next_year = year if month < 12 else year + 1

    # Group dates by ISO week
    weeks = {}
    for date in dates:
        week_key = f"{date.isocalendar()[0]}-W{date.isocalendar()[1]}"
        weeks.setdefault(week_key, []).append(date)

    holiday_dates = {h.date for h in Holiday.query.filter(
    Holiday.date >= datetime(year, month, 1).date(),
    Holiday.date <= datetime(year, month, month_days).date()
).all()}

    return render_template('leave_calendar.html',
                           users=users,
                           dates=dates,
                           leaves=leaves,
                           year=year,
                           month=month,
                           current_date=datetime.today(),
                           prev_month=prev_month,
                           next_month=next_month,
                           prev_year=prev_year,
                           next_year=next_year,
                           weeks=weeks,holidays=holiday_dates)

@app.route('/holiday-calendar', methods=['GET'])
def holiday_calendar():
    year = int(request.args.get('year', datetime.now().year))
    holidays = Holiday.query.filter(Holiday.date.like(f'{year}%')).all()

    # Generate dates for the calendar view
    first_day = datetime(year, 1, 1)
    last_day = datetime(year, 12, 31)
    dates = [first_day + timedelta(days=i) for i in range((last_day - first_day).days + 1)]

    return render_template('holiday_calendar.html', holidays=holidays, dates=dates, year=year)

import csv
from flask import Response



from flask import Response
from io import StringIO
import csv

@app.route('/leave-calendar-export')
def export_leaves():
    leaves = db.session.query(
        User.name,
        User.email,
        Leave.start_date,
        Leave.leave_type
    ).join(Leave, User.id == Leave.user_id).order_by(Leave.start_date.desc()).all()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Email', 'Leave Date', 'Leave Type'])

    for name, email, start_date, leave_type in leaves:
        if leave_type not in ['FD', 'HD', 'Half', 'Full']:  # ensure leave_type is valid
            continue
        writer.writerow([name, email, start_date.strftime('%d-%m-%Y'), leave_type])

    output.seek(0)
    return Response(
        output,
        mimetype='text/csv',
        headers={"Content-Disposition": "attachment;filename=leave_records.csv"}
    )



@app.route('/capacity', methods=['GET'])
def capacity():
    users = User.query.all()
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))
    selected_function = request.args.get('function', 'All')

    first_day = datetime(year, month, 1)
    month_days = calendar.monthrange(year, month)[1]
    last_day = datetime(year, month, month_days)

    # Get holidays just once
    holiday_dates = {h.date for h in Holiday.query.filter(
        Holiday.date >= first_day.date(), Holiday.date <= last_day.date()).all()
    }

    filtered_users = [u for u in users if selected_function == 'All' or u.designation == selected_function]

    capacity_data = []
    total_capacity = 0
    total_leaves = 0

    for user in filtered_users:
        working_days = [
            d for d in (first_day + timedelta(days=i) for i in range(month_days))
            if d.weekday() < 5 and d.date() not in holiday_dates
        ]

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
        total_leaves += leave_sum
        total_capacity += available_hours

    functions = sorted(set(u.designation for u in users if u.designation))
    return render_template("capacity.html", capacity_data=capacity_data, year=year, month=month,
                           functions=functions, selected_function=selected_function,
                           total_capacity=total_capacity, total_leaves=total_leaves)





@app.route('/sprint-capacity', methods=['GET', 'POST'])
def sprint_capacity():
    users = User.query.all()
    start_date = request.form.get("start") or request.args.get("start")
    end_date = request.form.get("end") or request.args.get("end")
    selected_function = request.form.get("function") or request.args.get("function", "All")
    start = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
    end = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None

    sprint_data = []
    total_capacity = 0

    if start and end and start <= end:
        holiday_dates = {h.date for h in Holiday.query.filter(
            Holiday.date >= start.date(), Holiday.date <= end.date()).all()
        }

        filtered_users = [u for u in users if selected_function == "All" or u.designation == selected_function]

        for user in filtered_users:
            working_days = [d for d in (start + timedelta(days=i) for i in range((end - start).days + 1))
                            if d.weekday() < 5 and d.date() not in holiday_dates]

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

    functions = sorted(set(u.designation for u in users if u.designation))
    return render_template("sprint_capacity.html", users=users, sprint_data=sprint_data,
                           total_capacity=total_capacity, start=start, end=end,
                           functions=functions, selected_function=selected_function)





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
            print("JQL:", jql)

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
                                "link": f"{JIRA_BASE_URL}/browse/{issue_key}",
                                "started": started
                            })
                        if user_name:
                            total_logged_by_user[user_name] = total_logged_by_user.get(user_name, 0) + time_spent / 3600

            # Get working weekdays in range
            all_working_days = [d for d in (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)) if d.weekday() < 5]

            for name in user_order:
                user = next((u for u in filtered_users if u.name == name), None)

                leave_days = Leave.query.filter(
                    Leave.user_id == user.id,
                    Leave.start_date >= start_date.date(),
                    Leave.start_date <= end_date.date()
                ).all()

                leave_map = {(leave.start_date, leave.leave_type) for leave in leave_days}
                leave_sum = sum([1 if l_type == 'FD' else 0.5 for (l_date, l_type) in leave_map if l_date in [d.date() for d in all_working_days]])
                available_days = max(0, len(all_working_days) - leave_sum)
                expected = available_days * 8

                entries = ordered_detailed_data.get(name, [])
                total_hours = round(sum(item["hours"] for item in entries), 2)
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


@app.route('/timelog-today', methods=['GET', 'POST'])
@app.route('/timelog-today/<user_email>', methods=['GET'])
def timelog_today(user_email=None):
    users = User.query.all()
    work_functions = sorted(set([u.designation for u in users if u.designation]))

    is_user_specific = user_email is not None

    selected_function = request.form.get('work_function') if request.method == 'POST' else request.args.get('work_function', 'All')
    filtered_users = [u for u in users if u.jira_account_id and (selected_function == 'All' or u.designation == selected_function)]

    if is_user_specific:
        filtered_users = [u for u in users if u.email == user_email and u.jira_account_id]

    summary_data = []
    detailed_data = defaultdict(list)
    user_map = {u.jira_account_id: u.name for u in filtered_users}
    user_email_map = {u.jira_account_id: u.email for u in filtered_users}
    user_id_map = {u.jira_account_id: u.id for u in filtered_users}
    user_order = [u.name for u in filtered_users]
    ordered_detailed_data = {name: [] for name in user_order}

    date_str = request.args.get('date')
    if date_str:
        current_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    else:
        current_date = datetime.today().date()

    today_str = current_date.strftime('%Y-%m-%d')
    display_date_str = current_date.strftime('%-d %B %Y') if os.name != 'nt' else current_date.strftime('%#d %B %Y')

    assignee_ids = [u.jira_account_id for u in filtered_users]

    jql = f"""
        issuetype = Sub-task AND
        assignee in ({','.join(assignee_ids)}) AND
        worklogDate = "{today_str}"
    """

    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    params = {
        "jql": jql,
        "fields": "summary,parent,assignee,worklog",
        "maxResults": 1000
    }

    response = requests.get(url, headers=headers, params=params, auth=auth)
    if not response.ok:
        return render_template("timelog_today.html", summary_data=[], detailed_data={}, start=today_str, end=today_str, work_functions=work_functions, selected_function=selected_function, previous_date=None, next_date=None, is_today_view=True, disable_date_inputs=True, display_date_str=display_date_str, is_user_specific=is_user_specific, user_email=user_email)

    issues = response.json().get("issues", [])

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
            if started == today_str:
                time_spent = worklog.get("timeSpentSeconds", 0)
                user_name = user_map.get(worklog["author"].get("accountId"))
                if user_name:
                    ordered_detailed_data[user_name].append({
                        "issue_key": issue_key,
                        "summary": summary,
                        "parent_summary": parent,
                        "hours": round(time_spent / 3600, 2),
                        "link": f"{JIRA_BASE_URL}/browse/{issue_key}",
                        "started": started
                    })

    for name in user_order:
        entries = ordered_detailed_data.get(name, [])
        total_hours = round(sum(item["hours"] for item in entries), 2)
        email = next((u.email for u in filtered_users if u.name == name), '')
        user_id = next((u.id for u in filtered_users if u.name == name), None)

        leave_status = None
        if user_id:
            leave = Leave.query.filter_by(user_id=user_id, start_date=current_date).first()
            if leave:
                leave_status = f"On Leave ({leave.leave_type})"

        if leave_status:
            display_hours = leave_status
            numeric_hours = 0.0
        else:
            display_hours = total_hours
            numeric_hours = total_hours

        summary_data.append({
            "user": name,
            "total_hours": display_hours,
            "numeric_hours": numeric_hours,
            "expected": 8,
            "status": "good" if not leave_status and numeric_hours >= 8 else ("onleave" if leave_status else "low"),
            "link": url_for('timelog_today', user_email=email, date=today_str) if is_user_specific else url_for('timelog_today', date=today_str, work_function=selected_function),
            "anchor": name.replace(' ', '_').replace('.', '').lower(),
            "copy_url": request.url_root.strip('/') + url_for('timelog_today', user_email=email)
        })

    previous_date = (current_date - timedelta(days=1)).strftime('%Y-%m-%d')
    next_date = (current_date + timedelta(days=1)).strftime('%Y-%m-%d') if current_date < date.today() else None

    return render_template("timelog_today.html",
                           summary_data=summary_data,
                           detailed_data=ordered_detailed_data,
                           start=today_str,
                           end=today_str,
                           work_functions=work_functions,
                           selected_function=selected_function,
                           previous_date=previous_date,
                           next_date=next_date,
                           is_today_view=True,
                           disable_date_inputs=True,
                           display_date_str=display_date_str,
                           is_user_specific=is_user_specific,
                           user_email=user_email)












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


@app.route('/HelperQA-AI', methods=['GET', 'POST'])
def HelperQA_AI():
    feedback_html = None
    image_url = None
    page_url = None

    if request.method == 'POST':
        input_type = request.form.get('input_type')
        ai_mode = request.form.get('ai_mode', 'review')  # default to review
        access_key = '8akGljPIc5sEfw'  # Replace with your ScreenshotOne key

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
                    feedback_html = f" Failed to capture screenshot. Status code: {response.status_code}"

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

        # Run OpenAI analysis
        if image_b64:
            if ai_mode == 'review':
                prompt_text = (
                    "Please analyze this UI screenshot thoroughly:\n\n"
                    "1. Check for **UI layout and alignment issues** — spacing, padding, misalignments, responsiveness.\n"
                    "2. Identify any **spelling or grammatical mistakes**.\n"
                    "3. Suggest improvements or best practices where applicable.\n\n"
                    "Format the response with markdown sections like:\n"
                    "### Summary\n### Layout Issues\n### Spelling Errors\n### Suggestions"
                )
                system_message = "You are a helpful UI reviewer analyzing screenshots. Use markdown formatting."
            elif ai_mode == 'testcases':
                prompt_text = (
                    "Based on this UI screenshot, draft **relevant test cases** covering UI, UX, functionality, edge cases, and responsiveness.\n"
                    "Organize them in markdown format with sections like:\n"
                    "### UI Test Cases\n### Functional Test Cases\n### Negative/Edge Cases\n\n"
                    "Each test case should include a title and a short description."
                )
                system_message = "You are an expert test engineer. Draft comprehensive test cases from UI screenshots."

            try:
                client = OpenAI()
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}", "detail": "high"}}
                        ]}
                    ],
                    max_tokens=800
                )
                feedback = response.choices[0].message.content if response.choices else "No feedback returned."
                # Remove fenced code block (like ```markdown ... ```)
                cleaned = re.sub(r"```(?:markdown)?\n?", "", feedback).strip()
                feedback_html = md_convert(cleaned)

            except Exception as e:
                feedback_html = f" Error during AI analysis: {str(e)}"

    return render_template("HelperQA-AI.html", image_url=image_url, page_url=page_url, feedback=feedback_html)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
