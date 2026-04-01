import time
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urlparse, parse_qs
import configparser
from kiteconnect import KiteConnect
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
import os
import requests
from datetime import datetime



# === Your Kite credentials ===

config = configparser.ConfigParser()

config.read('Cred/Cred_kite_PREM.ini')

api_key = config['Kite']['api_key']
api_secret = config['Kite']['api_secret']
user_id = config['Kite']['user_id']
password = config['Kite']['password']
totp_secret = config['Kite']['totp_secret']  

# Telegram alert function
def send_telegram(message):
    BOT_TOKEN = config.get('Kite', 'BOT_TOKEN')
    CHAT_ID = config.get('Kite', 'CHAT_ID')

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {
        "chat_id": CHAT_ID,
        "text": message
    }

    try:
        requests.get(url, params=params, timeout=5)
        print("📩 Telegram alert sent")
    except Exception as e:
        print(f"❌ Telegram error: {e}")


def get_request_token():
    # Setup Brave Browser
    options = webdriver.ChromeOptions()
    options.binary_location = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
    #options.add_argument("--start-maximized")
    options.add_argument("--headless")  # Run in background
    options.add_argument("--disable-gpu")  # Optional for compatibility
    options.add_argument("--no-sandbox")  # Optional for Linux
    options.add_argument("--window-size=1920,1080")  # Set standard size
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    success = False

    def save_debug_screenshot(stage):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = f"debug_{stage}_{timestamp}.png"
        try:
            driver.save_screenshot(path)
            print(f"📸 Saved debug screenshot: {path}")
        except Exception as screenshot_error:
            print(f"⚠️ Could not save screenshot: {screenshot_error}")

    def click_with_retry(locator, step_name, attempts=3, timeout=15):
        last_error = None
        for attempt in range(1, attempts + 1):
            try:
                wait = WebDriverWait(driver, timeout)
                element = wait.until(EC.element_to_be_clickable(locator))
                driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                time.sleep(0.3)
                try:
                    element.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", element)
                print(f"✅ {step_name} clicked (attempt {attempt}).")
                return element
            except Exception as e:
                last_error = e
                print(f"⚠️ {step_name} click attempt {attempt} failed: {e}")
                time.sleep(1)
        raise last_error

    try:
        login_url = f"https://kite.zerodha.com/"
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
        time.sleep(2)

        driver.get("https://console.zerodha.com/account/segment-activation")
        time.sleep(2)
    
        # clicking on nse equity
        try:
            wait = WebDriverWait(driver, 10)
            segment_element = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//label[@for='NSE_EQ']"
            )))
            segment_element.click()
            print("✅ Segment clicked successfully.")
            time.sleep(1)
        except Exception as e:
            print("❌ Error clicking segment:")
            print(f"Exception: {e}")
            return None
        
        # click on bse equity
        try:
            wait = WebDriverWait(driver, 10)
            segment_element = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//label[@for='BSE_EQ']"
            )))
            segment_element.click()
            print("✅ Segment clicked successfully.")
            time.sleep(1)
        except Exception as e:
            print("❌ Error clicking segment:")
            print(f"Exception: {e}")
            return None



        # click on nse fno
        try:
            wait = WebDriverWait(driver, 10)
            segment_element = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//label[@for='NSE_FO']"
            )))
            segment_element.click()
            print("✅ Segment clicked successfully.")
            time.sleep(1)
        except Exception as e:
            print("❌ Error clicking segment:")
            print(f"Exception: {e}")
            return None
        # click on bse fno
        try:
            wait = WebDriverWait(driver, 10)
            segment_element = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//label[@for='BSE_FO']"
            )))
            segment_element.click()
            print("✅ Segment clicked successfully.")
            time.sleep(1)
        except Exception as e:
            print("❌ Error clicking segment:")
            print(f"Exception: {e}")
            return None
        
        # click on nse commodity
        try:
            wait = WebDriverWait(driver, 10)
            segment_element = wait.until(EC.element_to_be_clickable((
                By.XPATH, "//label[@for='NSE_COM']"
            )))
            segment_element.click()
            print("✅ Segment clicked successfully.")
            time.sleep(1)
        except Exception as e:
            print("❌ Error clicking segment:")
            print(f"Exception: {e}")
            return None


        # Clicking on continue
        try:
            continue_btn = click_with_retry((
                By.XPATH, "//button[@class='btn btn-blue' and contains(text(), 'Continue')]"
            ),  "Continue", timeout=20)

            # Ensure transition to confirm stage before trying to click confirm.
            wait = WebDriverWait(driver, 15)
            try:
                wait.until(EC.staleness_of(continue_btn))
            except TimeoutException:
                # Some flows keep the same modal/button node and update in-place.
                print("ℹ️ Confirm modal opened in-place; proceeding to final submit.")
        except Exception as e:
            print("❌ Failed to click Continue button:")
            print(f"Exception: {e}")
            save_debug_screenshot("continue_error")
            return None

        # Clicking on confirm-page continue button
        try:
            confirm_btn = click_with_retry((
                By.XPATH, "//button[@type='submit' and @class='btn btn-blue']"
            ), "Confirm", timeout=20)

            # Wait for post-submit state change instead of fixed sleep.
            wait = WebDriverWait(driver, 20)
            try:
                wait.until(EC.staleness_of(confirm_btn))
            except TimeoutException:
                wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            success = True
        except Exception as e:
            print("❌ Failed to click Confirm button:")
            print(f"Exception: {e}")
            save_debug_screenshot("confirm_error")
            return None
        

    except Exception as e:
        print(f"❌ Error during login: {e}")
        save_debug_screenshot("login_error")
        return None

    finally:
        if success:
            os.system('say "Account Closed Successfully"')
            send_telegram("✅ Account Closed Successfully")
        else:
            os.system('say "Account Closure Failed"')
            send_telegram("❌ Account Closure Failed")
        driver.quit()

# Run the flow
if __name__ == "__main__":
    get_request_token()
