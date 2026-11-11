import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
import json
import sys
import time

def crawl_site(start_url, output_filename="crawl_results.json", delay=0.5):
    """
    Crawls a website starting at a specific path, strictly staying within or below that path.
    """
    # Ensure the start_url ends with a slash so it acts as a strict directory boundary.
    # Without this, 'site.com/app' could accidentally crawl 'site.com/apple' (parallel path).
    base_prefix = start_url if start_url.endswith('/') else start_url + '/'
    
    visited_urls = set()
    
    # We start by visiting the user's provided URL, even if it lacks a slash
    urls_to_visit = [start_url]
    results = []

    print(f"Starting crawl. Strictly locked to paths under: {base_prefix}")

    while urls_to_visit:
        current_url = urls_to_visit.pop(0)

        if current_url in visited_urls:
            continue

        visited_urls.add(current_url)
        print(f"Crawling: {current_url}")

        try:
            time.sleep(delay)
            
            response = requests.get(current_url, timeout=10)
            status_code = response.status_code
            
            is_success = 1 if status_code < 400 else 0

            results.append({
                "link": current_url,
                "success": is_success,
                "status_code": status_code
            })

            if is_success == 1 and 'text/html' in response.headers.get('Content-Type', ''):
                soup = BeautifulSoup(response.text, 'html.parser')
                
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    full_url = urljoin(current_url, href)
                    full_url = full_url.split('#')[0]
                    
                    # STRICT PATH CHECK: 
                    # 1. Must start with the base_prefix (keeps it from going up or parallel)
                    # 2. Must not be already visited or queued
                    if full_url.startswith(base_prefix) and full_url not in visited_urls and full_url not in urls_to_visit:
                        if urlparse(full_url).scheme in ['http', 'https']:
                            urls_to_visit.append(full_url)

        except requests.exceptions.RequestException as e:
            print(f"Failed to connect to {current_url}: {e}")
            results.append({
                "link": current_url,
                "success": 0,
                "status_code": 0 
            })

    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=4)

    print(f"\nCrawl complete. Checked {len(visited_urls)} links within the path boundary.")
    print(f"Results saved to {output_filename}")

# --- Execution Example ---
if __name__ == "__main__":
    # Replace this with the website you want to crawl
    target_website = sys.argv[1] 
    output_file = sys.argv[2]
    crawl_site(target_website, output_file)
