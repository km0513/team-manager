# --- Performance and Cleanliness Optimizations ---
# 1. Use joinedload for relationships in queries to avoid N+1
from sqlalchemy.orm import joinedload

# 2. Add type hints and docstrings to major functions and classes
# 3. Move repeated cache and query logic to helper functions (see timelog_cache.py and generate_testcases_core.py)
# 4. Add error handling and logging for slow queries and API failures
import logging
logging.basicConfig(level=logging.INFO)

# 5. Paginate large user lists
USERS_PER_PAGE = 20

# 6. Use granular cache keys and longer cache for static data
# 7. Blueprint registration and config separation (future-proofing)

import os
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.utils import secure_filename

from markdown import markdown as md_convert  # only one import for markdown is needed
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# JIRA credentials
JIRA_USERNAME = os.environ.get('JIRA_EMAIL')  # Using JIRA_EMAIL from .env
JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN')
JIRA_BASE_URL = os.environ.get('JIRA_BASE_URL', 'https://upgrad-jira.atlassian.net')

import pandas as pd
import matplotlib
matplotlib.use('Agg')  # use non-interactive backend for server environments
import matplotlib.pyplot as plt

import re
import json
import base64
from datetime import datetime, timedelta, date
import calendar
from datetime import date
import pytz

import requests
from requests.auth import HTTPBasicAuth
from collections import defaultdict

# Import webpage spellcheck utilities
from webpage_spellcheck_utils import extract_text_and_screenshot, spellcheck_text

from jira_worklog_batch import get_epoch_ms, fetch_worklog_ids_updated_since, fetch_worklogs_by_ids, fetch_issue_details_bulk

from generate_testcases_core import generate_testcases_core
from generate_testcases_route import fetch_jira_description, testcase_bp
from ai_utils import AIUtility

# Initialize Flask app
app = Flask(__name__)
app.config['SERVER_NAME'] = 'teammanagerqai.herokuapp.com'
# Load environment variables from .env file
load_dotenv()  # This loads the .env file

