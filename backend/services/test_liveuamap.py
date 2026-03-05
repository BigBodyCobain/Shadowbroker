import json
from playwright.sync_api import sync_playwright

def scrape_liveuamap():
    print("Launching playwright...")
    with sync_playwright() as p:
        # User agents are important for headless browsing
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        def handle_response(response):
            try:
                if not response.url.endswith(('js', 'css', 'png', 'jpg', 'woff2', 'svg', 'ico')):
                    print(f"Intercepted API Call: {response.url}")
            except Exception:
                pass
                    
        page.on("response", handle_response)
        
        print("Navigating to liveuamap...")
        try:
            page.goto("https://liveuamap.com/", timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            
            print("Grabbing all script tags...")
            scripts = page.evaluate("() => Array.from(document.querySelectorAll('script')).map(s => s.innerText)")
            for i, s in enumerate(scripts):
                if 'JSON.parse' in s or 'markers' in s or 'JSON' in s:
                    with open(f"script_{i}.txt", "w", encoding="utf-8") as f:
                        f.write(s)
        except Exception as e:
            print("Playwright timeout or error:", e)
            
        print("Closing browser...")
        browser.close()

if __name__ == "__main__":
    scrape_liveuamap()
