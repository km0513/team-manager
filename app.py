from flask import Flask, render_template, request, redirect, url_for, session, jsonify
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
from datetime import datetime, timedelta, date
import calendar
from datetime import date
import pytz

import requests
from requests.auth import HTTPBasicAuth
from collections import defaultdict

from jira_worklog_batch import get_epoch_ms, fetch_worklog_ids_updated_since, fetch_worklogs_by_ids, fetch_issue_details_bulk

from generate_testcases_core import generate_testcases_core
from generate_testcases_route import fetch_jira_description
from ai_utils import AIUtility

# Initialize Flask app
app = Flask(__name__)
app.config['SERVER_NAME'] = 'teammanagerqai.herokuapp.com'
# Load environment variables from .env file
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

# Email configuration
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

# Instantiate the AI utility once (at the top of your app)
ai_util = AIUtility(
    openai_api_key=os.getenv("OPENAI_API_KEY"),
    jira_base_url=os.getenv("JIRA_BASE_URL"),
    jira_email=os.getenv("JIRA_EMAIL"),
    jira_token=os.getenv("JIRA_API_TOKEN")
)

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
    if 'logged_in' not in session and request.endpoint not in ['login', 'static', 'HelperQA_AI', 'generate_testcases', 'generate_testcases_auth',
            'timelog_today', 'users', 'export_users', 'export_timelog_links', 'mytimelogs',
            'user_timelog', 'HelperQA_AI', 'generate_testcases']:
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
def root():
    # If user is logged in, redirect to /dashboard
    if session.get('logged_in'):
        return redirect(url_for('dashboard_admin'))
    # Otherwise, show public or login page (customize as needed)
    return redirect(url_for('login'))

@app.route('/dashboard')
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

    # --- Holiday and Weekend Logic for Dashboard ---
    holiday = Holiday.query.filter_by(date=today).first()
    is_holiday = holiday is not None
    holiday_name = holiday.description if holiday else None
    is_weekend = today.weekday() >= 5

    if is_holiday or is_weekend:
        function_capacity = {func: 0 for func in function_capacity}

    return render_template(
        'dashboard.html',
        users_on_leave=user_names,
        today=today,
        total_users=total_users,
        function_capacity=function_capacity,
        is_holiday=is_holiday,
        holiday_name=holiday_name,
        is_weekend=is_weekend
    )

@app.route('/dashboard')
def dashboard_admin():
    users = User.query.all()
    today = datetime.now().date()
    total_users = len(users)
    users_on_leave = []
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

    # --- Holiday and Weekend Logic for Dashboard ---
    holiday = Holiday.query.filter_by(date=today).first()
    is_holiday = holiday is not None
    holiday_name = holiday.description if holiday else None
    is_weekend = today.weekday() >= 5

    if is_holiday or is_weekend:
        function_capacity = {func: 0 for func in function_capacity}

    return render_template(
        'dashboard.html',
        users_on_leave=users_on_leave,
        today=today,
        total_users=total_users,
        function_capacity=function_capacity,
        is_holiday=is_holiday,
        holiday_name=holiday_name,
        is_weekend=is_weekend
    )

@app.route('/users', methods=['GET'])
def users():
    if session.get('logged_in'):
        page = int(request.args.get('page', 1))
        per_page = 10
        pagination = User.query.paginate(page=page, per_page=per_page)
        users = pagination.items
        # Always pass both users and pagination when logged in
        return render_template('users.html', users=users, pagination=pagination, user=None, email_checked=False)
    else:
        email = request.args.get('email')
        user = None
        email_checked = False
        if email:
            user = User.query.filter_by(email=email.strip().lower()).first()
            email_checked = True
        # Always pass users and pagination as None when not logged in
        return render_template('users.html', user=user, email_checked=email_checked, users=None, pagination=None)