@app.route('/jira-export-analysis', methods=['GET', 'POST'])
def jira_export_analysis():
    """Page for analyzing Jira export CSV files or JQL queries"""
    if request.method == 'POST':
        # Debug: Print form data
        print("Form data:", request.form)
        print("Files:", request.files)
        
        # Get the form type
        form_type = request.form.get('form_type', '')
        print(f"Form type: {form_type}")
        # Define status categories
        qa_ownership_statuses = [
            "Ready for QA", "QA-Ready", "QA Progress - Blocked",
            "Resolved", "QA In Progress", "QA Inprogress"
        ]
        
        dev_ownership_statuses = [
            "OPEN", "Reopen", "ToDo", "To Do", "Reopened", "Dev Inprogress", "Dev - Building",
            "Build Broken", "Ready for Development", "Dev - Frontend - InProgress",
            "Dev - Backend - InProgress", "Dev - Backend - Todo", "Dev - Frontend - Todo",
            "Dev- UI - InProgress", "Dev- UI - Todo", "Backlog Item", "Open (migrated)", "Open",
            "QA - Building", "QA Progress - Blocked", "Groomed"
        ]
        
        # Check if JQL query was submitted
        jql = request.form.get('jql', '').strip()
        print(f"JQL query: {jql}")
        if form_type == 'jql_query' and jql:
            try:
                # Use the Jira API to execute the JQL query
                import pandas as pd
                import json
                
                # Get Jira credentials from environment variables
                JIRA_BASE_URL = os.environ.get('JIRA_BASE_URL')
                JIRA_EMAIL = os.environ.get('JIRA_EMAIL')
                JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN')
                
                if not (JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN):
                    return render_template('jira_export_analysis.html', 
                                          error="Jira API credentials not configured. Please check environment variables.")
                
                # Set up authentication
                auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
                headers = {"Accept": "application/json"}
                
                # Call Jira API with the JQL query
                url = f"{JIRA_BASE_URL}/rest/api/3/search"
                params = {
                    "jql": jql,
                    "maxResults": 1000,  # Adjust as needed
                    "fields": "parent,status,summary,customfield_10074,updated,created,statuscategorychangedate"  # Include time in status field
                }
                
                print(f"Calling Jira API with URL: {url}")
                print(f"JQL params: {params}")
                
                try:
                    response = requests.get(url, auth=auth, headers=headers, params=params)
                    print(f"API response status: {response.status_code}")
                except Exception as e:
                    print(f"API call exception: {str(e)}")
                    return render_template('jira_export_analysis.html', error=f"Error calling Jira API: {str(e)}")
                
                if response.status_code != 200:
                    return render_template('jira_export_analysis.html', 
                                          error=f"Jira API error: {response.status_code} - {response.text}")
                
                # Process the API response
                data = response.json()
                issues = data.get('issues', [])
                
                # Extract Jira base URL from the environment variable
                jira_base_url = JIRA_BASE_URL.split('/rest/api')[0] if '/rest/api' in JIRA_BASE_URL else JIRA_BASE_URL
                
                # Print debug information about the first issue
                if issues and len(issues) > 0:
                    print("First issue fields:", list(issues[0].get('fields', {}).keys()))
                    
                    # Debug time tracking fields
                    if 'timetracking' in issues[0].get('fields', {}):
                        print("Time tracking data:", issues[0].get('fields', {}).get('timetracking'))
                    if 'timespent' in issues[0].get('fields', {}):
                        print("Time spent:", issues[0].get('fields', {}).get('timespent'))
                    if 'aggregatetimespent' in issues[0].get('fields', {}):
                        print("Aggregate time spent:", issues[0].get('fields', {}).get('aggregatetimespent'))
                    if 'worklog' in issues[0].get('fields', {}):
                        print("Worklog exists:", bool(issues[0].get('fields', {}).get('worklog')))
                
                if not issues:
                    return render_template('jira_export_analysis.html', 
                                          error="No issues found for the given JQL query")
                
                # Convert to DataFrame
                rows = []
                for issue in issues:
                    parent_data = issue.get('fields', {}).get('parent', {})
                    parent_summary = parent_data.get('fields', {}).get('summary', 'No Parent') if parent_data else 'No Parent'
                    status = issue.get('fields', {}).get('status', {}).get('name', 'Unknown')
                    issue_key = issue.get('key', '')
                    issue_summary = issue.get('fields', {}).get('summary', '')
                    
                    rows.append({
                        'Parent summary': parent_summary,
                        'Status': status,
                        'Issue Key': issue_key,
                        'Issue Summary': issue_summary
                    })
                
                df = pd.DataFrame(rows)
                
                # Basic file info
                file_info = {
                    'source': 'JQL Query',
                    'query': jql,
                    'total_rows': len(df),
                    'columns': len(df.columns)
                }
                
                # Continue with analysis as with CSV
                parent_summary_status = df[['Parent summary', 'Status']].copy()
                
                # Categorize statuses
                def categorize_status(status):
                    if status in dev_ownership_statuses:
                        return "Dev Ownership"
                    elif status in qa_ownership_statuses:
                        return "QA Ownership"
                    else:
                        return "Closed"
                
                parent_summary_status['Ownership'] = parent_summary_status['Status'].apply(categorize_status)
                
                # Group and count by Parent summary and Ownership
                ownership_counts = parent_summary_status.groupby(['Parent summary', 'Ownership']).size().unstack(fill_value=0).reset_index()
                
                # Calculate total per parent
                ownership_counts['Total'] = ownership_counts.sum(axis=1, numeric_only=True)
                
                # Ensure all columns exist
                for col in ['Dev Ownership', 'QA Ownership', 'Closed']:
                    if col not in ownership_counts.columns:
                        ownership_counts[col] = 0
                
                # Reorder columns
                ownership_counts = ownership_counts[['Parent summary', 'Total', 'Dev Ownership', 'QA Ownership', 'Closed']]
                
                # Add completion percentage
                ownership_counts['Completion %'] = (ownership_counts['Closed'] / ownership_counts['Total'] * 100).round(0).astype(int)
                
                # Calculate overall totals
                overall_totals = {
                    'Parent summary': 'OVERALL',
                    'Total': int(ownership_counts['Total'].sum()),
                    'Dev Ownership': int(ownership_counts['Dev Ownership'].sum()),
                    'QA Ownership': int(ownership_counts['QA Ownership'].sum()),
                    'Closed': int(ownership_counts['Closed'].sum()),
                    'Completion %': int((ownership_counts['Closed'].sum() / ownership_counts['Total'].sum() * 100).round(0))
                }
                
                # Convert to records for template rendering
                results = ownership_counts.to_dict('records')
                
                # Get issue details for each parent summary
                issue_details = {}
                
                for issue in issues:
                    parent_data = issue.get('fields', {}).get('parent', {})
                    parent_summary = parent_data.get('fields', {}).get('summary', 'No Parent') if parent_data else 'No Parent'
                    
                    if parent_summary not in issue_details:
                        issue_details[parent_summary] = []
                    
                    issue_details[parent_summary].append({
                        'key': issue.get('key', ''),
                        'summary': issue.get('fields', {}).get('summary', ''),
                        'status': issue.get('fields', {}).get('status', {}).get('name', 'Unknown')
                    })
                
                # Blocker processing has been moved to a dedicated API endpoint
                # The Release Blocker Analysis is now handled through the modal
                
                return render_template('jira_export_analysis.html', 
                                       file_info=file_info, 
                                       results=results,
                                       overall=overall_totals,
                                       issue_details=issue_details,
                                       jira_base_url=jira_base_url,
                                       os=os)
                
            except Exception as e:
                app.logger.error(f"Error processing JQL query: {str(e)}")
                return render_template('jira_export_analysis.html', error=f"Error processing JQL query: {str(e)}")
        
        # Check if a CSV file was uploaded
        elif form_type == 'csv_upload' and 'file' in request.files:
            file = request.files['file']
            if file.filename == '':
                return render_template('jira_export_analysis.html', error='No file selected')
                
            if file and file.filename.endswith('.csv'):
                try:
                    # Read the CSV file
                    import pandas as pd
                    import io
                    import json
                
                    # Define status categories
                    qa_ownership_statuses = [
                        "Ready for QA", "QA-Ready", "QA Progress - Blocked",
                        "Resolved", "QA In Progress", "QA Inprogress"
                    ]
                    
                    dev_ownership_statuses = [
                        "OPEN", "Reopen", "ToDo", "To Do", "Reopened", "Dev Inprogress", "Dev - Building",
                        "Build Broken", "Ready for Development", "Dev - Frontend - InProgress",
                        "Dev - Backend - InProgress", "Dev - Backend - Todo", "Dev - Frontend - Todo",
                        "Dev- UI - InProgress", "Dev- UI - Todo", "Backlog Item", "Open (migrated)", "Open",
                        "QA - Building", "QA Progress - Blocked", "Groomed"
                    ]
                
                    # Read the CSV file
                    df = pd.read_csv(file, encoding='utf-8')
                    
                    # Basic file info
                    file_info = {
                        'filename': file.filename,
                        'total_rows': len(df),
                        'columns': len(df.columns)
                    }
                    
                    # Extract parent summary and status
                    parent_summary_status = df[['Parent summary', 'Status']].copy()
                    
                    # Categorize statuses
                    def categorize_status(status):
                        if status in dev_ownership_statuses:
                            return "Dev Ownership"
                        elif status in qa_ownership_statuses:
                            return "QA Ownership"
                        else:
                            return "Closed"
                    
                    parent_summary_status['Ownership'] = parent_summary_status['Status'].apply(categorize_status)
                    
                    # Group and count by Parent summary and Ownership
                    ownership_counts = parent_summary_status.groupby(['Parent summary', 'Ownership']).size().unstack(fill_value=0).reset_index()
                    
                    # Calculate total per parent
                    ownership_counts['Total'] = ownership_counts.sum(axis=1, numeric_only=True)
                    
                    # Ensure all columns exist
                    for col in ['Dev Ownership', 'QA Ownership', 'Closed']:
                        if col not in ownership_counts.columns:
                            ownership_counts[col] = 0
                    
                    # Reorder columns
                    ownership_counts = ownership_counts[['Parent summary', 'Total', 'Dev Ownership', 'QA Ownership', 'Closed']]
                    
                    # Add completion percentage
                    ownership_counts['Completion %'] = (ownership_counts['Closed'] / ownership_counts['Total'] * 100).round(0).astype(int)
                    
                    # Calculate overall totals
                    overall_totals = {
                        'Parent summary': 'OVERALL',
                        'Total': int(ownership_counts['Total'].sum()),
                        'Dev Ownership': int(ownership_counts['Dev Ownership'].sum()),
                        'QA Ownership': int(ownership_counts['QA Ownership'].sum()),
                        'Closed': int(ownership_counts['Closed'].sum()),
                        'Completion %': int((ownership_counts['Closed'].sum() / ownership_counts['Total'].sum() * 100).round(0))
                    }
                    
                    # Convert to records for template rendering
                    results = ownership_counts.to_dict('records')
                    
                    return render_template('jira_export_analysis.html', 
                                           file_info=file_info, 
                                           results=results,
                                           overall=overall_totals)
                
                except Exception as e:
                    app.logger.error(f"Error processing CSV: {str(e)}")
                    return render_template('jira_export_analysis.html', error=f"Error processing file: {str(e)}")
            else:
                return render_template('jira_export_analysis.html', error='Only CSV files are supported')
    
    return render_template('jira_export_analysis.html')

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

