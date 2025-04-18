import os
import json
import hashlib
import glob

def get_cache_filename(params):
    key = json.dumps(params, sort_keys=True)
    hashed = hashlib.md5(key.encode()).hexdigest()
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    return os.path.join(cache_dir, f"timelog_{hashed}.json")

def save_to_cache(params, data):
    filename = get_cache_filename(params)
    with open(filename, "w") as f:
        json.dump(data, f)

def load_from_cache(params):
    filename = get_cache_filename(params)
    if os.path.exists(filename):
        with open(filename) as f:
            return json.load(f)
    return None

def clear_timelog_cache():
    cache_dir = "cache"
    if os.path.exists(cache_dir):
        for file in glob.glob(os.path.join(cache_dir, "timelog_*.json")):
            os.remove(file)