@app.route('/users', methods=['POST'])
def users_post():
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
            # Remove all leaves for this user in the selected month
            Leave.query.filter(
                Leave.user_id == user.id,
                Leave.start_date >= datetime(year, month, 1),
                Leave.start_date <= datetime(year, month, month_days)
            ).delete()

            for day in dates:
                leave_type = request.form.get(f'leave_{user.id}_{day.day}')
                if leave_type and leave_type in ["FD", "HD"]:
                    # Check if a leave already exists for this user on this day
                    existing_leave = Leave.query.filter_by(user_id=user.id, start_date=day).first()
                    if not existing_leave:
                        db.session.add(Leave(user_id=user.id, start_date=day, leave_type=leave_type))
                    else:
                        # Update the leave type if needed (optional, or skip to prevent duplicates)
                        existing_leave.leave_type = leave_type

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

    # FIX: Provide a dictionary of date: description for holidays
    holiday_dict = {h.date: h.description for h in Holiday.query.filter(
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
                           weeks=weeks,
                           holidays=holiday_dict)

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

@app.route('/leave-calendar-export')
def export_leaves():
    # Export all users who are on leave (forget learner filter)
    leaves = (
        db.session.query(User.name, User.email, Leave.start_date, Leave.leave_type)
        .join(Leave, User.id == Leave.user_id)
        .order_by(Leave.start_date.desc())
        .all()
    )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Name', 'Email', 'Leave Date', 'Leave Type'])

    for name, email, start_date, leave_type in leaves:
        if leave_type not in ['FD', 'HD', 'Half', 'Full']:
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

            leave_sum = sum([1 if l.leave_type == 'FD' else 0.5 for l in leaves])
            leave_sum = min(leave_sum, len(working_days))
            available_hours = max(0, (len(working_days) - leave_sum) * 8)

            sprint_data.append({
                'user_name': user.name,
                'total_days': len(working_days),
                'leaves': leave_sum,
                'capacity_hours': available_hours
            })
            total_capacity += available_hours

    print("SPRINT DATA:", sprint_data)  # Debug print
    functions = sorted(set(u.designation for u in users if u.designation))
    return render_template("sprint_capacity.html", users=users, my_sprint_data=sprint_data,
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

from timelog_cache import save_to_cache, load_from_cache, clear_timelog_cache

@app.route('/timelog', methods=['GET', 'POST'])
def timelog():
    users = User.query.all()
    summary_data = []
    detailed_data = defaultdict(list)
    ordered_detailed_data = {}
    total_logged_by_user = {}
    start = end = selected_function = None

    work_functions = sorted(set([u.designation for u in users if u.designation]))
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    current_date = now.strftime('%Y-%m-%d')

    # User pagination parameters
    user_page = int(request.args.get('user_page', 1))
    users_per_page = 10
    filtered_users = users
    if request.method == 'POST':
        start = request.form.get('start')
        end = request.form.get('end')
        selected_function = request.form.get('work_function')
        show_details = True  # Always show details after fetch
        clear_timelog_cache()
    else:
        start = request.args.get('start')
        end = request.args.get('end')
        selected_function = request.args.get('work_function', 'All')
        show_details = request.args.get('show_details', '0') == '1'
    if selected_function and selected_function != 'All':
        filtered_users = [u for u in users if u.jira_account_id and u.designation == selected_function]
    else:
        filtered_users = [u for u in users if u.jira_account_id]
    total_users = len(filtered_users)
    user_start = (user_page - 1) * users_per_page
    user_end = user_start + users_per_page
    paginated_users = filtered_users[user_start:user_end]
    next_user_page = user_page + 1 if user_end < total_users else None
    prev_user_page = user_page - 1 if user_page > 1 else None

    overall_total_logged = 0
    overall_total_expected = 0
    cache_params = {"start": start, "end": end, "user_ids": [u.jira_account_id for u in filtered_users]}
    cache_data = load_from_cache(cache_params)
    if not cache_data:
        # Fetch from Jira and cache using /worklog/updated for efficiency
        if start and end:
            since_epoch = get_epoch_ms(start)
            until_epoch = get_epoch_ms(end) + 24*3600*1000 - 1
            # 1. Get all updated worklog IDs since start
            worklog_ids = fetch_worklog_ids_updated_since(JIRA_BASE_URL, headers, auth, since_epoch)
            # 2. Fetch worklog details in batch
            all_worklogs = fetch_worklogs_by_ids(JIRA_BASE_URL, headers, auth, worklog_ids)
            # 3. Filter worklogs by date, user, and build user map
            user_map_all = {u.jira_account_id: u.name for u in filtered_users}
            detailed_data_all = defaultdict(list)
            overall_total_logged = 0
            overall_total_expected = 0
            expected_map = {}
            # Collect all unique issue IDs
            issue_ids = set()
            for wl in all_worklogs:
                author_id = wl.get('author', {}).get('accountId')
                started = wl.get('started', '')[:10]
                if author_id in user_map_all and start <= started <= end:
                    issue_id = str(wl.get('issueId'))
                    issue_ids.add(issue_id)
            print("[DEBUG] Issue IDs sent to Jira bulk API:", issue_ids)
            # Fetch issue details in bulk (fallback to individual if bulk fails)
            issue_details = fetch_issue_details_bulk(JIRA_BASE_URL, headers, auth, issue_ids) if issue_ids else {}
            if not issue_details:
                print("[DEBUG] Bulk API returned no data, falling back to individual issue fetches.")
                from jira_worklog_batch import fetch_issue_details_individual
                issue_details = fetch_issue_details_individual(JIRA_BASE_URL, headers, auth, issue_ids)
            print("[DEBUG] Jira issue details response (truncated):", str(issue_details)[:500])
            for wl in all_worklogs:
                author_id = wl.get('author', {}).get('accountId')
                started = wl.get('started', '')[:10]
                if author_id in user_map_all and start <= started <= end:
                    user_name = user_map_all[author_id]
                    hours = round(wl.get('timeSpentSeconds', 0) / 3600, 2)
                    issue_id = str(wl.get('issueId'))
                    issue_info = issue_details.get(issue_id, {})
                    issue_key = issue_info.get('key', '')
                    summary = issue_info.get('summary', '')
                    parent_summary = issue_info.get('parent_summary', '')
                    detailed_data_all[user_name].append({
                        "issue_key": issue_key,
                        "summary": summary,
                        "parent_summary": parent_summary,
                        "hours": hours,
                        "link": f"{JIRA_BASE_URL}/browse/{issue_key}" if issue_key else '',
                        "started": started
                    })
            # Calculate expected for all users
            start_date = datetime.strptime(start, "%Y-%m-%d")
            end_date = datetime.strptime(end, "%Y-%m-%d")
            all_working_days = [d for d in (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)) if d.weekday() < 5]
            for user in filtered_users:
                leave_days = Leave.query.filter(
                    Leave.user_id == user.id,
                    Leave.start_date >= start_date.date(),
                    Leave.start_date <= end_date.date()
                ).all()
                leave_map = {(leave.start_date, leave.leave_type) for leave in leave_days}
                leave_sum = sum([1 if l_type == 'FD' else 0.5 for (l_date, l_type) in leave_map if l_date in [d.date() for d in all_working_days]])
                available_days = max(0, len(all_working_days) - leave_sum)
                expected = available_days * 8
                total_hours = round(sum(item["hours"] for item in detailed_data_all.get(user.name, [])), 2)
                overall_total_logged += total_hours
                overall_total_expected += expected
                expected_map[user.name] = expected
            # Save all data to cache
            save_to_cache(cache_params, {
                "detailed_data_all": detailed_data_all,
                "overall_total_logged": overall_total_logged,
                "overall_total_expected": overall_total_expected,
                "expected_map": expected_map
            })
            cache_data = load_from_cache(cache_params)
    else:
        overall_total_logged = cache_data["overall_total_logged"]
        overall_total_expected = cache_data["overall_total_expected"]

    # Only build user table if show_details is True
    if show_details and cache_data:
        detailed_data_all = cache_data["detailed_data_all"]
        expected_map = cache_data["expected_map"]
        user_order = [u.name for u in paginated_users]
        ordered_detailed_data = {name: detailed_data_all.get(name, []) for name in user_order}
        for name in user_order:
            total_hours = round(sum(item["hours"] for item in ordered_detailed_data.get(name, [])), 2)
            expected = expected_map.get(name, 0)
            status = "good" if total_hours >= expected else "low"
            filter_url = f"{JIRA_BASE_URL}/issues/?jql=assignee%20in%20({','.join([u.jira_account_id for u in paginated_users if u.name == name])})%20AND%20worklogDate%3E%3D{start}%20AND%20worklogDate%3C%3D{end}"
            summary_data.append({
                "user": name,
                "total_hours": total_hours,
                "expected": expected,
                "status": status,
                "link": filter_url,
                "anchor": name.replace(' ', '_').replace('.', '').lower()
            })

    # --- Holiday and Weekend Logic for Timelog Pages ---
    holiday = Holiday.query.filter_by(date=start).first() if start else None
    is_holiday = holiday is not None
    holiday_name = holiday.description if holiday else None
    is_weekend = False
    if start and end and start == end:
        dt = datetime.strptime(start, "%Y-%m-%d")
        is_weekend = dt.weekday() >= 5

    # If holiday or weekend, set expected to zero for all users
    if (is_holiday or is_weekend) and summary_data:
        for row in summary_data:
            row['expected'] = 0
        overall_total_expected = 0

    return render_template(
        "timelog.html",
        summary_data=summary_data,
        detailed_data=ordered_detailed_data,
        start=start,
        end=end,
        work_functions=work_functions,
        selected_function=selected_function,
        user_page=user_page,
        next_user_page=next_user_page,
        prev_user_page=prev_user_page,
        current_date=current_date,
        overall_total_logged=overall_total_logged,
        overall_total_expected=overall_total_expected,
        show_details=show_details,
        is_holiday=is_holiday,
        holiday_name=holiday_name,
        is_weekend=is_weekend
    )

@app.route('/timelog-today', methods=['GET', 'POST'])
@app.route('/timelog-today/<user_email>', methods=['GET'])
def timelog_today(user_email=None):
    # Only require login if the route is /timelog-today/<user_email> and user_email is missing or empty,
    # and only if the route was actually called with a user_email parameter (not just a query param)
    if request.url_rule and '<user_email>' in str(request.url_rule) and (not user_email):
        return redirect(url_for('login', next=request.url))
    users = User.query.all()
    work_functions = sorted(set([u.designation for u in users if u.designation]))
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    current_date = now.strftime('%Y-%m-%d')

    # Pagination params
    user_page = int(request.args.get('user_page', 1))
    users_per_page = 10
    filtered_users = users
    if user_email:
        filtered_users = [u for u in users if u.email == user_email and u.jira_account_id]
    else:
        selected_function = request.form.get('work_function') if request.method == 'POST' else request.args.get('work_function', 'All')
        if selected_function and selected_function != 'All':
            filtered_users = [u for u in users if u.jira_account_id and u.designation == selected_function]
        else:
            filtered_users = [u for u in users if u.jira_account_id]
    total_users = len(filtered_users)
    user_start = (user_page - 1) * users_per_page
    user_end = user_start + users_per_page
    paginated_users = filtered_users[user_start:user_end]
    next_user_page = user_page + 1 if user_end < total_users else None
    prev_user_page = user_page - 1 if user_page > 1 else None

    # Date for today
    date_str = request.args.get('date') or current_date
    start = end = date_str
    display_date_str = datetime.strptime(date_str, "%Y-%m-%d").strftime('%d %B %Y')
    # Previous/Next date logic for navigation
    current_dt = datetime.strptime(date_str, "%Y-%m-%d")
    previous_date = (current_dt - timedelta(days=1)).strftime('%Y-%m-%d')
    next_date = (current_dt + timedelta(days=1)).strftime('%Y-%m-%d') if current_dt.date() < date.today() else None

    # Caching and batch fetching (same as timelog)
    cache_params = {"start": start, "end": end, "user_ids": [u.jira_account_id for u in filtered_users]}
    cache_data = load_from_cache(cache_params)
    summary_data = []
    ordered_detailed_data = {}
    overall_total_logged = 0
    overall_total_expected = 0
    if not cache_data:
        since_epoch = get_epoch_ms(start)
        until_epoch = get_epoch_ms(end) + 24*3600*1000 - 1
        worklog_ids = fetch_worklog_ids_updated_since(JIRA_BASE_URL, headers, auth, since_epoch)
        all_worklogs = fetch_worklogs_by_ids(JIRA_BASE_URL, headers, auth, worklog_ids)
        user_map_all = {u.jira_account_id: u.name for u in filtered_users}
        detailed_data_all = defaultdict(list)
        expected_map = {}
        issue_ids = set()
        for wl in all_worklogs:
            author_id = wl.get('author', {}).get('accountId')
            started = wl.get('started', '')[:10]
            if author_id in user_map_all and start <= started <= end:
                issue_id = str(wl.get('issueId'))
                issue_ids.add(issue_id)
        issue_details = fetch_issue_details_bulk(JIRA_BASE_URL, headers, auth, issue_ids) if issue_ids else {}
        if not issue_details:
            from jira_worklog_batch import fetch_issue_details_individual
            issue_details = fetch_issue_details_individual(JIRA_BASE_URL, headers, auth, issue_ids)
        for wl in all_worklogs:
            author_id = wl.get('author', {}).get('accountId')
            started = wl.get('started', '')[:10]
            if author_id in user_map_all and start <= started <= end:
                user_name = user_map_all[author_id]
                hours = round(wl.get('timeSpentSeconds', 0) / 3600, 2)
                issue_id = str(wl.get('issueId'))
                issue_info = issue_details.get(issue_id, {})
                issue_key = issue_info.get('key', '')
                summary = issue_info.get('summary', '')
                parent_summary = issue_info.get('parent_summary', '')
                detailed_data_all[user_name].append({
                    "issue_key": issue_key,
                    "summary": summary,
                    "parent_summary": parent_summary,
                    "hours": hours,
                    "link": f"{JIRA_BASE_URL}/browse/{issue_key}" if issue_key else '',
                    "started": started
                })
        # Calculate expected for all users
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
        all_working_days = [d for d in (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)) if d.weekday() < 5]
        for user in filtered_users:
            leave_days = Leave.query.filter(
                Leave.user_id == user.id,
                Leave.start_date >= start_date.date(),
                Leave.start_date <= end_date.date()
            ).all()
            leave_map = {(leave.start_date, leave.leave_type) for leave in leave_days}
            leave_sum = sum([1 if l_type == 'FD' else 0.5 for (l_date, l_type) in leave_map if l_date in [d.date() for d in all_working_days]])
            available_days = max(0, len(all_working_days) - leave_sum)
            expected = available_days * 8
            total_hours = round(sum(item["hours"] for item in detailed_data_all.get(user.name, [])), 2)
            overall_total_logged += total_hours
            overall_total_expected += expected
            expected_map[user.name] = expected
        save_to_cache(cache_params, {
            "detailed_data_all": detailed_data_all,
            "overall_total_logged": overall_total_logged,
            "overall_total_expected": overall_total_expected,
            "expected_map": expected_map
        })
        cache_data = load_from_cache(cache_params)
    else:
        overall_total_logged = cache_data["overall_total_logged"]
        overall_total_expected = cache_data["overall_total_expected"]

    # Build summary and details for paginated users
    if cache_data:
        detailed_data_all = cache_data["detailed_data_all"]
        expected_map = cache_data["expected_map"]
        user_order = [u.name for u in paginated_users]
        ordered_detailed_data = {name: detailed_data_all.get(name, []) for name in user_order}
        for name in user_order:
            total_hours = round(sum(item["hours"] for item in ordered_detailed_data.get(name, [])), 2)
            expected = expected_map.get(name, 0)
            status = "good" if total_hours >= expected else "low"
            summary_data.append({
                "user": name,
                "total_hours": total_hours,
                "expected": expected,
                "status": status,
                "link": '',
                "anchor": name.replace(' ', '_').replace('.', '').lower()
            })

    # --- Holiday and Weekend Logic for Timelog Pages ---
    holiday = Holiday.query.filter_by(date=start).first() if start else None
    is_holiday = holiday is not None
    holiday_name = holiday.description if holiday else None
    is_weekend = False
    if start and end and start == end:
        dt = datetime.strptime(start, "%Y-%m-%d")
        is_weekend = dt.weekday() >= 5

    # If holiday or weekend, set expected to zero for all users
    if (is_holiday or is_weekend) and summary_data:
        for row in summary_data:
            row['expected'] = 0
        overall_total_expected = 0

    return render_template(
        "timelog_today.html",
        summary_data=summary_data,
        detailed_data=ordered_detailed_data,
        start=start,
        end=end,
        work_functions=work_functions,
        selected_function=request.args.get('work_function', 'All'),
        user_page=user_page,
        next_user_page=next_user_page,
        prev_user_page=prev_user_page,
        current_date=current_date,
        overall_total_logged=overall_total_logged,
        overall_total_expected=overall_total_expected,
        display_date_str=display_date_str,
        previous_date=previous_date,
        next_date=next_date,
        is_holiday=is_holiday,
        holiday_name=holiday_name,
        is_weekend=is_weekend
    )