from flask import jsonify

@app.route('/timelog_async', methods=['POST'])
def timelog_async():
    """
    Enqueue a background job to process timelog data. Expects form data with 'start', 'end', and 'work_function'.
    Returns a job ID for polling.
    """
    form = request.form.to_dict()
    job = timelog_queue.enqueue(process_timelog_report, form)
    return jsonify({'job_id': job.get_id()}), 202

@app.route('/timelog_status/<job_id>', methods=['GET'])
def timelog_status(job_id):
    """
    Check the status of a background timelog job. Returns status and result if ready.
    """
    try:
        import os
        redis_conn = Redis(
            host=os.getenv('REDIS_HOST'),
            port=int(os.getenv('REDIS_PORT')),
            decode_responses=True,
            username=os.getenv('REDIS_USERNAME'),
            password=os.getenv('REDIS_PASSWORD'),
            ssl=True
        )
        job = Job.fetch(job_id, connection=redis_conn)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 404
    if job.is_finished:
        return jsonify({'status': 'finished', 'result': job.result})
    elif job.is_failed:
        return jsonify({'status': 'failed', 'message': str(job.exc_info)})
    else:
        return jsonify({'status': 'in_progress'})

@app.template_filter('round_half')
def round_half(value):
    return round(float(value) * 2) / 2

