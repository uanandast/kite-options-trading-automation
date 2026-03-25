import time
from pathlib import Path
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from urllib.parse import urlparse, parse_qs
import configparser
from kiteconnect import KiteConnect

# === Your Kite credentials ===

config = configparser.ConfigParser()
config_path = Path(__file__).parent.parent / "Cred" / "Cred_kite_PREM.ini"
config.read(config_path)

api_key = config['Kite']['api_key']
api_secret = config['Kite']['api_secret']
user_id = config['Kite']['user_id']
password = config['Kite']['password']
totp_secret = config['Kite']['totp_secret']  

def get_request_token():
    # Setup Chrome
    options = webdriver.ChromeOptions()
    options.binary_location = "/usr/bin/google-chrome"
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")

    service = Service("/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)

    try:
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
        driver.get(login_url)

        wait = WebDriverWait(driver, 20)

        # Login step
        username = wait.until(EC.presence_of_element_located((By.ID, "userid")))
        username.send_keys(user_id)

        password_el = driver.find_element(By.ID, "password")
        password_el.send_keys(password)

        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(1)
        driver.switch_to.default_content()

        # TOTP step (with retry to avoid stale element issues)
        for attempt in range(3):
            try:
                totp = pyotp.TOTP(totp_secret).now()
                print(f"✅ TOTP: {totp}")

                totp_input = wait.until(
                    EC.presence_of_element_located((By.XPATH, "//input"))
                )

                totp_input.clear()
                totp_input.send_keys(totp)

                driver.find_element(By.XPATH, "//button[@type='submit']").click()
                break

            except Exception as e:
                print(f"Retrying TOTP... {attempt+1}")
                time.sleep(2)

        # Wait for redirect with request_token
        wait.until(lambda d: "request_token" in d.current_url)
        current_url = driver.current_url

        if "request_token" not in current_url:
            raise Exception("Login failed: request_token not found")

        # Extract request_token from redirect URL
        parsed = urlparse(current_url)
        query = parse_qs(parsed.query)
        request_token = query.get("request_token", [None])[0]

        if request_token:
            print(f"✅ Request token: {request_token}")
        else:
            print("❌ Failed to retrieve request token. Check login details or TOTP.")
        
        return request_token

    except Exception as e:
        print(f"❌ Error during login: {e}")
        return None

    finally:
        driver.quit()

# Run the flow
if __name__ == "__main__":
    request_token = get_request_token()
    if not request_token:
        raise Exception("Login failed: request_token is None")

    kite = KiteConnect(api_key=api_key)
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]
    with open("Cred/access_token.txt", "w") as f:
        f.write(access_token)

    print("Access token saved!")