@app.route('/user-timelog/<user_email>')
def user_timelog(user_email):
    user = User.query.filter_by(email=user_email).first()
    today = request.args.get('date')
    if today:
        date_obj = datetime.strptime(today, "%Y-%m-%d").date()
    else:
        date_obj = datetime.now().date()
    logs = []
    total_logged_hours = 0
    is_holiday = False
    holiday_name = None
    is_weekend = date_obj.weekday() >= 5
    is_on_leave = False
    if user:
        # Check leave (full day only)
        leave = Leave.query.filter_by(user_id=user.id, start_date=date_obj, leave_type='FD').first()
        is_on_leave = leave is not None
        # Holiday check
        holiday = Holiday.query.filter_by(date=date_obj).first()
        is_holiday = holiday is not None
        holiday_name = holiday.description if holiday else None
        # Timelog fetch logic for user (with parent summary)
        jql = f"worklogAuthor = '{user.jira_account_id}' AND worklogDate = '{date_obj.strftime('%Y-%m-%d')}'"
        url = f"{JIRA_BASE_URL}/rest/api/3/search"
        params = {"jql": jql, "fields": "worklog,summary,parent", "maxResults": 100}
        response = requests.get(url, headers=headers, params=params, auth=auth)
        if response.ok:
            data = response.json()
            for issue in data.get("issues", []):
                issue_key = issue.get("key", "")
                summary = issue.get("fields", {}).get("summary", "")
                parent_summary = issue.get("fields", {}).get("parent", {}).get("fields", {}).get("summary", "")
                for worklog in issue.get("fields", {}).get("worklog", {}).get("worklogs", []):
                    author_id = worklog.get("author", {}).get("accountId")
                    started = worklog.get("started", "")
                    if author_id == user.jira_account_id and started[:10] == date_obj.strftime('%Y-%m-%d'):
                        hours = round(worklog.get("timeSpentSeconds", 0) / 3600, 2)
                        total_logged_hours += hours
                        logs.append({
                            'issue_key': issue_key,
                            'summary': summary,
                            'parent_summary': parent_summary,
                            'hours': hours,
                            'started': started[:10]
                        })
    # Previous/Next date logic
    previous_date = (date_obj - timedelta(days=1)).strftime('%Y-%m-%d')
    next_date = (date_obj + timedelta(days=1)).strftime('%Y-%m-%d') if date_obj < datetime.now().date() else None
    display_date_str = date_obj.strftime('%d %B %Y')
    return render_template('user_timelog.html', user=user, logs=logs, is_holiday=is_holiday, holiday_name=holiday_name, is_weekend=is_weekend, is_on_leave=is_on_leave, date_obj=date_obj, total_logged_hours=total_logged_hours, previous_date=previous_date, next_date=next_date, display_date_str=display_date_str)