@app.before_request
def require_login():
    # Add 'underlogged_days' to the allowlist so it does NOT require login
    if 'logged_in' not in session and request.endpoint not in [
        'login', 'static', 'HelperQA_AI', 'generate_testcases', 'generate_testcases_auth',
        'timelog_today', 'users', 'export_users', 'export_timelog_links', 'mytimelogs',
        'user_timelog', 'HelperQA_AI', 'generate_testcases', 'get_jira_description',
        'analyseui', 'testcases_result', 'generate_testcases', 'generate_testcases_auth',
        'underlogged_days', 'jql_wip'  # <-- allow jql_wip without login
    ]:
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
@app.route('/leave-calendar', methods=['GET', 'POST'])
def leave_calendar():
    from flask import render_template, request
    user_id = request.args.get('user_id')
    modal = request.args.get('modal') == '1'
    # ... existing logic to get users, leaves, etc. ...
    if user_id:
        selected_user = User.query.filter_by(id=user_id).first()
        users = [selected_user] if selected_user else []
    else:
        users = User.query.all()
    # Calculate year and month
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
                    existing_leave = Leave.query.filter_by(user_id=user.id, start_date=day).first()
                    if not existing_leave:
                        db.session.add(Leave(user_id=user.id, start_date=day, leave_type=leave_type))
                    else:
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

    # Provide a dictionary of date: description for holidays
    holiday_dict = {h.date: h.description for h in Holiday.query.filter(
        Holiday.date >= datetime(year, month, 1).date(),
        Holiday.date <= datetime(year, month, month_days).date()
    ).all()}

    context = dict(
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
        holidays=holiday_dict,
        selected_user_id=user_id
    )
    if modal:
        context['user'] = users[0] if users else None
        context['modal'] = True
        return render_template('leave_calendar_modal.html', **context)
    else:
        return render_template('leave_calendar.html', **context)

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
    """
    Timelog summary and details for all users within a date range.
    Optimized for performance: uses eager loading, caching, and pagination.
    """
    # Eager load user relationships for efficiency
    users = User.query.options(joinedload(User.leaves)).all()
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
    filtered_users = users
    if selected_function and selected_function != 'All':
        filtered_users = [u for u in users if u.jira_account_id and u.designation == selected_function]
    else:
        filtered_users = [u for u in users if u.jira_account_id]
    # Remove pagination to show all users
    paginated_users = filtered_users
    next_user_page = None
    prev_user_page = None

    overall_total_logged = 0
    overall_total_expected = 0
    cache_params = {"start": start, "end": end, "user_ids": [u.jira_account_id for u in paginated_users]}
    cache_data = load_from_cache(cache_params)
    if not cache_data:
        # Defensive: Ensure start and end are always valid strings
        if not start:
            ist = pytz.timezone('Asia/Kolkata')
            now = datetime.now(ist)
            start = now.strftime('%Y-%m-%d')
        if not end:
            ist = pytz.timezone('Asia/Kolkata')
            now = datetime.now(ist)
            end = now.strftime('%Y-%m-%d')
        # Fetch from Jira and cache using /worklog/updated for efficiency
        since_epoch = get_epoch_ms(start)
        until_epoch = get_epoch_ms(end) + 24*3600*1000 - 1
        worklog_ids = fetch_worklog_ids_updated_since(JIRA_BASE_URL, headers, auth, since_epoch)
        all_worklogs = fetch_worklogs_by_ids(JIRA_BASE_URL, headers, auth, worklog_ids)
        user_map_all = {u.jira_account_id: u.name for u in paginated_users}
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
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
        all_working_days = [d for d in (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)) if d.weekday() < 5]
        for user in paginated_users:
            leave_days = Leave.query.options(joinedload(Leave.user)).filter(
                Leave.user_id == user.id,
                Leave.start_date >= start_date.date(),
                Leave.start_date <= end_date.date()
            ).all()
            expected_map[user.name] = len(all_working_days) * 8 - len(leave_days) * 8
        for user in paginated_users:
            logs = detailed_data_all[user.name]
            total_logged = sum(l['hours'] for l in logs)
            summary_data.append({
                "user": user.name,
                "total_hours": total_logged,
                "expected": expected_map.get(user.name, 0)
            })
            ordered_detailed_data[user.name] = logs
            overall_total_logged += total_logged
            overall_total_expected += expected_map.get(user.name, 0)
        cache_data = {"summary_data": summary_data, "detailed_data": ordered_detailed_data}
        save_to_cache(cache_params, cache_data)
    else:
        summary_data = cache_data["summary_data"]
        ordered_detailed_data = cache_data["detailed_data"]
        # Calculate overall totals from cached summary_data
        overall_total_logged = sum(item["total_hours"] for item in summary_data)
        overall_total_expected = sum(item["expected"] for item in summary_data)

    return render_template("timelog.html", summary_data=summary_data, detailed_data=ordered_detailed_data, start=start, end=end, work_functions=work_functions, selected_function=selected_function, show_details=show_details, next_user_page=next_user_page, prev_user_page=prev_user_page, overall_total_logged=overall_total_logged, overall_total_expected=overall_total_expected)

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
    filtered_users = users
    if user_email:
        filtered_users = [u for u in users if u.email == user_email and u.jira_account_id]
    else:
        if selected_function and selected_function != 'All':
            filtered_users = [u for u in users if u.jira_account_id and u.designation == selected_function]
        else:
            filtered_users = [u for u in users if u.jira_account_id]
    # Show all users (no pagination)
    paginated_users = filtered_users
    next_user_page = None
    prev_user_page = None

    # Date for today
    date_str = request.args.get('date') or current_date
    start = end = date_str
    display_date_str = datetime.strptime(date_str, "%Y-%m-%d").strftime('%d %B %Y')
    # Previous/Next date logic for navigation
    current_dt = datetime.strptime(date_str, "%Y-%m-%d")
    previous_date = (current_dt - timedelta(days=1)).strftime('%Y-%m-%d')
    next_date = (current_dt + timedelta(days=1)).strftime('%Y-%m-%d') if current_dt.date() < date.today() else None

    # Caching and batch fetching (same as timelog)
    cache_params = {"start": start, "end": end, "user_ids": [u.jira_account_id for u in paginated_users]}
    cache_data = load_from_cache(cache_params)
    summary_data = []
    ordered_detailed_data = {}
    overall_total_logged = 0
    overall_total_expected = 0
    if not cache_data:
        # Fetch from Jira and cache using /worklog/updated for efficiency
        since_epoch = get_epoch_ms(start)
        until_epoch = get_epoch_ms(end) + 24*3600*1000 - 1
        worklog_ids = fetch_worklog_ids_updated_since(JIRA_BASE_URL, headers, auth, since_epoch)
        all_worklogs = fetch_worklogs_by_ids(JIRA_BASE_URL, headers, auth, worklog_ids)
        user_map_all = {u.jira_account_id: u.name for u in paginated_users}
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
        start_date = datetime.strptime(start, "%Y-%m-%d")
        end_date = datetime.strptime(end, "%Y-%m-%d")
        all_working_days = [d for d in (start_date + timedelta(days=i) for i in range((end_date - start_date).days + 1)) if d.weekday() < 5]
        for user in paginated_users:
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
        user_page=None,
        next_user_page=None,
        prev_user_page=None,
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
    # Round total_logged_hours to the nearest 0.5 for display
    total_logged_hours_rounded = round(float(total_logged_hours) * 2) / 2
    return render_template('user_timelog.html', user=user, logs=logs, is_holiday=is_holiday, holiday_name=holiday_name, is_weekend=is_weekend, is_on_leave=is_on_leave, date_obj=date_obj, total_logged_hours=total_logged_hours_rounded, previous_date=previous_date, next_date=next_date, display_date_str=display_date_str)

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
    print("DEBUG: /generate-testcases route was hit")
    print("DEBUG: session contents at /generate-testcases:", dict(session))
    jira_error = None
    if request.method == 'POST':
        jira_id = request.form.get('jira_id', '').strip()
        story_text = request.form.get('story_text', '').strip()
        uploaded_file = request.files.get('story_doc')
        print("DEBUG: /generate-testcases POST called")
        print("DEBUG: Jira ID received:", jira_id)
        print("DEBUG: Story text received:", story_text)
        # Validate Jira ID before generating test cases
        from generate_testcases_route import fetch_jira_description
        desc, err = fetch_jira_description(jira_id)
        print("DEBUG: Jira validation result:", desc, err)
        if err or not desc:
            jira_error = f"Invalid or inaccessible Jira ID: {jira_id}. Please check and try again."
            return render_template('generate_testcases.html', jira_error=jira_error)
        # If valid, proceed to generate test cases
        from generate_testcases_core import generate_testcases_core
        client = None
        table_rows, error, extracted_text, jira_id_out = generate_testcases_core(
            jira_id, story_text, uploaded_file, fetch_jira_description, client
        )
        print("DEBUG: generate_testcases_core returned error:", error)
        return render_template(
            'testcases_result.html',
            content=table_rows,
            error=error,
            original_requirement=extracted_text,
            jira_id=jira_id_out,
            jira_base_url=os.getenv('JIRA_BASE_URL', '')
        )
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
    if request.method == 'POST':
        input_type = request.form.get('input_type')
        ai_mode = request.form.get('ai_mode', 'review')
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
                # New logic: Use Selenium + BeautifulSoup to extract text and take screenshot
                screenshot_path, extracted_text = extract_text_and_screenshot(page_url)
                if screenshot_path and os.path.exists(screenshot_path):
                    image_url = url_for('static', filename=f"uploads/{os.path.basename(screenshot_path)}")
                    with open(screenshot_path, "rb") as f:
                        image_b64 = base64.b64encode(f.read()).decode()
                else:
                    feedback_html = f"Failed to capture screenshot or extract text. {extracted_text}"
                    return render_template("HelperQA-AI.html", feedback=feedback_html)
                # Spell check the extracted text
                spelling_errors = spellcheck_text(extracted_text)
                # Generate a report (HTML block)
                report_html = f"""
                    <h3>Webpage Screenshot</h3>
                    <img src='{image_url}' style='max-width: 100%; border:1px solid #ccc;'/>
                    <h3>Spelling Errors</h3>
                    <ul>
                """
                if spelling_errors:
                    for err in spelling_errors:
                        report_html += f"<li><b>{err['word']}</b> (suggestions: {', '.join(err['suggestion'])})<br><small>Context: ...{err['context']}...</small></li>"
                else:
                    report_html += "<li>No spelling errors detected.</li>"
                report_html += "</ul>"
                feedback_html = report_html

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
                    "Please review this UI screenshot and check for any **spelling or grammatical mistakes** only.\n\n"
                    "Format the response using markdown like:\n"
                    "### Spelling and Grammar Issues"
                )
                system_message = "You are a helpful proofreader analyzing screenshots for spelling and grammar issues only. Use markdown formatting."
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
    expected_hours_month = get_expected_hours_for_user_month(email) if user else 0
    return render_template('mytimelogs.html', user=user, email_checked=email_checked, total_hours_month=total_hours_month, expected_hours_month=expected_hours_month)

def get_total_hours_for_user_month(email):
    user = User.query.filter_by(email=email).first()
    if not user or not user.jira_account_id:
        return 0
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    start_date = now.replace(day=1).date()
    end_date = now.date()
    from_date_str = start_date.strftime('%Y-%m-%d')
    to_date_str = end_date.strftime('%Y-%m-%d')
    jql = f"worklogAuthor = '{user.jira_account_id}' AND worklogDate >= '{from_date_str}' AND worklogDate <= '{to_date_str}'"
    url = f"{JIRA_BASE_URL}/rest/api/3/search"
    params = {"jql": jql, "fields": "worklog", "maxResults": 1000}
    response = requests.get(url, headers=headers, params=params, auth=auth)
    total_seconds = 0
    if response.ok:
        data = response.json()
        for issue in data.get("issues", []):
            for worklog in issue.get("fields", {}).get("worklog", {}).get("worklogs", []):
                author_id = worklog.get("author", {}).get("accountId")
                started = worklog.get("started", "")
                if author_id == user.jira_account_id and started:
                    dt = datetime.strptime(started[:10], '%Y-%m-%d').date()
                    if start_date <= dt <= end_date:
                        total_seconds += worklog.get('timeSpentSeconds', 0)
    return round(total_seconds / 3600, 2)

