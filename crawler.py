import json
import os
import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup


INDEX_FILE = "index.json"
URLS_FILE = "urls.json"
USER_AGENT = "WSWBot/1.0"
REQUEST_TIMEOUT = 10


def load_index():
    try:
        if os.path.exists(INDEX_FILE):
            with open(INDEX_FILE, "r", encoding="utf-8") as file:
                raw_index = file.read()

            if not raw_index.strip():
                print(f"Index file {INDEX_FILE} is empty - starting with an empty index")
                return {}

            index = json.loads(raw_index)

            if not isinstance(index, dict):
                print(f"Index file {INDEX_FILE} is invalid - starting with an empty index")
                return {}

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


def build_headers():
    return {"User-Agent": USER_AGENT}


def get_robots_parser(url, robots_cache):
    parsed_url = urlparse(url)
    robots_origin = f"{parsed_url.scheme}://{parsed_url.netloc}"

    if robots_origin in robots_cache:
        return robots_cache[robots_origin]

    robots_url = urljoin(robots_origin, "/robots.txt")
    parser = RobotFileParser()
    parser.set_url(robots_url)

    try:
        response = requests.get(robots_url, headers=build_headers(), timeout=REQUEST_TIMEOUT)
        if response.status_code == 404:
            robots_cache[robots_origin] = None
            return None

        response.raise_for_status()
        parser.parse(response.text.splitlines())
        robots_cache[robots_origin] = parser
        return parser
    except requests.RequestException as exc:
        print(f"Could not read robots.txt for {robots_origin}: {exc}")
        robots_cache[robots_origin] = None
        return None


def is_crawl_allowed(url, robots_cache):
    parser = get_robots_parser(url, robots_cache)
    if parser is None:
        return True

    allowed = parser.can_fetch(USER_AGENT, url)
    if not allowed:
        print(f"Disallowed by robots.txt: {url}")

    return allowed


def fetch_page(url, robots_cache):
    if not is_crawl_allowed(url, robots_cache):
        return None, None, None

    response = requests.get(
        url,
        allow_redirects=False,
        headers=build_headers(),
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code not in (301, 302):
        response.raise_for_status()
        return url, response, None

    location = response.headers.get("Location")
    if not location:
        raise ValueError(f"Redirect from {url} did not include a Location header")

    redirected_url = urljoin(url, location)
    if not is_crawl_allowed(redirected_url, robots_cache):
        return None, None, None

    redirected_response = requests.get(
        redirected_url,
        headers=build_headers(),
        timeout=REQUEST_TIMEOUT,
    )
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
    robots_cache = {}

    for position, original_url in enumerate(list(urls)):
        print()
        print(f"Reading: {original_url}")

        final_url, response, redirect_status = fetch_page(original_url, robots_cache)
        if response is None:
            continue

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
