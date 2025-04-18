import os
import requests
from flask import render_template
from datetime import datetime, timedelta
from collections import defaultdict
from app import db, User, Leave, JIRA_BASE_URL, headers, auth

def process_timelog_request(form):
    users = User.query.all()
    summary_data = []
    detailed_data = defaultdict(list)
    ordered_detailed_data = {}
    total_logged_by_user = {}
    start = form.get('start')
    end = form.get('end')
    selected_function = form.get('work_function')

    work_functions = sorted(set([u.designation for u in users if u.designation]))

    start_date = datetime.strptime(start, "%Y-%m-%d")
    end_date = datetime.strptime(end, "%Y-%m-%d")
    filtered_users = [u for u in users if u.jira_account_id and (selected_function == 'All' or u.designation == selected_function)]
    assignee_ids = [u.jira_account_id for u in filtered_users]

    # Parallelize worklog fetching
    import concurrent.futures
    issues = []
    jql = f"issuetype = Sub-task AND assignee in ({','.join(assignee_ids)}) AND worklogDate >= '{start}' AND worklogDate <= '{end}'"
    url = f"{JIRA_BASE_URL}/rest/api/2/search"
    params = {"jql": jql, "fields": "summary,parent,assignee,worklog", "maxResults": 1000}
    response = requests.get(url, headers=headers, params=params, auth=auth)
    if response.ok:
        issues = response.json().get("issues", [])
    user_map = {u.jira_account_id: u.name for u in filtered_users}
    user_order = [u.name for u in filtered_users]
    ordered_detailed_data = {name: [] for name in user_order}

    def fetch_worklogs(issue):
        issue_key = issue.get("key")
        summary = issue["fields"].get("summary", "")
        parent = issue["fields"].get("parent", {}).get("fields", {}).get("summary", "")
        assignee_id = issue["fields"].get("assignee", {}).get("accountId")
        worklog_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/worklog"
        worklog_resp = requests.get(worklog_url, headers=headers, auth=auth)
        result = []
        if worklog_resp.ok:
            for worklog in worklog_resp.json().get("worklogs", []):
                started = worklog.get("started", "")[:10]
                if start <= started <= end:
                    time_spent = worklog.get("timeSpentSeconds", 0)
                    user_name = user_map.get(worklog["author"].get("accountId"))
                    if user_name:
                        result.append({
                            "user_name": user_name,
                            "issue_key": issue_key,
                            "summary": summary,
                            "parent_summary": parent,
                            "hours": round(time_spent / 3600, 2),
                            "link": f"{JIRA_BASE_URL}/browse/{issue_key}",
                            "started": started
                        })
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_worklogs, issues)
        for res in results:
            for entry in res:
                ordered_detailed_data[entry["user_name"]].append(entry)
                total_logged_by_user[entry["user_name"]] = total_logged_by_user.get(entry["user_name"], 0) + entry["hours"]

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
    # Store or return results as needed (e.g., save to DB, notify user, etc.)
    # For demo: just print
    print('Timelog summary:', summary_data)
    return summary_data, ordered_detailed_data