@app.route('/generate-testcases-auth', methods=['POST'])
def generate_testcases_auth():
    email = request.form.get('email', '').strip().lower()
    user = User.query.filter_by(email=email).first()
    if user:
        # Set a short-lived session key to allow access
        session['testcase_user'] = user.email
        return render_template('generate_testcases.html', user_exists=True)
    else:
        return render_template('generate_testcases.html', user_exists=False, email_checked=True)

@app.route('/generate-testcases', methods=['GET', 'POST'])
def generate_testcases():
    if session.get('logged_in') or session.get('testcase_user'):
        if request.method == 'POST':
            jira_id = request.form.get('jira_id', '').strip()
            story_text = request.form.get('story_text', '').strip()
            uploaded_file = request.files.get('story_doc')
            # Import the helper and fetch_jira_description from generate_testcases_route for DRY
            from generate_testcases_core import generate_testcases_core
            from generate_testcases_route import fetch_jira_description
            from app import client  # already initialized
            table_rows, error, extracted_text, jira_id_out = generate_testcases_core(
                jira_id, story_text, uploaded_file, fetch_jira_description, client
            )
            # Render result template
            return render_template(
                'testcases_result.html',
                content=table_rows,
                error=error,
                original_requirement=extracted_text,
                jira_id=jira_id_out,
                jira_base_url=os.getenv('JIRA_BASE_URL', '')
            )
        return render_template('generate_testcases.html', user_exists=True)
    else:
        return render_template('generate_testcases.html')

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

