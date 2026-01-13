import asyncio
import sys
import os
import pandas as pd
from playwright.async_api import async_playwright

async def scrape_cbse(target_state, target_district):
    async with async_playwright() as p:
        # 1. Initialize Browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        print(f"🚀 Starting: {target_state} -> {target_district}")
        await page.goto("https://saras.cbse.gov.in/saras/AffiliatedList/ListOfSchdirReport")
        
        # 2. Selection Logic
        await page.click("#SearchMainRadioState_wise")
        await page.select_option("#State", label=target_state)
        await page.wait_for_timeout(2000) # Wait for District dropdown to populate
        
        if target_district.upper() != "ALL":
            await page.select_option("#District", label=target_district)
        
        await page.click("input[value='Search']")
        
        # 3. Wait for the table to actually load
        try:
            await page.wait_for_selector("#myTable tbody tr", timeout=15000)
        except:
            print(f"⚠️ No results found for {target_district}")
            await browser.close()
            return

        schools_data = []

        # 4. Extraction Loop with Pagination Support
        while True:
            rows = await page.locator("#myTable tbody tr").all()
            print(f"📄 Found {len(rows)} schools on this page.")

            for i in range(len(rows)):
                # Re-locate the row by index to avoid 'stale' element errors
                row = page.locator("#myTable tbody tr").nth(i)
                
                try:
                    # Scroll the row into view to make the 'View' link clickable
                    await row.scroll_into_view_if_needed()
                    
                    # Capture school name from the 5th column
                    name_cell = row.locator("td:nth-child(5)")
                    school_name = await name_cell.inner_text()

                    # Click 'View' and wait for the popup tab
                    async with context.expect_page() as new_page_info:
                        await row.locator("a:has-text('View')").click(timeout=5000)
                    
                    detail_page = await new_page_info.value
                    await detail_page.wait_for_load_state()

                    # Extract Email from the details page
                    try:
                        email_elem = detail_page.locator("a[href^='mailto:']").first
                        email = await email_elem.inner_text()
                    except:
                        email = "Not Available"
                    
                    schools_data.append({
                        "School_Name": school_name.strip(),
                        "Email": email.strip(),
                        "State": target_state,
                        "District": target_district
                    })
                    
                    await detail_page.close()
                    print(f"✅ Scraped: {school_name[:40]}...")
                
                except Exception as e:
                    print(f"❌ Skipped row {i} due to error: {str(e)[:100]}")

            # 5. Check for 'Next' button (DataTables pagination)
            next_button = page.locator("#myTable_next")
            is_disabled = await next_button.get_attribute("class")
            if "disabled" in is_disabled:
                break
            else:
                print("➡️ Moving to next page...")
                await next_button.click()
                await page.wait_for_timeout(2000) # Wait for table refresh

        # 6. Save Logic
        folder_path = f"Data/{target_state.replace(' ', '_')}"
        os.makedirs(folder_path, exist_ok=True)
        file_path = f"{folder_path}/{target_district.replace(' ', '_')}.xlsx"
        
        if schools_data:
            df = pd.DataFrame(schools_data)
            df.to_excel(file_path, index=False)
            print(f"📁 FINAL SUCCESS: Data saved to {file_path}")
        else:
            print("❌ No data collected.")

        await browser.close()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python main_scraper.py 'STATE' 'DISTRICT'")
    else:
        asyncio.run(scrape_cbse(sys.argv[1], sys.argv[2]))