def get_expected_hours_for_user_month(email):
    user = User.query.filter_by(email=email).first()
    if not user:
        return 0
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    start_date = now.replace(day=1).date()
    end_date = now.date()
    # Get holidays this month
    holidays = set(h.date for h in Holiday.query.filter(Holiday.date >= start_date, Holiday.date <= end_date).all())
    # Get full-day leaves for user this month
    leaves = set(l.start_date for l in Leave.query.filter(Leave.user_id == user.id, Leave.start_date >= start_date, Leave.start_date <= end_date, Leave.leave_type == 'FD').all())
    total_days = (end_date - start_date).days + 1
    expected_days = 0
    for i in range(total_days):
        day = start_date + timedelta(days=i)
        if day.weekday() >= 5 or day in holidays or day in leaves:
            continue
        expected_days += 1
    return expected_days * 8

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

@app.route('/underlogged-days')
def underlogged_days():
    email = request.args.get('user_email')
    if not email:
        return jsonify([])
    underlogged = get_underlogged_days_for_user(email)
    # Format for frontend: date (YYYY-MM-DD), date_display (e.g. 20 Apr 2025), hours
    formatted = [{
        'date': d['date'].strftime('%Y-%m-%d'),
        'date_display': d['date'].strftime('%d %b %Y'),
        'hours': d['hours']
    } for d in underlogged]
    return jsonify(formatted)

def get_underlogged_days_for_user(email):
    """
    Returns a list of dictionaries for each working day this month where the user logged less than 8 hours.
    Skips weekends, holidays, and full-day leaves.
    Each dict: {'date': date_obj, 'hours': hours_logged}
    """
    user = User.query.filter_by(email=email).first()
    if not user or not user.jira_account_id:
        return []
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist)
    start_date = now.replace(day=1).date()
    end_date = now.date()
    # Get all holidays this month
    holidays = set(h.date for h in Holiday.query.filter(Holiday.date >= start_date, Holiday.date <= end_date).all())
    # Get all full-day leaves for user this month
    leaves = set(l.start_date for l in Leave.query.filter(Leave.user_id == user.id, Leave.start_date >= start_date, Leave.start_date <= end_date, Leave.leave_type == 'FD').all())
    # Fetch all issues where user logged work this month
    from_date_str = start_date.strftime('%Y-%m-%d')
    to_date_str = end_date.strftime('%Y-%m-%d')
    jql = f"worklogAuthor = '{user.jira_account_id}' AND worklogDate >= '{from_date_str}' AND worklogDate <= '{to_date_str}'"
    url = f"{JIRA_BASE_URL}/rest/api/3/search"
    params = {"jql": jql, "fields": "worklog", "maxResults": 1000}
    response = requests.get(url, headers=headers, params=params, auth=auth)
    hours_per_day = {}
    if response.ok:
        data = response.json()
        for issue in data.get("issues", []):
            for worklog in issue.get("fields", {}).get("worklog", {}).get("worklogs", []):
                author_id = worklog.get("author", {}).get("accountId")
                started = worklog.get("started", "")
                if author_id == user.jira_account_id and started:
                    dt = datetime.strptime(started[:10], '%Y-%m-%d').date()
                    if start_date <= dt <= end_date:
                        hours_per_day[dt] = hours_per_day.get(dt, 0) + worklog.get('timeSpentSeconds', 0) / 3600
    # Now check each working day
    missed = []
    for i in range((end_date - start_date).days + 1):
        day = start_date + timedelta(days=i)
        if day.weekday() >= 5 or day in holidays or day in leaves:
            continue
        hours = round(hours_per_day.get(day, 0), 2)
        if hours < 8:
            missed.append({'date': day, 'hours': hours})
    return missed

app.register_blueprint(testcase_bp)

