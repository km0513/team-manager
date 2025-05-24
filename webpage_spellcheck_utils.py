import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.common.exceptions import WebDriverException
from bs4 import BeautifulSoup
from spellchecker import SpellChecker


def extract_text_and_screenshot(url, output_dir='static/uploads', screenshot_prefix='webpage_screenshot'):
    """
    Loads a webpage, extracts visible text, takes a screenshot, and returns both.
    Returns: (screenshot_path, extracted_text)
    """
    # Setup headless Chrome
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-dev-shm-usage')

    # Try to use chromedriver from PATH
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(url)
        time.sleep(2)  # Wait for page to load

        # Take screenshot
        os.makedirs(output_dir, exist_ok=True)
        timestamp = int(time.time())
        screenshot_filename = f"{screenshot_prefix}_{timestamp}.png"
        screenshot_path = os.path.join(output_dir, screenshot_filename)
        driver.save_screenshot(screenshot_path)

        # Extract visible text using BeautifulSoup
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # Remove script and style elements
        for script in soup(["script", "style", "noscript"]):
            script.extract()
        # Get visible text
        text = ' '.join(soup.stripped_strings)
        return screenshot_path, text
    except WebDriverException as e:
        return None, f"Webdriver error: {e}"
    finally:
        if driver:
            driver.quit()

def spellcheck_text(text):
    """
    Spellchecks the provided text and returns a list of misspelled words with context.
    """
    spell = SpellChecker()
    words = text.split()
    misspelled = spell.unknown(words)
    # For context, return a list of dicts: {word, context}
    results = []
    for word in misspelled:
        # Find a context snippet (sentence or phrase containing the word)
        idx = text.lower().find(word.lower())
        context = text[max(0, idx-40):idx+40] if idx != -1 else ''
        suggestions = spell.candidates(word)
        # Ensure suggestions is always a list for join()
        if not isinstance(suggestions, (list, set, tuple)):
            suggestions = [str(suggestions)] if suggestions else []
        results.append({
            'word': word,
            'suggestion': list(suggestions),
            'context': context
        })
    return results
