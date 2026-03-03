import time
from pathlib import Path
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
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
    options.add_argument("--start-maximized")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    try:
        login_url = f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
        driver.get(login_url)

        # Wait and login
        time.sleep(2)
        driver.find_element(By.ID, "userid").send_keys(user_id)
        driver.find_element(By.ID, "password").send_keys(password)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()

        # Wait for TOTP screen
        time.sleep(2)
        otp = pyotp.TOTP(totp_secret).now()
        print(f"✅ TOTP: {otp}")
        driver.find_element(By.XPATH, "//input[@type='number']").send_keys(otp)
        driver.find_element(By.XPATH, "//button[@type='submit']").click()

        # Wait for redirect
        time.sleep(5)
        current_url = driver.current_url

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
    kite = KiteConnect(api_key=api_key)
    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]
    with open("Cred/access_token.txt", "w") as f:
        f.write(access_token)

    print("Access token saved!")
