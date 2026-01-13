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
        
        print(f"🚀 Starting scrape for: {target_state} -> {target_district}")
        await page.goto("https://saras.cbse.gov.in/saras/AffiliatedList/ListOfSchdirReport")
        
        # 2. Select State-wise Search
        await page.click("#SearchMainRadioState_wise")
        
        # 3. Select State from dropdown
        await page.select_option("#State", label=target_state)
        await page.wait_for_timeout(2000) # Allow district dropdown to load
        
        # 4. Select District
        if target_district.upper() != "ALL":
            await page.select_option("#District", label=target_district)
        
        # 5. Click Search
        await page.click("input[value='Search']")
        await page.wait_for_selector("#myTable", timeout=10000)

        # 6. Extraction Loop
        schools_data = []
        rows = await page.locator("#myTable tbody tr").all()
        
        for row in rows:
            # Open the 'Details' view to get the email
            # Usually opens in a new tab or popup
            async with context.expect_page() as new_page_info:
                await row.locator("a:has-text('View')").click()
            
            detail_page = await new_page_info.value
            await detail_page.wait_for_load_state()
            
            # Extract Email (Targeting the specific link pattern)
            try:
                email_elem = detail_page.locator("a[href^='mailto:']").first
                email = await email_elem.inner_text()
            except:
                email = "Not Available"
            
            # Extract School Name
            school_name = await row.locator("td:nth-child(5)").inner_text()
            
            schools_data.append({
                "School_Name": school_name.strip(),
                "Email": email.strip(),
                "State": target_state,
                "District": target_district
            })
            
            await detail_page.close()
            print(f"✅ Scraped: {school_name[:30]}...")

        # 7. Save Phase: Organized Folders for Ready4Exam
        folder_path = f"Data/{target_state.replace(' ', '_')}"
        os.makedirs(folder_path, exist_ok=True)
        file_path = f"{folder_path}/{target_district.replace(' ', '_')}.xlsx"
        
        df = pd.DataFrame(schools_data)
        df.to_excel(file_path, index=False)
        print(f"📁 Data saved to: {file_path}")

        await browser.close()

if __name__ == "__main__":
    # Get State and District from GitHub Action inputs
    state_input = sys.argv[1]
    dist_input = sys.argv[2]
    asyncio.run(scrape_cbse(state_input, dist_input))
