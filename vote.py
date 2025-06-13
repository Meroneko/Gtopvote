import time
import requests
import random
import string
import yaml
import os
from seleniumwire import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoSuchElementException, TimeoutException, WebDriverException
)
from loguru import logger

# ============ 配置加载 ============
def load_config(config_path="config.yml"):
    """加载配置文件"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件 {config_path} 不存在")
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    return config

# 加载配置
config = load_config()

# ============ 日志配置 ============
logger.add(
    "vote_log_{time}.log", 
    rotation=config['logging']['rotation'], 
    retention=config['logging']['retention'], 
    level=config['logging']['level'], 
    encoding=config['logging']['encoding']
)

# ============ 从配置文件获取参数 ============
# 2captcha账号API KEY
API_KEY = config['captcha']['api_key']

# Bright Data 代理配置
PROXY_HOST = config['proxy']['host']
PROXY_PORT = config['proxy']['port']
PROXY_USER = config['proxy']['user']
PROXY_PASS = config['proxy']['password']

# 要投票的账号列表
USERNAMES = config['accounts']

# 投票URL模板
BASE_VOTE_URL = config['voting']['base_url']
POST_VOTE_URL = config['voting']['post_url']

# 浏览器配置
USER_AGENTS = config['browser']['user_agents']
WINDOW_SIZE_CONFIG = config['browser']['window_size']

# 执行配置
MAX_ROUNDS = config['execution']['max_rounds']
DELAY_CONFIG = config['execution']['delay_between_accounts']
VOTING_DELAY_CONFIG = config['execution']['voting_behavior_delay']

# ============= Selenium代理封装 =============
def get_chrome_driver(session_id):
    random_user_agent = random.choice(USER_AGENTS)
    width = random.randint(WINDOW_SIZE_CONFIG['width_min'], WINDOW_SIZE_CONFIG['width_max'])
    height = random.randint(WINDOW_SIZE_CONFIG['height_min'], WINDOW_SIZE_CONFIG['height_max'])

    chrome_options = Options()
    # chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument(f"--window-size={width},{height}")
    chrome_options.add_argument(f'user-agent={random_user_agent}')

    proxy_user_with_session = f"{PROXY_USER}-session-{session_id}"
    logger.info(f"使用代理 (强制轮换IP): {proxy_user_with_session}")
    logger.info(f"使用User-Agent: {random_user_agent}")
    logger.info(f"使用窗口大小: {width}x{height}")

    seleniumwire_options = {
        'proxy': {
            'http': f'http://{proxy_user_with_session}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}',
            'https': f'https://{proxy_user_with_session}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}',
            'no_proxy': 'localhost,127.0.0.1'
        }
    }
    return webdriver.Chrome(options=chrome_options, seleniumwire_options=seleniumwire_options)

# ============= 等待与操作工具 =============
def wait_for_element(driver, by, value, timeout=20):
    wait = WebDriverWait(driver, timeout)
    return wait.until(EC.presence_of_element_located((by, value)))

# ============= ArkoseLabs FunCaptcha 自动解码 =============
def solve_funcaptcha(site_key, url):
    logger.info("正在向2captcha请求解ArkoseLabs FunCaptcha")
    s = requests.Session()
    req = s.post("http://2captcha.com/in.php", data={
        "key": API_KEY, "method": "funcaptcha", "publickey": site_key,
        "pageurl": url, "json": 1
    }).json()
    if req.get("status") != 1:
        logger.error(f"2captcha下单失败: {req}")
        return None
    
    task_id = req.get("request")
    for _ in range(60):
        time.sleep(5)
        res = s.get(f"http://2captcha.com/res.php?key={API_KEY}&action=get&id={task_id}&json=1").json()
        if res["status"] == 1:
            logger.success("FunCaptcha解码成功")
            return res["request"]
        elif res["request"] != "CAPCHA_NOT_READY":
            logger.error(f"2captcha识别失败: {res}")
            return None
    logger.warning("2captcha 超时未返回结果")
    return None

# ============= 单次投票执行函数 =============
def perform_vote(username):
    session_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    driver = None
    response = None  # 新增response变量，便于finally块使用
    try:
        driver = get_chrome_driver(session_id)
        VOTE_URL = BASE_VOTE_URL.format(username=username)

        logger.info("正在加载投票页面……")
        driver.get(VOTE_URL)

        logger.info("等待页面加载并从JS变量提取fingerprint...")
        fingerprint = None
        for _ in range(15):
            fingerprint = driver.execute_script("return window.murmur;")
            if fingerprint:
                logger.info(f"提取到fingerprint: {fingerprint}")
                break
            time.sleep(1)
        if not fingerprint:
            raise Exception("无法从JS变量`window.murmur`获取fingerprint")

        wait_time = random.uniform(VOTING_DELAY_CONFIG['min'], VOTING_DELAY_CONFIG['max'])
        logger.info(f"等待 {wait_time:.1f} 秒，模拟真实投票行为")
        time.sleep(wait_time)

        logger.info("查找投票按钮")
        vote_btn = wait_for_element(driver, By.ID, "votebutton", timeout=15)
        vote_btn.click()
        logger.info("点击按钮，准备弹出验证窗口")
        time.sleep(2)

        logger.info("等待FunCaptcha ArkoseLabs弹窗…")
        site_key, refresh_count = None, 0
        while refresh_count < 3:
            click_count, found = 0, False
            while click_count < 3:
                time.sleep(5)
                iframes = driver.find_elements(By.TAG_NAME, "iframe")
                for f in iframes:
                    try:
                        src = f.get_attribute('src')
                        if src and ("arkoselabs" in src or "funcaptcha" in src):
                            m = re.search(r'pk=([0-9A-Fa-f-]+)|#([0-9A-Fa-f-]+)', src)
                            if m:
                                site_key = m.group(1) or m.group(2)
                                driver.switch_to.default_content()
                                driver.switch_to.frame(f)
                                found = True
                                break
                    except WebDriverException: continue
                if found: break
                click_count += 1
                if click_count < 3:
                    logger.warning(f"未检测到FunCaptcha弹窗，尝试再次点击投票按钮（第{click_count + 1}次）")
                    try:
                        driver.switch_to.default_content()
                        wait_for_element(driver, By.ID, "votebutton", timeout=5).click()
                    except Exception as e:
                        logger.error(f"再次点击投票按钮失败: {e}")
                        break
            if found: break
            refresh_count += 1
            if refresh_count < 3:
                logger.warning(f"3次点击后仍未检测到弹窗，刷新页面重试（第{refresh_count + 1}次）")
                driver.refresh()
                time.sleep(5)
                try: wait_for_element(driver, By.ID, "votebutton", timeout=10).click()
                except Exception as e: logger.error(f"刷新后点击投票按钮失败: {e}")
        
        if not site_key: raise Exception("多次重试后仍未找到FunCaptcha iframe或sitekey")
        logger.success(f"检测到FunCaptcha sitekey: {site_key}")
        
        token = solve_funcaptcha(site_key, VOTE_URL)
        if not token: raise Exception("获取2captcha token失败")

        logger.info("构造最终投票请求...")
        site_id_match = re.search(r'MapleSchool-(\d+)', VOTE_URL)
        site_id = site_id_match.group(1) if site_id_match else ''
        timezone = driver.execute_script("return Intl.DateTimeFormat().resolvedOptions().timeZone")

        vote_payload = {
            'site': site_id, 'user_id': '', 'fingerprintid': fingerprint,
            'pingUsername': username, 'minecraftname': 'undefined', 'fcToken': token,
            'asf': '', 'tz': timezone, 'reToken': 'undefined'
        }

        logger.info("发送最终投票POST请求...")
        proxy_user_with_session = f"{PROXY_USER}-session-{session_id}"
        proxies = {
            'http': f'http://{proxy_user_with_session}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}',
            'https': f'https://{proxy_user_with_session}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}',
        }
        s = requests.Session()
        for cookie in driver.get_cookies():
            s.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
        headers = {
            'User-Agent': driver.execute_script("return navigator.userAgent;"),
            'Accept': '*/*', 'X-Requested-With': 'XMLHttpRequest',
            'Origin': 'https://gtop100.com', 'Referer': VOTE_URL
        }
        try:
            response = s.post(POST_VOTE_URL, data=vote_payload, headers=headers, proxies=proxies)
            logger.info(f"服务器响应状态码: {response.status_code}")
            logger.info(f"服务器响应内容: {response.text}")
        except requests.exceptions.RequestException as req_e:
            logger.error(f"投票POST请求异常: {req_e}")
            if response is not None:
                logger.error(f"异常时服务器响应状态码: {response.status_code}")
                logger.error(f"异常时服务器响应内容: {response.text}")
            else:
                logger.error("异常时无response对象可用")
            return False, str(req_e)
        if response is not None:
            if ("Thank you for voting!" in response.text or 
                "You have already voted" in response.text or 
                response.text.strip().lower() == 'success'):
                return True, response.text
            else:
                logger.warning("[!] 投票失败，未找到成功标识。")
                return False, response.text
        else:
            logger.error("未获取到服务器response对象")
            return False, "no response object"
    except Exception as e:
        logger.error(f"为账号 {username} 投票时出现未处理的异常: {e}")
        if response is not None:
            logger.error(f"异常时服务器响应状态码: {response.status_code}")
            logger.error(f"异常时服务器响应内容: {response.text}")
        return False, str(e)
    finally:
        if driver:
            driver.quit()

# ============= 主循环 =============
def main():
    successful_accounts = []
    accounts_to_process = USERNAMES[:]
    final_failed_accounts = []

    logger.info(f"开始为 {len(USERNAMES)} 个账号执行投票任务...")

    for attempt in range(1, MAX_ROUNDS + 1):  # 使用配置的最大轮数
        if not accounts_to_process:
            logger.info("所有账号均已处理完毕，提前结束任务。")
            break

        logger.info(f"========== 开始第 {attempt}/{MAX_ROUNDS} 轮投票尝试 ==========")
        failed_this_round = []
        
        for i, username in enumerate(accounts_to_process):
            logger.info(f"--- (第 {attempt} 轮) 开始为账号: {username} ---")
            
            # 执行单次投票
            success, response_text = perform_vote(username)
            if success:
                successful_accounts.append(username)
                logger.success(f"--- 账号: {username} 投票成功 -- 响应: {response_text.strip()} ---")
            else:
                failed_this_round.append(username)
                logger.error(f"--- 账号: {username} 投票失败，将在下一轮重试 ---")
            
            # 账号之间的随机延时
            if i < len(accounts_to_process) - 1:
                delay = random.randint(DELAY_CONFIG['min'], DELAY_CONFIG['max'])
                logger.info(f"随机等待 {delay} 秒后继续下一个账号...")
                time.sleep(delay)
        
        # 将本轮失败的账号作为下一轮的处理目标
        accounts_to_process = failed_this_round
        
        if accounts_to_process:
             logger.warning(f"第 {attempt} 轮投票后，有 {len(accounts_to_process)} 个账号失败，准备进入下一轮重试...")
        
    final_failed_accounts = accounts_to_process  # 经过3轮后仍然失败的账号

    logger.info("========== 投票任务完成 ==========")
    logger.success(f"成功账号 ({len(successful_accounts)}): {', '.join(successful_accounts) if successful_accounts else '无'}")
    if final_failed_accounts:
        logger.error(f"最终失败账号 (已重试{MAX_ROUNDS}次) ({len(final_failed_accounts)}): {', '.join(final_failed_accounts)}")
    logger.info("==================================")

if __name__ == "__main__":
    import re
    main()
