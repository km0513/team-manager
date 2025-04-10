import requests
from requests.auth import HTTPBasicAuth

# Jira instance details
JIRA_BASE_URL = "https://upgrad-jira.atlassian.net"
JIRA_EMAIL = "kishore.murkhanad@upgrad.com"
JIRA_API_TOKEN = "REMOVED3xFfGF0_6ptUkViQJjGO72_7sTkR-SpSuoFyk5KZUQSW4lpoD9_qW7RXxdWBpZlu_phU_o6F_WJpFIFzf-2s5CN9bfJXY9Z78vAafipCZMMJ1hYA4OmlSkJ-d-RtEk2rA4JNmTcmLmc3mVLj6ZEHNZMaQMNalau1WeXtCTWvS0S-PKT1Es=02619F01"


# List of user email addresses
user_emails = ['aditya1.prasad@upgrad.com', 'devineni.durga@upgrad.com','mahesh.zanje@upgrad.com','ramesh.rao@upgrad.com','Rajeshwaridevi.kanumula@upgrad.com','meghana.puram@upgrad.com','raghupathi.reddy@upgrad.com','prakash1.shankar@upgrad.com','sai.geethika@upgrad.com','puja.yellamelli@upgrad.com']

# Function to get account ID by email
def get_account_id(email):
    url = f'{JIRA_BASE_URL}/rest/api/3/user/search?query={email}'
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {'Accept': 'application/json'}
    response = requests.get(url, headers=headers, auth=auth)
    if response.ok:
        users = response.json()
        if users:
            return users[0]['accountId']
    return None

# Retrieve account IDs for all users
user_account_ids = {email: get_account_id(email) for email in user_emails}

# Output the results
for email, account_id in user_account_ids.items():
    print(f'Email: {email}, Account ID: {account_id}')


 