@app.route('/jql-wip', methods=['GET', 'POST'])
def jql_wip():
    import os
    import requests
    from flask import current_app
    from collections import defaultdict

    # Get parameters from either POST form or GET query parameters
    shared_card = None
    if request.method == 'POST':
        jql = request.form.get('jql', '')
        group_by = request.form.get('group_by', 'assignee')
        shared_card = request.form.get('shared_card')
    else:  # GET method
        jql = request.args.get('jql', '')
        group_by = request.args.get('group_by', 'assignee')
        shared_card = request.args.get('shared_card')
    
    # If we have a shared card, extract the field and value
    shared_card_field = None
    shared_card_value = None
    if shared_card:
        try:
            shared_card_field, shared_card_value = shared_card.split(':', 1)
            shared_card_value = shared_card_value.replace('"', '').replace("'", "").strip()
        except (ValueError, AttributeError):
            shared_card = None
    
    grouped_issues = {}
    error = None

    # Jira config from environment or config
    JIRA_BASE_URL = os.environ.get('JIRA_BASE_URL')
    JIRA_EMAIL = os.environ.get('JIRA_EMAIL')
    JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN')
    if not (JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN):
        error = 'Jira credentials are not set in environment.'
        return render_template('jql_wip.html', jql=jql, grouped_issues={}, group_by=group_by, error=error, jira_base_url=JIRA_BASE_URL)

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)

    filterable_fields = ["assignee", "creator", "status", "priority"]
    unique_values = {field: [] for field in filterable_fields}
    
    if jql.strip():
        fields = ["summary", "creator", "assignee", "status", "priority"]
        if group_by not in fields:
            fields.append(group_by)
        fields_param = ','.join(fields)
        url = f"{JIRA_BASE_URL}/rest/api/3/search"
        params = {
            "jql": jql,
            "fields": fields_param,
            "maxResults": 100
        }
        grouped_issues = {}
        try:
            # Debug log the JQL query
            print(f"\n--- JQL Query ---\n{params['jql']}\n---------------\n")
            
            # Make the API request
            resp = requests.get(url, headers=headers, params=params, auth=auth)
            print(f"\n--- API Response Status ---\n{resp.status_code}\n---------------\n")
            
            if resp.ok:
                # Debug log the response keys
                data = resp.json()
                print(f"\n--- API Response Data ---")
                print(f"Total issues: {data.get('total')}")
                print(f"Issues in response: {len(data.get('issues', []))}")
                if data.get('issues'):
                    print(f"First issue key: {data['issues'][0].get('key')}")
                print("---------------\n")
                data = resp.json()
                issues = data.get('issues', [])
                
                if not issues:
                    # No issues found but request was successful
                    error = "No issues found matching the JQL query."
                else:
                    # Process the issues
                    grouped = defaultdict(list)
                    for issue in issues:
                        key = issue.get('key', 'Unknown')
                        f = issue.get('fields', {})
                        
                        # Use safe getters with default values
                        summary = f.get('summary', '')
                        
                        # Handle potentially missing nested objects
                        creator_obj = f.get('creator') or {}
                        creator = creator_obj.get('displayName', 'Unassigned')
                        
                        assignee_obj = f.get('assignee') or {}
                        assignee = assignee_obj.get('displayName', 'Unassigned')
                        
                        status_obj = f.get('status') or {}
                        status = status_obj.get('name', 'Unknown')
                        
                        priority_obj = f.get('priority') or {}
                        priority = priority_obj.get('name', 'None')
                        
                        issue_data = {
                            'key': key,
                            'summary': summary,
                            'creator': creator,
                            'assignee': assignee,
                            'status': status,
                            'priority': priority
                        }
                        
                        # Group by selected field with safe fallback
                        group_val = issue_data.get(group_by) or 'Unassigned'
                        grouped[group_val].append(issue_data)
                        print(f"Adding to group '{group_val}': {issue_data['key']}")  # Debug log
                    
                    grouped_issues = dict(grouped)
            else:
                # Handle API error response
                try:
                    error_json = resp.json()
                    error_message = error_json.get('errorMessages', [])
                    if error_message:
                        error = f"Jira API error: {error_message[0]}"
                    else:
                        error = f"Jira API error: {resp.status_code} - {resp.text}"
                except:
                    error = f"Jira API error: {resp.status_code} - {resp.text}"
        except Exception as e:
            error = f"Jira API exception: {str(e)}"
            print(f"Exception in JQL WIP: {str(e)}")
            import traceback
            traceback.print_exc()
        
        # Flatten issues for filter value extraction (outside try block)
        all_issues = []
        if grouped_issues:
            all_issues = [issue for group in grouped_issues.values() for issue in group]
            
        # Debug log the structure of grouped_issues
        if grouped_issues:
            app.logger.debug(f"Grouped issues keys: {list(grouped_issues.keys())}")
            first_key = next(iter(grouped_issues))
            app.logger.debug(f"First group key: {first_key}")
            if grouped_issues[first_key]:
                app.logger.debug(f"First issue in first group: {grouped_issues[first_key][0]}")
            
        # Debug log the first few issues
        if all_issues:
            app.logger.debug(f"Total issues: {len(all_issues)}")
            for i, issue in enumerate(all_issues[:3]):
                app.logger.debug(f"Issue {i+1}: {issue}")
            
        # Dynamically collect unique values for all filterable fields
        for field in filterable_fields:
            if all_issues:
                unique_values[field] = sorted(set(issue.get(field, '') or 'Unassigned' for issue in all_issues if issue.get(field, '') != ''))
            else:
                unique_values[field] = []
    # If we have a shared card, make sure we're grouping by the correct field
    if shared_card_field and shared_card_field != group_by:
        group_by = shared_card_field
        
    return render_template(
        'jql_wip.html',
        jql=jql,
        grouped_issues=grouped_issues,
        group_by=group_by,
        error=error,
        jira_base_url=JIRA_BASE_URL,
        filterable_fields=filterable_fields,
        unique_values=unique_values,
        shared_card=shared_card
    )

