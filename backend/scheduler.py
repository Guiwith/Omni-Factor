from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from playwright.sync_api import sync_playwright
import sqlite3
from datetime import datetime, timedelta
import multiprocessing
from apscheduler.triggers.interval import IntervalTrigger
import asyncio
from playwright.async_api import async_playwright
from concurrent.futures import ThreadPoolExecutor
import sys
import hashlib
import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
from bs4 import NavigableString

class ScraperScheduler:
    def __init__(self):
        self.scheduler = BackgroundScheduler(
            executors={'default': {'type': 'threadpool', 'max_workers': 1}},
            job_defaults={'coalesce': False, 'max_instances': 1},
            timezone='Asia/Shanghai'
        )
        self.base_prompt = """你是一个专业的内容分析助手。请对以下内容进行分析和总结：
1. 只提取与要求相关信息，忽略html标签
2. 保持原文的重要数据和数字
3. 使用清晰的结构化格式输出
4. 如果有文字对应链接请在文字后面添加链接
5. 对于所有链接：
   - 保持完整的URL，包含域名
   - 自动补充相对路径的域名
   - 确保所有链接都是可直接点击的完整URL
6. 只总结与要求主题相关的内容"""
        
        self.init_database()
        self.start()

    def init_database(self):
        conn = sqlite3.connect('scraper.db')
        c = conn.cursor()
        
        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     url TEXT NOT NULL,
                     selector TEXT NOT NULL,
                     schedule TEXT NOT NULL, 
                     active INTEGER DEFAULT 1)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS results
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     task_id INTEGER,
                     content TEXT,
                     content_hash TEXT,
                     summary TEXT,
                     timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                     is_new BOOLEAN DEFAULT 1,
                     FOREIGN KEY (task_id) REFERENCES tasks (id))''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS prompts
                    (task_id INTEGER PRIMARY KEY,
                     custom_prompt TEXT,
                     FOREIGN KEY (task_id) REFERENCES tasks (id))''')
        
        conn.commit()
        conn.close()

    def add_task(self, task_id, url, selector, schedule):
        schedule_data = json.loads(schedule)
        day_mapping = {0: 6, 1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 6: 5}
        cron_days = [str(day_mapping[day]) for day in schedule_data['days']]
        
        job_id = f'task_{task_id}'
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
        
        self.scheduler.add_job(
            self.scrape_task,
            'cron',
            day_of_week=','.join(cron_days),
            hour=schedule_data['hour'],
            minute=schedule_data['minute'],
            id=job_id,
            args=[task_id, url, selector],
            replace_existing=True
        )
        
        # 立即执行一次
        self.scrape_task(task_id, url, selector)

    def remove_task(self, task_id):
        job_id = f'task_{task_id}'
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)

    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()

    def set_custom_prompt(self, task_id, custom_prompt):
        conn = sqlite3.connect('scraper.db')
        c = conn.cursor()
        c.execute('INSERT OR REPLACE INTO prompts (task_id, custom_prompt) VALUES (?, ?)',
                 (task_id, custom_prompt))
        conn.commit()
        conn.close()

    def get_custom_prompt(self, task_id):
        conn = sqlite3.connect('scraper.db')
        c = conn.cursor()
        c.execute('SELECT custom_prompt FROM prompts WHERE task_id = ?', (task_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else ""

    async def generate_summary(self, task_id, content):
        custom_prompt = self.get_custom_prompt(task_id)
        soup = BeautifulSoup(content, 'html.parser')
        
        # 处理链接和文本
        processed_content = []
        for element in soup.descendants:
            if element.name == 'a':
                href = element.get('href', '')
                text = element.get_text(strip=True)
                if href and text:
                    if href.startswith(('/', './')):
                        conn = sqlite3.connect('scraper.db')
                        c = conn.cursor()
                        c.execute('SELECT url FROM tasks WHERE id = ?', (task_id,))
                        task_url = c.fetchone()[0]
                        conn.close()
                        base_url = f"{urlparse(task_url).scheme}://{urlparse(task_url).netloc}"
                        href = urljoin(base_url, href)
                    processed_content.append(f'<a href="{href}">{text}</a>')
            elif element.string and element.string.strip():
                if element.parent.name != 'a':
                    processed_content.append(element.string.strip())
        
        content_text = '\n'.join(processed_content)
        final_prompt = f"{custom_prompt}\n\n{self.base_prompt}\n\n{content_text}"

        response = requests.post(
            'http://172.31.118.255:11434/api/generate',
            json={'model': 'glm4:latest', 'prompt': final_prompt, 'stream': False}
        )
        
        if response.status_code == 200:
            return response.json().get('response', '')
        return None

    def scrape_task(self, task_id, url, selector):
        if sys.platform == 'win32':
            loop = asyncio.ProactorEventLoop()
        else:
            loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(self._scrape_task_async(task_id, url, selector))
        finally:
            loop.close()

    async def _scrape_task_async(self, task_id, url, selector):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            )
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until='domcontentloaded')
                await page.wait_for_load_state('networkidle')
                
                element = page.locator(selector)
                await element.wait_for(state='attached')
                content = await element.inner_html()
                
                if not content.strip():
                    raise ValueError("Empty content")
                
                conn = sqlite3.connect('scraper.db')
                c = conn.cursor()
                
                content_hash = hash(content)
                c.execute('SELECT content_hash FROM results WHERE task_id = ? ORDER BY timestamp DESC LIMIT 1',
                         (task_id,))
                last_result = c.fetchone()
                
                if not last_result or last_result[0] != content_hash:
                    summary = await self.generate_summary(task_id, content)
                    c.execute('UPDATE results SET is_new = 0 WHERE task_id = ?', (task_id,))
                    c.execute('''INSERT INTO results (task_id, content, content_hash, summary, is_new)
                                VALUES (?, ?, ?, ?, 1)''', (task_id, content, content_hash, summary))
                    conn.commit()
                
                conn.close()
                
            except Exception as e:
                conn = sqlite3.connect('scraper.db')
                c = conn.cursor()
                c.execute('''INSERT INTO results (task_id, content, is_new)
                            VALUES (?, ?, 1)''', (task_id, str(e)))
                conn.commit()
                conn.close()
            
            finally:
                await browser.close()

    # 添加新方法用于获取任务结果
    def get_task_results(self, task_id, only_new=False):
        try:
            conn = sqlite3.connect('scraper.db')
            c = conn.cursor()
            
            if only_new:
                c.execute('''SELECT content, summary, timestamp 
                            FROM results 
                            WHERE task_id = ? AND is_new = 1
                            ORDER BY timestamp DESC''', (task_id,))
            else:
                c.execute('''SELECT content, summary, timestamp 
                            FROM results 
                            WHERE task_id = ?
                            ORDER BY timestamp DESC''', (task_id,))
            
            results = c.fetchall()
            conn.close()
            return results
        except Exception as e:
            print(f"获取任务结果失败: {str(e)}")
            return []