@app.route('/HelperQA-AI', methods=['GET', 'POST'])
def HelperQA_AI():
    global client
    feedback_html = None
    image_url = None
    page_url = None
    email_checked = False
    user_exists = False
    if request.method == 'GET' and not (session.get('logged_in') or session.get('ai_helper_email')):
        email = request.args.get('email')
        if email:
            user = User.query.filter_by(email=email).first()
            email_checked = True
            if user:
                session['ai_helper_email'] = email
                user_exists = True
            else:
                return render_template("HelperQA-AI.html", email_checked=email_checked, user_exists=user_exists)
    if request.method == 'POST':
        input_type = request.form.get('input_type')
        ai_mode = request.form.get('ai_mode', 'review')
        if not (session.get('logged_in') or session.get('ai_helper_email')):
            return redirect(url_for('HelperQA_AI'))
        if input_type == "testcase_story" and ai_mode == "testcases":
            jira_id = request.form.get('jira_id', '').strip()
            story_text = request.form.get('story_text', '').strip()
            uploaded_file = request.files.get('story_doc')
            testcases_rows, error, extracted_text, jira_id_out = ai_util.run(
                jira_id=jira_id,
                story_text=story_text,
                uploaded_file=uploaded_file
            )
            if error:
                return render_template("HelperQA-AI.html", feedback=error)
            return render_template("testcases_result.html",
                                   jira_id=jira_id_out,
                                   content=testcases_rows,
                                   original_requirement=extracted_text,
                                   jira_base_url=os.getenv("JIRA_BASE_URL"))
        # ... existing logic for upload/url/AI review ...
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


