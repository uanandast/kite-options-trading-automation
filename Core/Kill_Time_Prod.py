import time
from pathlib import Path
import pyotp
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
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

config_path = Path(__file__).parent.parent / "Cred" / "Cred_kite_PREM.ini"
config.read(config_path)

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
     # Setup Chrome for Lightsail
    options = webdriver.ChromeOptions()
    options.binary_location = "/usr/bin/google-chrome"
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")

    service = Service("/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)
    
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
        login_url = "https://console.zerodha.com/"
        driver.get(login_url)
        print(f"🌐 After opening login page: {driver.current_url}")

        # Click "Login with Kite"
        wait = WebDriverWait(driver, 20)
        login_kite_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Login with Kite')]") )
        )
        login_kite_btn.click()
        print(f"🌐 After clicking Login with Kite: {driver.current_url}")

        # Login step
        username = wait.until(EC.presence_of_element_located((By.ID, "userid")))
        username.send_keys(user_id)

        password_el = driver.find_element(By.ID, "password")
        password_el.send_keys(password)

        driver.find_element(By.XPATH, "//button[@type='submit']").click()
        time.sleep(1)
        driver.switch_to.default_content()
        print(f"🌐 After password submit: {driver.current_url}")

        time.sleep(2)
        # TOTP step (with retry to avoid stale element issues)
        for attempt in range(3):
            try:
                totp = pyotp.TOTP(totp_secret).now()
                print(f"✅ TOTP: {totp}")

                totp_input = wait.until(
                    EC.element_to_be_clickable((By.ID, "userid"))
                )

                totp_input.clear()
                totp_input.send_keys(totp)

                driver.find_element(By.XPATH, "//button[@type='submit']").click()
                time.sleep(2)
                print(f"🌐 After TOTP submit: {driver.current_url}")
                break

            except Exception as e:
                print(f"Retrying TOTP... {attempt+1}")
                time.sleep(2)

        time.sleep(2)

        # Wait for redirect back to console dashboard
        WebDriverWait(driver, 20).until(
            lambda d: "console.zerodha.com/dashboard" in d.current_url
        )
        print(f"✅ Logged in successfully, current URL: {driver.current_url}")
        send_telegram(f"✅ Logged in successfully, current URL: {driver.current_url}")

        # Directly navigate to segment activation page
        time.sleep(2)  # small buffer for session stabilization
        driver.get("https://console.zerodha.com/account/segment-activation")
        print(f"🌐 Navigated to segment page: {driver.current_url}")

        # Wait for segment page to load
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "form_segment_manage"))
        )
        print("✅ Segment page loaded successfully")
    
        # clicking on nse equity
        try:
            wait = WebDriverWait(driver, 20)
            segment_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "#form_segment_manage label")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", segment_element)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", segment_element)
            print("✅ NSE_EQ clicked successfully.")
        except Exception as e:
            print("❌ Error clicking NSE_EQ:")
            print(f"Exception: {e}")
            save_debug_screenshot("nse_eq_error")
            return None

        # click on bse equity
        try:
            segment_element = wait.until(EC.presence_of_element_located((By.XPATH, "//label[@for='BSE_EQ']")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", segment_element)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", segment_element)
            print("✅ BSE_EQ clicked successfully.")
        except Exception as e:
            print("❌ Error clicking BSE_EQ:")
            print(f"Exception: {e}")
            save_debug_screenshot("bse_eq_error")
            return None

        # click on nse fno
        try:
            segment_element = wait.until(EC.presence_of_element_located((By.XPATH, "//label[@for='NSE_FO']")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", segment_element)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", segment_element)
            print("✅ NSE_FO clicked successfully.")
        except Exception as e:
            print("❌ Error clicking NSE_FO:")
            print(f"Exception: {e}")
            save_debug_screenshot("nse_fo_error")
            return None

        # click on bse fno
        try:
            segment_element = wait.until(EC.presence_of_element_located((By.XPATH, "//label[@for='BSE_FO']")))
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", segment_element)
            time.sleep(1)
            driver.execute_script("arguments[0].click();", segment_element)
            print("✅ BSE_FO clicked successfully.")
        except Exception as e:
            print("❌ Error clicking BSE_FO:")
            print(f"Exception: {e}")
            save_debug_screenshot("bse_fo_error")
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
            print("✅ Account Closed Successfully")
            send_telegram("✅ Account Closed Successfully")
        else:
            print("❌ Account Closure Failed")
            send_telegram("❌ Account Closure Failed")
        driver.quit()

# Run the flow
if __name__ == "__main__":
    get_request_token()