@app.route('/api/jira_filters')
def api_jira_filters():
    """API endpoint to fetch Jira filters"""
    # Debug log environment variables
    app.logger.debug(f"JIRA_BASE_URL: {'Set' if JIRA_BASE_URL else 'Not set'}")
    app.logger.debug(f"JIRA_EMAIL: {'Set' if JIRA_EMAIL else 'Not set'}")
    app.logger.debug(f"JIRA_API_TOKEN: {'Set' if JIRA_API_TOKEN else 'Not set'}")
    
    # Check if Jira credentials are available
    if not JIRA_BASE_URL or not JIRA_EMAIL or not JIRA_API_TOKEN:
        app.logger.error("Jira credentials not configured in environment variables")
        return jsonify({
            'error': 'Jira credentials not configured. Please check server configuration.',
            'filters': []
        }), 500
    
    filters = []
    
    try:
        # Fetch favorite filters first
        fav_url = f"{JIRA_BASE_URL}/rest/api/2/filter/favourite"
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        auth = (JIRA_EMAIL, JIRA_API_TOKEN)
        
        # Fetch favorite filters
        try:
            app.logger.info(f"Fetching favorite filters from {fav_url}")
            response = requests.get(
                fav_url,
                auth=auth,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                favorite_filters = response.json()
                app.logger.info(f"Found {len(favorite_filters)} favorite filters")
                for f in favorite_filters:
                    try:
                        filters.append({
                            'id': f.get('id'),
                            'name': f.get('name', 'Unnamed Filter'),
                            'jql': f.get('jql', ''),
                            'favorite': True
                        })
                    except Exception as e:
                        app.logger.error(f"Error processing favorite filter {f.get('id')}: {str(e)}")
            else:
                app.logger.error(f"Failed to fetch favorite filters: {response.status_code} - {response.text}")
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Request error when fetching favorite filters: {str(e)}")
        
        # Fetch all filters (including non-favorites)
        try:
            all_url = f"{JIRA_BASE_URL}/rest/api/2/filter"
            app.logger.info(f"Fetching all filters from {all_url}")
            response = requests.get(
                all_url,
                auth=auth,
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 200:
                all_filters = response.json()
                app.logger.info(f"Found {len(all_filters)} total filters")
                # Add non-favorite filters
                favorite_ids = {f['id'] for f in filters}
                for f in all_filters:
                    try:
                        if f.get('id') not in favorite_ids:
                            filters.append({
                                'id': f.get('id'),
                                'name': f.get('name', 'Unnamed Filter'),
                                'jql': f.get('jql', ''),
                                'favorite': False
                            })
                    except Exception as e:
                        app.logger.error(f"Error processing filter {f.get('id')}: {str(e)}")
            else:
                app.logger.error(f"Failed to fetch all filters: {response.status_code} - {response.text}")
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Request error when fetching all filters: {str(e)}")
        
        print(f"Returning {len(filters)} total filters")
        app.logger.info(f"Returning {len(filters)} total filters")
        
        # Add some mock filters if no filters were found (for testing)
        if len(filters) == 0:
            print("No filters found, adding mock filters for testing")
            filters = [
                {
                    'id': 'mock-1',
                    'name': 'My Issues',
                    'jql': 'assignee = currentUser()',
                    'favorite': True
                },
                {
                    'id': 'mock-2',
                    'name': 'Created Recently',
                    'jql': 'created >= -7d',
                    'favorite': False
                },
                {
                    'id': 'mock-3',
                    'name': 'Done Last Sprint',
                    'jql': 'status = Done AND sprint in closedSprints()',
                    'favorite': False
                }
            ]
        
        return jsonify({
            'filters': filters
        })
    
    except Exception as e:
        error_msg = f"Unexpected error fetching Jira filters: {str(e)}"
        app.logger.exception(error_msg)
        return jsonify({
            'error': 'An unexpected error occurred while fetching filters',
            'filters': []
        }), 500

@app.route('/api/jira_filter/<filter_id>')
def api_jira_filter(filter_id):
    """API endpoint to fetch a specific Jira filter"""
    # Check if Jira credentials are available
    if not JIRA_BASE_URL or not JIRA_EMAIL or not JIRA_API_TOKEN:
        return jsonify({
            'error': 'Jira credentials not configured'
        }), 400
    
    try:
        url = f"{JIRA_BASE_URL}/rest/api/2/filter/{filter_id}"
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        response = requests.get(
            url,
            auth=(JIRA_EMAIL, JIRA_API_TOKEN),
            headers=headers
        )
        
        if response.status_code == 200:
            filter_data = response.json()
            return jsonify({
                'id': filter_data.get('id'),
                'name': filter_data.get('name'),
                'jql': filter_data.get('jql'),
                'favorite': filter_data.get('favourite', False)
            })
        else:
            return jsonify({
                'error': f"Error fetching filter: {response.status_code} - {response.text}"
            }), response.status_code
    
    except Exception as e:
        print(f"Error fetching Jira filter {filter_id}: {str(e)}")
        return jsonify({
            'error': f"Error fetching filter: {str(e)}"
        }), 500

# This endpoint has been replaced with a more comprehensive implementation above

# This endpoint has been replaced with a more comprehensive implementation above

@app.route('/api/jira_issue/<issue_key>')
def api_jira_issue(issue_key):
    import os
    import requests
    from flask import jsonify
    JIRA_BASE_URL = os.environ.get('JIRA_BASE_URL')
    JIRA_EMAIL = os.environ.get('JIRA_EMAIL')
    JIRA_API_TOKEN = os.environ.get('JIRA_API_TOKEN')
    if not (JIRA_BASE_URL and JIRA_EMAIL and JIRA_API_TOKEN):
        return jsonify({'error': 'Jira credentials not set'}), 500
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    auth = (JIRA_EMAIL, JIRA_API_TOKEN)
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}"
    params = {"fields": "summary,description,status,assignee,reporter,priority"}
    try:
        resp = requests.get(url, headers=headers, params=params, auth=auth)
        if resp.ok:
            data = resp.json()
            f = data.get('fields', {})
            def extract_adf_text(adf):
                if isinstance(adf, str):
                    return adf
                if not isinstance(adf, dict):
                    return ''
                text = ''
                if adf.get('type') == 'text':
                    text += adf.get('text', '')
                if 'content' in adf:
                    for item in adf['content']:
                        text += extract_adf_text(item)
                    if adf.get('type') == 'paragraph':
                        text += '\n'
                return text

            adf_desc = f.get('description', '')
            desc_text = ''
            if isinstance(adf_desc, dict):
                desc_text = extract_adf_text(adf_desc).strip()
            else:
                desc_text = adf_desc or ''
            result = {
                'key': issue_key,
                'summary': f.get('summary', ''),
                'description': desc_text,
                'status': f.get('status', {}).get('name', ''),
                'assignee': f.get('assignee', {}).get('displayName', ''),
                'reporter': f.get('reporter', {}).get('displayName', ''),
                'priority': f.get('priority', {}).get('name', ''),
            }
            return jsonify(result)

        else:
            return jsonify({'error': f'Jira API error: {resp.status_code} {resp.text}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# This section was removed to fix the duplicate route issue

print("Registered routes:")
for rule in app.url_map.iter_rules():
    print(rule)
# --- Screenshot Upload Route ---
import re
@app.route('/upload_screenshot', methods=['POST'])
def upload_screenshot():
    data = request.get_json()
    image_data = data.get('image')
    if not image_data or not image_data.startswith('data:image/png;base64,'):
        return jsonify({'error': 'Invalid image data'}), 400
    # Remove base64 header
    img_str = re.sub('^data:image/.+;base64,', '', image_data)
    img_bytes = base64.b64decode(img_str)
    # Create uploads dir if not exists
    upload_dir = os.path.join('static', 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    # Unique filename
    from datetime import datetime
    filename = f'screenshot_{datetime.now().strftime("%Y%m%d_%H%M%S_%f")}.png'
    file_path = os.path.join(upload_dir, filename)
    with open(file_path, 'wb') as f:
        f.write(img_bytes)
    image_url = url_for('static', filename=f'uploads/{filename}')
    return jsonify({'image_url': image_url})

@app.route('/release-blocker-analysis')
def release_blocker_analysis():
    # Render the Issue Bug Analysis page with JIRA base URL
    return render_template('issue_bug_analysis.html', 
                         jira_base_url=os.getenv('JIRA_BASE_URL', 'https://upgrad-jira.atlassian.net'))

@app.route('/api/analyze-blockers', methods=['POST'])
def analyze_blockers():
    data = request.json
    blocker_jql = data.get('jql', '').strip()
    
    if not blocker_jql:
        return jsonify({'error': 'No JQL query provided'}), 400
    
    # Initialize authentication
    auth = None
    if JIRA_USERNAME and JIRA_API_TOKEN:
        auth = (JIRA_USERNAME, JIRA_API_TOKEN)
    
    headers = {
        "Accept": "application/json"
    }
    
    try:
        # Use the dedicated blocker JQL to fetch release blockers
        blocker_url = f"{JIRA_BASE_URL}/rest/api/3/search"
        blocker_params = {
            "jql": blocker_jql,
            "maxResults": 100,
            "fields": "status,summary,parent,updated,created,statuscategorychangedate,customfield_10074"
        }
        
        blocker_response = requests.get(blocker_url, auth=auth, headers=headers, params=blocker_params)
        
        if blocker_response.status_code != 200:
            return jsonify({'error': f"Jira API error: {blocker_response.status_code} - {blocker_response.text}"}), 400
        
        blocker_data = blocker_response.json()
        blocker_issues = blocker_data.get('issues', [])
        
        # Process blockers and time in status data
        blockers = []
        time_in_status_data = []
        
        for issue in blocker_issues:
            issue_key = issue.get('key', '')
            issue_summary = issue.get('fields', {}).get('summary', '')
            issue_status = issue.get('fields', {}).get('status', {}).get('name', 'Unknown')
            
            # Get parent summary if available
            parent_summary = None
            if 'parent' in issue.get('fields', {}):
                parent_summary = issue.get('fields', {}).get('parent', {}).get('fields', {}).get('summary', 'No Parent')
            
            # Calculate days in current status (for backward compatibility)
            days_in_status = 0
            status_change_date = issue.get('fields', {}).get('statuscategorychangedate')
            
            if status_change_date:
                status_date = datetime.strptime(status_change_date.split('T')[0], '%Y-%m-%d')
                days_in_status = (datetime.now() - status_date).days
            
            # Fetch issue changelog to get status transition history
            changelog_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/changelog"
            changelog_response = requests.get(changelog_url, auth=auth, headers=headers)
            
            # Track all status transitions and history with detailed logging
            status_history = []
            current_status = issue.get('fields', {}).get('status', {}).get('name', 'Unknown')
            print(f"Processing issue {issue_key} with current status: {current_status}")
            
            if changelog_response.status_code == 200:
                changelog_data = changelog_response.json()
                histories = changelog_data.get('values', [])
                print(f"Found {len(histories)} history entries for issue {issue_key}")
                
                # Get the created date
                created_date = issue.get('fields', {}).get('created')
                created_datetime = None
                if created_date:
                    created_datetime = datetime.strptime(created_date.split('.')[0].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                    print(f"Issue {issue_key} created at {created_datetime}")
                    
                    # Add initial status as the first entry
                    status_history.append({
                        'from_status': 'Created',
                        'to_status': current_status,
                        'datetime': created_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                        'days': 0,
                        'hours': 0
                    })
                    print(f"Added initial status: Created -> {current_status}")
                
                # Process all status changes from the changelog
                last_datetime = created_datetime
                last_status = current_status
                
                # Process all changes chronologically
                for history in histories:
                    history_date = history.get('created')
                    history_author = history.get('author', {}).get('displayName', 'Unknown')
                    
                    if history_date:
                        history_datetime = datetime.strptime(history_date.split('.')[0].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
                        
                        # Process all items in this history entry
                        for item in history.get('items', []):
                            field_name = item.get('field')
                            from_value = item.get('fromString')
                            to_value = item.get('toString')
                            
                            # Log all field changes for debugging
                            print(f"Field change in {issue_key} at {history_datetime}: {field_name} from '{from_value}' to '{to_value}' by {history_author}")
                            
                            # Focus on status changes
                            if field_name == 'status':
                                # Calculate time in previous status
                                if last_datetime:
                                    time_diff = history_datetime - last_datetime
                                    days = time_diff.days
                                    hours = time_diff.total_seconds() / 3600  # Convert to hours
                                    
                                    status_entry = {
                                        'from_status': from_value,
                                        'to_status': to_value,
                                        'datetime': history_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                                        'days': days,
                                        'hours': round(hours, 2),
                                        'author': history_author
                                    }
                                    
                                    status_history.append(status_entry)
                                    print(f"Added status change: {from_value} -> {to_value} ({round(hours, 2)} hours)")
                                
                                last_datetime = history_datetime
                                last_status = to_value
                
                # Calculate time in current status
                if last_datetime:
                    now = datetime.now()
                    time_diff = now - last_datetime
                    days = time_diff.days
                    hours = time_diff.total_seconds() / 3600  # Convert to hours
                    
                    current_entry = {
                        'from_status': last_status,
                        'to_status': 'Current',
                        'datetime': now.strftime('%Y-%m-%d %H:%M:%S'),
                        'days': days,
                        'hours': round(hours, 2),
                        'author': 'System'
                    }
                    
                    status_history.append(current_entry)
                    print(f"Added current status: {last_status} -> Current ({round(hours, 2)} hours)")
            
            # COMPLETELY REWRITTEN: Calculate time spent in Open status
            hours_in_open = 0
            time_ranges = []
            open_statuses = ['open', 'open (migrated)']
            
            print(f"\n==== DETAILED STATUS ANALYSIS FOR {issue_key} ====\n")
            print(f"Current status: {current_status}")
            print(f"Total status transitions: {len(status_history)}")
            
            # First, log all status history for debugging
            print(f"\nComplete status history:")
            for i, status in enumerate(status_history):
                print(f"  {i+1}. {status['from_status']} -> {status['to_status']} on {status['datetime']} ({status['hours']} hours)")
            
            # Now calculate time in Open status with detailed logging
            print(f"\nCalculating time in Open status:")
            for i, status in enumerate(status_history):
                from_status_lower = status['from_status'].lower()
                
                # Check if this status period should be counted toward Open time
                is_open_status = any(open_name in from_status_lower for open_name in open_statuses)
                
                if is_open_status:
                    hours_in_open += status['hours']
                    print(f"  ✓ Adding {status['hours']} hours from '{status['from_status']}' -> '{status['to_status']}' (total: {hours_in_open})")
                    
                    # Add to time ranges for display in modal
                    time_ranges.append({
                        'from_status': status['from_status'],
                        'to_status': status['to_status'],
                        'datetime': status['datetime'],
                        'days': status['days'],
                        'hours': status['hours']
                    })
                else:
                    print(f"  ✗ Skipping {status['hours']} hours from '{status['from_status']}' -> '{status['to_status']}' (not an Open status)")
            
            # Special case: if currently in Open status, make sure we count that time too
            if current_status and any(open_name in current_status.lower() for open_name in open_statuses):
                # Find the most recent status entry that leads to current status
                for status in reversed(status_history):
                    if status['to_status'] == 'Current':
                        print(f"\nSpecial case: Issue is CURRENTLY in an Open status: {current_status}")
                        print(f"  ✓ Adding {status['hours']} hours from current Open status (total: {hours_in_open + status['hours']})")
                        
                        # Only add these hours if we haven't already counted them
                        if status['from_status'].lower() not in open_statuses:
                            hours_in_open += status['hours']
                            time_ranges.append({
                                'from_status': status['from_status'],
                                'to_status': 'Current',
                                'datetime': status['datetime'],
                                'days': status['days'],
                                'hours': status['hours']
                            })
                        break
                        
            print(f"\nFinal hours in Open status: {hours_in_open}")
            print(f"Number of Open time ranges: {len(time_ranges)}")
            print(f"==== END ANALYSIS FOR {issue_key} ====\n")
            
            # Add to blockers list with hours in open status and status history
            blockers.append({
                'key': issue_key,
                'summary': issue_summary,
                'status': issue_status,
                'parent_summary': parent_summary,
                'days_in_status': days_in_status,
                'hours_in_open': round(hours_in_open, 2),  # Round to 2 decimal places
                'time_ranges': time_ranges,
                'status_history': status_history
            })
            
            # Add to time in status data for backward compatibility
            time_in_status_data.append({
                'key': issue_key,
                'days_in_status': days_in_status
            })
        
        return jsonify({
            'blockers': blockers,
            'time_in_status_data': time_in_status_data,
            'jira_base_url': JIRA_BASE_URL
        })
        
    except Exception as e:
        print(f"Error analyzing blockers: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5001, debug=True)