@app.route('/mytimelogs', methods=['GET'])
def mytimelogs():
    # Remove login requirement: allow access regardless of login state
    email = request.args.get('email')
    user = None
    email_checked = False
    if email:
        user = User.query.filter_by(email=email).first()
        email_checked = True
    total_hours_month = get_total_hours_for_user_month(email) if user else 0
    expected_hours_month = get_expected_hours_for_month() if user else 0
    return render_template('mytimelogs.html', user=user, email_checked=email_checked, total_hours_month=total_hours_month, expected_hours_month=expected_hours_month)

def get_total_hours_for_user_month(email):
    user = User.query.filter_by(email=email).first()
    if not user or not user.jira_account_id:
        return 0
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    start_date = now.replace(day=1)
    start = start_date.strftime('%Y-%m-%d')
    end = now.strftime('%Y-%m-%d')
    # Use worklog updated API
    from jira_worklog_batch import get_epoch_ms, fetch_worklog_ids_updated_since, fetch_worklogs_by_ids
    since_epoch = get_epoch_ms(start)
    worklog_ids = fetch_worklog_ids_updated_since(JIRA_BASE_URL, headers, auth, since_epoch)
    all_worklogs = fetch_worklogs_by_ids(JIRA_BASE_URL, headers, auth, worklog_ids)
    total_seconds = 0
    for wl in all_worklogs:
        author = wl.get('author', {}).get('accountId')
        if author == user.jira_account_id:
            # Only count logs in this month
            started = wl.get('started', '')
            if started and started[:7] == start[:7]:
                total_seconds += wl.get('timeSpentSeconds', 0)
    return round(total_seconds / 3600, 2)

def get_expected_hours_for_month():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    start_date = now.replace(day=1)
    end_date = now
    total_days = (end_date - start_date).days + 1
    # Count working days (Mon-Fri)
    working_days = sum(1 for i in range(total_days)
                       if (start_date + timedelta(days=i)).weekday() < 5)
    expected_hours = working_days * 8
    return expected_hours

@app.route('/api/issue_details', methods=['POST'])
def api_issue_details():
    data = request.get_json()
    issue_ids = data.get('issue_ids', [])
    from jira_worklog_batch import fetch_issue_details_individual
    # Use persistent cache-backed fetch
    issue_details = fetch_issue_details_individual(JIRA_BASE_URL, headers, auth, issue_ids)
    return jsonify(issue_details)

@app.route('/get-jira-description')
def get_jira_description():
    jira_id = request.args.get('jira_id', '').strip()
    if not jira_id:
        return jsonify({'description': 'No Jira ID provided.'})
    desc, err = ai_util.fetch_jira_description(jira_id)
    if err:
        return jsonify({'description': f'Error: {err}'})
    return jsonify({'description': desc})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
