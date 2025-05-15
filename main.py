import json
import time
from fastapi import FastAPI, HTTPException, Request
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import threading

# ✅ First, define the app
app = FastAPI()

class SelectionRequest(BaseModel):
    url: str
    max_pages: int

selected_elements = []  # Store selected elements

def start_browser(url: str):
    """Launch Chrome for element selection."""
    chrome_options = Options()
    chrome_options.add_experimental_option("detach", True)  # Keep browser open

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    driver.get(url)

    # Inject JavaScript to enable element selection
    script = """
    function highlightElements() {
        document.body.style.cursor = 'crosshair';
        let selected = [];

        document.addEventListener('mouseover', function(event) {
            if (!event.target.classList.contains('selected-element')) {
                event.target.style.outline = '2px solid red';
            }
        });

        document.addEventListener('mouseout', function(event) {
            if (!event.target.classList.contains('selected-element')) {
                event.target.style.outline = '';
            }
        });

        document.addEventListener('click', function(event) {
            event.preventDefault();
            let xpath = getXPath(event.target);
            let text = event.target.innerText.trim();
            let attributes = {};
            for (let attr of event.target.attributes) {
                attributes[attr.name] = attr.value;
            }
            selected.push({xpath, text, attributes});
            event.target.style.outline = '3px solid blue';
            event.target.classList.add('selected-element');
            fetch("http://localhost:8000/store-xpath", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({xpath, text, attributes})
            });
        });

        function getXPath(element) {
            if (element.id) {
                return `//*[@id="${element.id}"]`;
            }
            
            if (element.className) {
                return `//*[contains(@class, "${element.className.split(' ')[0]}")]`;
            }

            if (element.tagName.toLowerCase() === "p" || element.tagName.toLowerCase() === "blockquote" || element.tagName.toLowerCase() === "span") {
                return `//${element.tagName.toLowerCase()}[contains(text(), "${element.textContent.trim()}")]`;
            }

            return `//${element.tagName.toLowerCase()}[1]`; // Default fallback
        }
    }
    highlightElements();
    """

    driver.execute_script(script)

@app.post("/select-elements")
async def select_elements(request: SelectionRequest):
    """Start the browser for element selection."""
    try:
        threading.Thread(target=start_browser, args=(request.url,), daemon=True).start()
        return {"message": "Selection mode activated. Click on elements in the browser!"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error starting browser: {str(e)}")

@app.post("/store-xpath")
async def store_xpath(data: dict):
    """Store the selected XPath, extracted text, and attributes."""
    xpath = data.get("xpath")
    text = data.get("text")
    
    
    if xpath and not any(ele['xpath'] == xpath for ele in selected_elements):
        selected_elements.append({"xpath": xpath, "text": text})
    
    return {"message": "XPath stored successfully"}

@app.post("/clear-xpaths")
async def clear_xpaths():
    global selected_elements
    selected_elements = []  # Reset the list
    return {"message": "XPaths cleared"}

@app.get("/scrape-elements")
async def scrape_elements(request: Request):
    """Scrape selected elements and return extracted text."""
    try:
        if not selected_elements:
            return {"message": "No elements selected yet!"}

        chrome_options = Options()
        chrome_options.add_argument("--headless")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        
        url = request.query_params.get("url")
        driver.get(url) 
        
        scraped_data = []
        for element in selected_elements:
            try:
                elements = driver.find_elements(By.XPATH, element['xpath'])
                for elem in elements:
                    text = driver.execute_script("return arguments[0].innerText;", elem).strip()
                    if text:
                        scraped_data.append({"xpath": element['xpath'], "text": text, "attributes": element['attributes']})
            except Exception as e:
                scraped_data.append({"xpath": element['xpath'], "error": str(e)})
        
        driver.quit()
        return {"scraped_data": scraped_data}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/get-xpaths")
async def get_xpaths():
    """Return all stored XPaths with details."""
    return {"selected_elements": selected_elements}

# ✅ Then, add middleware after app is defined
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (POST, GET, OPTIONS, etc.)
    allow_headers=["*"],  # Allow all headers
)

def scrape_website(url, max_pages=1):
    options = Options()
    options.add_argument("--headless")
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    all_data = []
    current_page = 1
    
    while current_page <= max_pages:
        time.sleep(2)
        driver.get(url)
        
        elements = driver.find_elements(By.XPATH, "//*")
        
        for element in elements:
            tag_name = element.tag_name
            text = driver.execute_script(
    "return arguments[0].innerText;", element
).strip()
            attributes = driver.execute_script(
                'var items = {}; for (var i = 0; i < arguments[0].attributes.length; i++) ' 
                '{ items[arguments[0].attributes[i].name] = arguments[0].attributes[i].value; } return items;', 
                element
            )
            
            if text or attributes:
                element_data = {"tag": tag_name, "text": text, "attributes": attributes}
                all_data.append(element_data)
        
        try:
            next_button = driver.find_element(By.LINK_TEXT, "Next")
            next_page = next_button.get_attribute("href")
            if next_page.startswith("/"):
                url = url.rstrip("/") + next_page
            else:
                url = next_page
            current_page += 1
        except:
            break
    
    driver.quit()  # Ensure the driver is closed after scraping
    return all_data

@app.post("/scrape")
async def scrape(request: Request):
    try:
        body = await request.json()
        url = body.get("url")
        max_pages = body.get("max_pages", 1)

        if not url:
            raise HTTPException(status_code=400, detail="Missing 'url' parameter")

        data = scrape_website(url, max_pages)
        return {"status": "success", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
