import requests
import time
import threading
import json

def get_epoch_ms(date_str):
    # date_str: 'YYYY-MM-DD'
    return int(time.mktime(time.strptime(date_str, "%Y-%m-%d"))) * 1000


def fetch_worklog_ids_updated_since(jira_base_url, headers, auth, since_epoch_ms):
    """
    Fetch all worklog IDs updated since a given timestamp (epoch ms).
    Returns a list of worklog IDs.
    """
    url = f"{jira_base_url}/rest/api/3/worklog/updated"
    worklog_ids = []
    next_since = since_epoch_ms
    while True:
        resp = requests.get(url, headers=headers, auth=auth, params={"since": next_since})
        if not resp.ok:
            break
        data = resp.json()
        worklog_ids.extend([item['worklogId'] for item in data.get('values', [])])
        if data.get('lastPage', True):
            break
        next_since = data.get('nextPage', None)
        if not next_since:
            break
    return worklog_ids


def fetch_worklogs_by_ids(jira_base_url, headers, auth, worklog_ids):
    """
    Fetch worklog details for a list of worklog IDs (max 1000 per request).
    Returns a list of worklog dicts.
    """
    url = f"{jira_base_url}/rest/api/3/worklog/list"
    all_worklogs = []
    for i in range(0, len(worklog_ids), 1000):
        batch = worklog_ids[i:i+1000]
        resp = requests.post(url, headers=headers, auth=auth, json={"ids": batch})
        if resp.ok:
            # Jira returns a list, not a dict, for /worklog/list
            data = resp.json()
            if isinstance(data, list):
                all_worklogs.extend(data)
            elif isinstance(data, dict):
                all_worklogs.extend(data.get('values', []))
    return all_worklogs


def fetch_issue_details_bulk(jira_base_url, headers, auth, issue_ids):
    """
    Fetch issue details (key, summary, parent summary) for a set of issue IDs using the Jira bulk API.
    Returns a dict: {issue_id: {"key": ..., "summary": ..., "parent_summary": ...}}
    """
    url = f"{jira_base_url}/rest/api/3/issue/bulk"
    results = {}
    issue_id_list = list(issue_ids)
    for i in range(0, len(issue_id_list), 100):  # Jira bulk API allows up to 100 per call
        batch = issue_id_list[i:i+100]
        resp = requests.post(url, headers=headers, auth=auth, json={"ids": batch, "fields": ["summary", "parent"]})
        if resp.ok:
            data = resp.json()
            for issue in data.get("issues", []):
                issue_id = str(issue.get("id"))
                issue_key = issue.get("key", "")
                summary = issue.get("fields", {}).get("summary", "")
                parent_summary = issue.get("fields", {}).get("parent", {}).get("fields", {}).get("summary", "")
                results[issue_id] = {"key": issue_key, "summary": summary, "parent_summary": parent_summary}
    return results


ISSUE_CACHE_FILE = 'issue_details_cache.json'
ISSUE_CACHE_LOCK = threading.Lock()

def load_issue_cache():
    try:
        with ISSUE_CACHE_LOCK:
            with open(ISSUE_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        return {}

def save_issue_cache(cache):
    with ISSUE_CACHE_LOCK:
        with open(ISSUE_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f)

def fetch_issue_details_individual(jira_base_url, headers, auth, issue_ids):
    """
    Fetch issue details (key, summary, parent summary) for each issueId individually, using a persistent cache.
    Returns a dict: {issue_id: {"key": ..., "summary": ..., "parent_summary": ...}}
    """
    cache = load_issue_cache()
    results = {}
    to_fetch = [iid for iid in issue_ids if iid not in cache]
    for issue_id in to_fetch:
        url = f"{jira_base_url}/rest/api/3/issue/{issue_id}"
        resp = requests.get(url, headers=headers, auth=auth, params={"fields": "summary,parent"})
        if resp.ok:
            data = resp.json()
            issue_key = data.get("key", "")
            summary = data.get("fields", {}).get("summary", "")
            parent_summary = data.get("fields", {}).get("parent", {}).get("fields", {}).get("summary", "")
            cache[str(issue_id)] = {"key": issue_key, "summary": summary, "parent_summary": parent_summary}
    save_issue_cache(cache)
    for issue_id in issue_ids:
        if issue_id in cache:
            results[issue_id] = cache[issue_id]
    return results
