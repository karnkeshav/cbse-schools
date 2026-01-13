import asyncio
import csv
import random
import os
import urllib.parse
from playwright.async_api import async_playwright

class CBSEScraper:
    def __init__(self, output_file="cbse_schools.csv"):
        self.output_file = output_file
        self.base_url = "https://saras.cbse.gov.in/saras/AffiliatedList/ListOfSchdirReport"
        self.data_buffer = []

        # Initialize CSV if it doesn't exist
        if not os.path.exists(self.output_file):
            with open(self.output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["School Name", "Affiliation Number", "Principal Name", "Email Address", "State", "District"])

    async def init_browser(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        # Increase timeout for navigation
        self.context.set_default_timeout(60000)

    async def close(self):
        await self.browser.close()
        await self.playwright.stop()

    async def save_data(self, data):
        with open(self.output_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                data.get("School Name", ""),
                data.get("Affiliation Number", ""),
                data.get("Principal Name", ""),
                data.get("Email Address", ""),
                data.get("State", ""),
                data.get("District", "")
            ])

    async def get_states(self, page):
        # Ensure we are on the page and State dropdown is visible
        # We need to click "State wise" radio first
        await page.click("#SearchMainRadioState_wise")
        # Wait for the select element itself to be visible, not options
        await page.wait_for_selector("#State", state="visible")

        options = await page.eval_on_selector_all("#State option", "options => options.map(o => ({text: o.innerText, value: o.value}))")
        # Filter out empty or "select"
        states = [o for o in options if o["value"] and "select" not in o["text"].lower()]
        return states

    async def get_districts(self, page, state_value):
        # Select state
        await page.select_option("#State", value=state_value)

        # Wait for district dropdown to populate (more than 1 option)
        # We'll try up to a few seconds. If it stays at 1, maybe there are no districts or it failed.
        try:
            await page.wait_for_function("document.getElementById('District').options.length > 1", timeout=5000)
        except:
            print(f"  Timeout waiting for districts for state {state_value}")
            return []

        options = await page.eval_on_selector_all("#District option", "options => options.map(o => ({text: o.innerText, value: o.value}))")
        districts = [o for o in options if o["value"] and o["value"] != "0" and "select" not in o["text"].lower()]
        return districts

    async def process_school_details(self, page, detail_url, state_name, district_name):
        new_page = await self.context.new_page()
        try:
            full_url = urllib.parse.urljoin("https://saras.cbse.gov.in", detail_url)
            await new_page.goto(full_url)

            # Extract data
            # Using XPath or CSS selectors based on the table structure found in probe
            # Table is <table class="table table-bordered">
            # Rows have <td><b>Label</b></td><td>Value</td>

            def get_field(label):
                # XPath to find td with bold label, then get next sibling td text
                # Normalize space to handle whitespace
                xpath = f"//td[b[contains(text(), '{label}')]]/following-sibling::td"
                return new_page.locator(xpath).first

            school_name = await get_field("Name of Institution").inner_text()
            aff_no = await get_field("Affiliation Number").inner_text()
            principal = await get_field("Name of Principal").inner_text()

            # Email is not found in HTML, but we'll try to look for it generically just in case
            # or leave empty
            email = "Not Available"

            data = {
                "School Name": school_name.strip(),
                "Affiliation Number": aff_no.strip(),
                "Principal Name": principal.strip(),
                "Email Address": email,
                "State": state_name,
                "District": district_name
            }

            await self.save_data(data)
            print(f"    Scraped: {data['School Name']}")

        except Exception as e:
            print(f"    Error scraping detail {detail_url}: {e}")
        finally:
            await new_page.close()

    async def scrape(self):
        await self.init_browser()
        page = await self.context.new_page()

        try:
            print("Navigating to home...")
            await page.goto(self.base_url)

            states = await self.get_states(page)
            print(f"Found {len(states)} states.")

            for state in states:
                state_name = state["text"]
                state_val = state["value"]
                print(f"Processing State: {state_name} ({state_val})")

                # Refresh page or reset to ensure clean state for each state loop
                # (Although we could just change dropdowns, refreshing is safer against stale DOM)
                await page.goto(self.base_url)
                await page.click("#SearchMainRadioState_wise")

                districts = await self.get_districts(page, state_val)
                print(f"  Found {len(districts)} districts.")

                for district in districts:
                    district_name = district["text"]
                    district_val = district["value"]
                    print(f"  Processing District: {district_name} ({district_val})")

                    # We need to re-select state and district because we might have navigated away or refreshed
                    # But since we are iterating, let's just ensure we are on the main page
                    # and select values.

                    # If we are not on the search page (e.g. after a search), go back
                    if "ListOfSchdirReport" not in page.url:
                         await page.goto(self.base_url)

                    # Ensure radio is clicked
                    if not await page.is_checked("#SearchMainRadioState_wise"):
                        await page.click("#SearchMainRadioState_wise")

                    # Select State
                    await page.select_option("#State", value=state_val)
                    # Wait for districts
                    await page.wait_for_function("document.getElementById('District').options.length > 1")
                    # Select District
                    await page.select_option("#District", value=district_val)

                    # Click Search
                    # Search triggers a POST and page reload.
                    async with page.expect_navigation():
                        await page.click("input[value='Search']")

                    # Now we are on the results page.
                    # We need to handle pagination.
                    # The table id is #myTable.

                    while True:
                        # Process current page rows
                        # Row selector: #myTable tbody tr
                        rows = page.locator("#myTable tbody tr")
                        count = await rows.count()
                        print(f"    Found {count} schools on current page.")

                        if count == 0:
                            break

                        # Iterate rows
                        # Note: If we navigate away in the same tab, we lose the rows handle.
                        # So we must open details in a NEW tab (which the link does).

                        for i in range(count):
                            row = rows.nth(i)
                            # Get 'View' link href
                            # It is in the last column
                            try:
                                link = row.locator("td:last-child a")
                                href = await link.get_attribute("href")
                                if href:
                                    await self.process_school_details(page, href, state_name, district_name)
                            except Exception as e:
                                print(f"    Error processing row {i}: {e}")

                        # Check for Next button
                        # Pagination: #myTable_paginate .paginate_button.next
                        # Class 'disabled' means no more pages.
                        next_btn = page.locator("#myTable_next")
                        if await next_btn.count() > 0:
                            classes = await next_btn.get_attribute("class")
                            if "disabled" in classes:
                                break
                            else:
                                print("    Next page...")
                                await next_btn.click()
                                # Wait for table to update?
                                # DataTables client side pagination is instant, but if it's server side...
                                # The probe showed "Showing 1 to 10 of 127 entries".
                                # If all 127 are loaded in DOM but hidden, Playwright might see them all if we search by tr?
                                # No, usually they are removed from DOM.
                                # DataTables updates the DOM.
                                # We need to wait for the first row to change or something?
                                # Or just wait a small delay.
                                await page.wait_for_timeout(1000)
                        else:
                            break

                    # Backoff
                    await asyncio.sleep(random.uniform(1, 3))

                    # Go back to main page for next district
                    await page.goto(self.base_url)

        except Exception as e:
            print(f"Global Error: {e}")
        finally:
            await self.close()

if __name__ == "__main__":
    scraper = CBSEScraper()
    asyncio.run(scraper.scrape())
