from playwright.sync_api import sync_playwright

def test_selector():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<div><span>No records found</span></div>")
        
        selectors = [
            "text=No records found",
            "text='No records found'",
            "text=\"No records found\"",
            ":has-text('No records found')",
            "text=No records found, text=No data"
        ]
        for sel in selectors:
            loc = page.locator(sel)
            print(f"Selector: {sel} -> Count: {loc.count()}")
            
        browser.close()

if __name__ == "__main__":
    test_selector()
