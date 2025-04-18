from flask import render_template, request
from app import app, User
from datetime import datetime, timedelta
from jira_worklog_batch import fetch_issue_details_individual
from app import JIRA_BASE_URL, headers, auth

@app.route('/user-timelog/<user_email>')
def user_timelog(user_email):
    users = User.query.all()
    user = next((u for u in users if u.email == user_email), None)
    if not user:
        return render_template('user_timelog.html', error='User not found', user=None)
    # Date logic
    ist = datetime.now().astimezone().tzinfo
    current_date = datetime.now(ist).strftime('%Y-%m-%d')
    date_str = request.args.get('date') or current_date
    display_date_str = datetime.strptime(date_str, "%Y-%m-%d").strftime('%-d %B %Y') if hasattr(datetime, 'strftime') else date_str
    # Previous/Next date
    current_dt = datetime.strptime(date_str, "%Y-%m-%d")
    previous_date = (current_dt - timedelta(days=1)).strftime('%Y-%m-%d')
    next_date = (current_dt + timedelta(days=1)).strftime('%Y-%m-%d') if current_dt.date() < datetime.now().date() else None
    # Fetch logs for user for this date
    worklogs = []
    logs = []
    # Try to use the same batch fetch logic as timelog_today
    from app import get_time_spent_by_user_range
    user_logs = get_time_spent_by_user_range(date_str, date_str)
    # Fetch issue details if any logs
    issue_ids = list(user_logs.keys())
    issue_details = fetch_issue_details_individual(JIRA_BASE_URL, headers, auth, issue_ids) if issue_ids else {}
    for issue_id, hours in user_logs.items():
        details = issue_details.get(issue_id, {})
        logs.append({
            'issue_key': details.get('key', ''),
            'summary': details.get('summary', ''),
            'parent_summary': details.get('parent_summary', ''),
            'hours': hours,
            'started': date_str
        })
    return render_template('user_timelog.html', user=user, logs=logs, previous_date=previous_date, next_date=next_date, display_date_str=display_date_str, error=None)
