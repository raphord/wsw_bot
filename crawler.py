import json
import os
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


INDEX_FILE = "index.json"
URLS_FILE = "urls.json"


def load_index():
    try:
        if os.path.exists(INDEX_FILE):
            with open(INDEX_FILE, "r", encoding="utf-8") as file:
                index = json.load(file)

            print(f"Loaded existing index from {INDEX_FILE}")
            return index
    except json.decoder.JSONDecodeError:
        pass
    print("No existing index found - starting with an empty index")
    return {}


def load_urls():
    if not os.path.exists(URLS_FILE):
        raise FileNotFoundError(f"Missing URL list: {URLS_FILE}")

    with open(URLS_FILE, "r", encoding="utf-8") as file:
        urls = json.load(file)

    if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
        raise ValueError(f"{URLS_FILE} must contain a JSON array of URL strings")

    return urls


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, sort_keys=True)


def dedupe_urls(urls):
    seen = set()
    deduped = []

    for url in urls:
        if url in seen:
            continue

        seen.add(url)
        deduped.append(url)

    return deduped


def move_url_in_index(index, old_url, new_url):
    for word, locations in index.items():
        if old_url not in locations:
            continue

        old_count = locations.pop(old_url)

        if new_url not in locations:
            locations[new_url] = old_count


def get_existing_page_counts(index, target_url):
    page_counts = {}

    for word, locations in index.items():
        if target_url in locations:
            page_counts[word] = locations[target_url]

    return page_counts


def fetch_page(url):
    response = requests.get(url, allow_redirects=False, timeout=10)

    if response.status_code not in (301, 302):
        response.raise_for_status()
        return url, response, None

    location = response.headers.get("Location")
    if not location:
        raise ValueError(f"Redirect from {url} did not include a Location header")

    redirected_url = urljoin(url, location)
    redirected_response = requests.get(redirected_url, timeout=10)
    redirected_response.raise_for_status()

    return redirected_response.url, redirected_response, response.status_code


def extract_word_counts(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    page_words = re.findall(r"[a-zA-Z]+", text.lower())

    word_counts = {}
    for word in page_words:
        if word not in word_counts:
            word_counts[word] = 0

        word_counts[word] += 1

    return word_counts


def sync_page(index, storage_url, word_counts):
    existing_index_words = set(index)
    previous_counts = get_existing_page_counts(index, storage_url)
    added_words = set(word_counts) - set(previous_counts)
    removed_words = set(previous_counts) - set(word_counts)

    for word in removed_words:
        del index[word][storage_url]
        if not index[word]:
            del index[word]

    for word, count in word_counts.items():
        if word not in index:
            index[word] = {}

        if word in added_words:
            if word not in existing_index_words:
                print(f"  NEW WORD: {word}")
            print(f"    Added {storage_url} ({count} occurrences)")
        elif previous_counts[word] != count:
            print(
                f"  UPDATED: {word} on {storage_url}: "
                f"{previous_counts[word]} -> {count}"
            )

        index[word][storage_url] = count


def crawl():
    index = load_index()
    urls = load_urls()

    for position, original_url in enumerate(list(urls)):
        print()
        print(f"Reading: {original_url}")

        final_url, response, redirect_status = fetch_page(original_url)
        storage_url = original_url

        if redirect_status is None:
            print(f"Response: {response.status_code}")
        elif redirect_status == 302:
            print(f"Response: 302 -> {final_url}")
        elif redirect_status == 301:
            print(f"Response: 301 -> {final_url}")
            move_url_in_index(index, original_url, final_url)
            urls[position] = final_url
            storage_url = final_url

        word_counts = extract_word_counts(response.text)
        sync_page(index, storage_url, word_counts)

    save_json(INDEX_FILE, index)
    save_json(URLS_FILE, dedupe_urls(urls))

    print()
    print(f"Index saved to {INDEX_FILE}")
    print(f"URL list saved to {URLS_FILE}")


if __name__ == "__main__":
    crawl()
