from rq import get_current_job
from redis import Redis
from app import app  # Adjust if your Flask app is in a different module
from timelog_background import process_timelog_request

import os

redis_conn = Redis(
    host=os.getenv('REDIS_HOST'),
    port=int(os.getenv('REDIS_PORT')),
    decode_responses=True,
    username=os.getenv('REDIS_USERNAME'),
    password=os.getenv('REDIS_PASSWORD'),
    ssl=True
)


def process_timelog_report(form):
    """
    Background job to process timelog data for a given date range and user list.
    Accepts a dict (form) with 'start', 'end', and 'work_function'.
    Returns summary and detailed data.
    """
    with app.app_context():
        summary_data, detailed_data = process_timelog_request(form)
        # Optionally: save result to DB, cache, or file
        return {'summary': summary_data, 'details': detailed_data}
