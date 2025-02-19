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
        # 配置线程池执行器
        executors = {
            'default': {'type': 'threadpool', 'max_workers': 1}
        }
        job_defaults = {
            'coalesce': False,
            'max_instances': 1
        }
        
        # 使用进程安全的调度器
        self.scheduler = BackgroundScheduler(
            executors=executors,
            job_defaults=job_defaults,
            timezone='Asia/Shanghai'
        )
        self.start()  # 在初始化时就启动调度器
        print("调度器已初始化并启动")
        self.base_prompt = """你是一个专业的内容分析助手。请对以下内容进行分析和总结：
1. 只提取与要求相关信息,如果内容出现html标签，请忽略，只提取文字部分
2. 保持原文的重要数据和数字
3. 使用清晰的结构化格式输出
4. 如果有文字对应链接请在文字后面添加链接
5. 对于所有链接：
   - 必须保持完整的URL，包含域名（如 https://www.ndrc.gov.cn）
   - 如果遇到相对路径（以 ./ 或 / 开头的链接），请自动补充域名
   - 确保所有链接都是可直接点击的完整URL
   示例：
   正确：<a href="https://www.ndrc.gov.cn/xxgk/zcfb/tz/202502/t20250214_1396164.html">关于开展物流数据开放互联试点工作的通知</a>
   错误：[https://www.ndrc.gov.cn/xxgk/zcfb/tz/202502/t20250214_1396164.html](https://www.ndrc.gov.cn/xxgk/zcfb/tz/202502/t20250214_1396164.html)
6. 表格中的链接格式：
   | 标题 | 日期 |
   | ---- | ---- |
   | <a href="完整URL">文章标题</a> | 发布日期 |
7. 只给出清晰的结构化格式输出
8. 只总结与要求主题相关的内容:
   — 如果内容与要求主题无关，请直接返回"本次更新内容与要求主题无关"
   — 不要对无关内容进行总结
"""
        self.init_database()
        
    def init_database(self):
        conn = sqlite3.connect('scraper.db')
        c = conn.cursor()
        
        
        c.execute('''CREATE TABLE IF NOT EXISTS tasks
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     url TEXT NOT NULL,
                     selector TEXT NOT NULL,
                     schedule TEXT NOT NULL, 
                     active INTEGER DEFAULT 1)''')
        
        # 检查 results 表是否存在
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='results'")
        table_exists = c.fetchone() is not None
        
        if not table_exists:
            # 创建新表时包含 summary 字段
            c.execute('''CREATE TABLE results
                        (id INTEGER PRIMARY KEY AUTOINCREMENT,
                         task_id INTEGER,
                         content TEXT,
                         content_hash TEXT,
                         summary TEXT,
                         timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                         is_new BOOLEAN DEFAULT 1,
                         FOREIGN KEY (task_id) REFERENCES tasks (id))''')
        else:
            # 检查是否需要添加 summary 列
            c.execute("PRAGMA table_info(results)")
            columns = [column[1] for column in c.fetchall()]
            
            if 'summary' not in columns:
                c.execute('ALTER TABLE results ADD COLUMN summary TEXT')
        
        # 创建 prompts 表 (只存储自定义提示词)
        c.execute('''CREATE TABLE IF NOT EXISTS prompts
                    (task_id INTEGER PRIMARY KEY,
                     custom_prompt TEXT,
                     FOREIGN KEY (task_id) REFERENCES tasks (id))''')
        
        conn.commit()
        conn.close()
        print("数据库初始化完成")

    def scrape_task(self, task_id, url, selector):
        def run_async_task():
            # 在 Windows 上使用 ProactorEventLoop
            if sys.platform == 'win32':
                loop = asyncio.ProactorEventLoop()
            else:
                loop = asyncio.new_event_loop()
            
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(self.scrape_task_async(task_id, url, selector))
            finally:
                loop.close()

        # 在单独的线程中运行异步任务
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(run_async_task).result()

    def add_task(self, task_id, url, selector, schedule):
        try:
            job_id = f'task_{task_id}'
            print(f"\n{'='*50}")
            print(f"开始添加任务 {job_id}")
            print(f"URL: {url}")
            print(f"选择器: {selector}")
            print(f"调度计划: {schedule}")
            
            # 移除已存在的任务
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                print(f"已移除旧任务: {job_id}")
            
            # 解析调度计划
            schedule_data = json.loads(schedule)
            cron_days = []
            # 转换星期格式：0-6(周日-周六) -> 0-6(周一-周日)
            day_mapping = {
                0: 6,  # 周日 -> 6
                1: 0,  # 周一 -> 0
                2: 1,  # 周二 -> 1
                3: 2,  # 周三 -> 2
                4: 3,  # 周四 -> 3
                5: 4,  # 周五 -> 4
                6: 5   # 周六 -> 5
            }
            
            for day in schedule_data['days']:
                cron_days.append(str(day_mapping[day]))
            
            # 添加定时任务，使用cron触发器
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
            print(f"√ 已添加定时任务")
            
            # 立即执行一次爬虫任务
            print("立即执行一次爬虫任务...")
            self.scrape_task(task_id, url, selector)
            print("√ 首次爬取完成")
            
            # 打印任务状态
            jobs = self.scheduler.get_jobs()
            print(f"\n当前活动任务数量: {len(jobs)}")
            for job in jobs:
                try:
                    next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S') if job.next_run_time else "未安排"
                    print(f"- 任务ID: {job.id}")
                    print(f"- 下次执行时间: {next_run}")
                except AttributeError:
                    print(f"- 任务ID: {job.id}")
                    print("- 下次执行时间: 无法获取")
            
            print(f"\n{'='*50}")
            return True
            
        except Exception as e:
            error_msg = f"添加任务失败: {str(e)}"
            print(f"\n× {error_msg}")
            print(f"{'='*50}")
            return False

    def remove_task(self, task_id):
        job_id = f'task_{task_id}'
        if self.scheduler.get_job(job_id):
            self.scheduler.remove_job(job_id)
            print(f"已移除任务 {task_id}")

    def start(self):
        # 移除进程检查，确保调度器总是启动
        if not self.scheduler.running:
            self.scheduler.start()
            print("调度器已启动")
        else:
            print("调度器已在运行中")

    def set_custom_prompt(self, task_id, custom_prompt):
        try:
            conn = sqlite3.connect('scraper.db')
            c = conn.cursor()
            c.execute('''INSERT OR REPLACE INTO prompts (task_id, custom_prompt)
                        VALUES (?, ?)''', (task_id, custom_prompt))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"设置自定义prompt失败: {str(e)}")
            return False

    def get_custom_prompt(self, task_id):
        try:
            conn = sqlite3.connect('scraper.db')
            c = conn.cursor()
            c.execute('SELECT custom_prompt FROM prompts WHERE task_id = ?', (task_id,))
            result = c.fetchone()
            conn.close()
            return result[0] if result else ""
        except Exception as e:
            print(f"获取自定义prompt失败: {str(e)}")
            return ""

    async def generate_summary(self, task_id, content):
        try:
            # 获取自定义prompt
            custom_prompt = self.get_custom_prompt(task_id)
            
            # 处理HTML内容
            soup = BeautifulSoup(content, 'html.parser')
            
            # 移除script和style标签
            for element in soup(['script', 'style']):
                element.decompose()
            
            # 处理链接，同时移除其他HTML标签
            processed_content = []
            for element in soup.descendants:
                if element.name == 'a':
                    href = element.get('href', '')
                    text = element.get_text(strip=True)
                    if href and text:
                        # 处理相对路径
                        if href.startswith('/') or href.startswith('./'):
                            conn = sqlite3.connect('scraper.db')
                            c = conn.cursor()
                            c.execute('SELECT url FROM tasks WHERE id = ?', (task_id,))
                            task_url = c.fetchone()[0]
                            conn.close()
                            
                            base_url = f"{urlparse(task_url).scheme}://{urlparse(task_url).netloc}"
                            href = urljoin(base_url, href)
                        
                        processed_content.append(f'<a href="{href}">{text}</a>')
                elif isinstance(element, NavigableString) and element.strip():
                    # 只添加非空的文本内容
                    text = element.strip()
                    if text and element.parent.name != 'a':  # 避免重复添加链接文本
                        processed_content.append(text)
            
            # 将处理后的内容用换行符连接
            cleaned_content = '\n'.join(processed_content)
            
            # 移除多余的空行
            cleaned_content = '\n'.join(line for line in cleaned_content.splitlines() if line.strip())
            
            # 组合prompt
            final_prompt = f"###重要回答要求###：\n{custom_prompt if custom_prompt else '无'}\n\n{self.base_prompt}\n\n待分析总结内容：\n{cleaned_content}"
            
            print("\n" + "="*80)
            print("开始生成AI总结...")
            print("完整的提示词内容:")
            print("-"*80)
            print(final_prompt)
            print("-"*80)
            
            # 打印API请求详情
            api_request = {
                'model': 'glm4:latest',
                'prompt': final_prompt,
                'stream': False
            }
            print("\nAPI请求详情:")
            print("-"*80)
            print(json.dumps(api_request, ensure_ascii=False, indent=2))
            print("-"*80)
            
            # 调用Ollama API
            response = requests.post('http://172.31.118.255:11434/api/generate',
                                  json=api_request)
            
            if response.status_code == 200:
                summary = response.json().get('response', '')
                print("\nAI响应状态码:", response.status_code)
                print("\nAI总结结果:")
                print("-"*80)
                print(summary)
                print("-"*80)
                print("√ AI总结完成")
                print("="*80 + "\n")
                return summary
            else:
                raise Exception(f"Ollama API 调用失败: {response.status_code}")
                
        except Exception as e:
            print(f"生成总结失败: {str(e)}")
            print("="*80 + "\n")
            return None

    async def scrape_task_async(self, task_id, url, selector):
        try:
            print(f"\n{'='*50}")
            print(f"任务 {task_id} 开始执行")
            print(f"URL: {url}")
            print(f"选择器: {selector}")
            print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*50}\n")

            async with async_playwright() as p:
                try:
                    print("1. 启动浏览器...")
                    browser = await p.chromium.launch(headless=True)
                    context = await browser.new_context(
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                    )
                    page = await context.new_page()
                    print("√ 浏览器启动成功")
                    
                    print("\n2. 访问目标页面...")
                    try:
                        response = await page.goto(url)
                        if not response:
                            raise Exception("页面响应为空")
                        if response.status != 200:
                            raise Exception(f"HTTP状态码: {response.status}")
                        
                        print("等待页面加载完成...")
                        await page.wait_for_load_state('networkidle')
                        print(f"√ 页面加载成功 (状态码: {response.status})")
                    except Exception as e:
                        print(f"× 页面加载失败: {str(e)}")
                        raise
                    
                    print("\n3. 定位目标元素...")
                    try:
                        print(f"使用选择器: {selector}")
                        # 修改等待策略，不仅等待元素可见，也接受隐藏元素
                        element = page.locator(selector)
                        
                        # 首先尝试等待元素存在（不管是否可见）
                        await element.wait_for(state='attached', timeout=10000)
                        
                        print("获取元素内容...")
                        # 即使元素隐藏也获取内容
                        content = await element.inner_html()
                        
                        if not content.strip():
                            raise Exception("获取到的内容为空")
                            
                        # 计算内容的哈希值
                        content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
                        
                        # 检查是否存在相同内容
                        conn = sqlite3.connect('scraper.db')
                        c = conn.cursor()
                        
                        # 获取最近的记录
                        c.execute('''SELECT content_hash 
                                    FROM results 
                                    WHERE task_id = ? 
                                    ORDER BY timestamp DESC 
                                    LIMIT 1''', (task_id,))
                        last_result = c.fetchone()
                        
                        if last_result and last_result[0] == content_hash:
                            print("内容未发生变化，跳过更新")
                            c.execute('''UPDATE results 
                                       SET is_new = 0 
                                       WHERE task_id = ?''', (task_id,))
                            conn.commit()
                            conn.close()
                            return
                        
                        # 生成 AI 总结
                        summary = await self.generate_summary(task_id, content)
                        
                        # 更新旧记录状态
                        c.execute('''UPDATE results 
                                   SET is_new = 0 
                                   WHERE task_id = ?''', (task_id,))
                        
                        # 插入新记录，包含总结内容
                        c.execute('''INSERT INTO results 
                                   (task_id, content, content_hash, summary, is_new) 
                                   VALUES (?, ?, ?, ?, 1)''',
                                (task_id, content, content_hash, summary))
                        
                        conn.commit()
                        conn.close()
                        print("√ 新内容和AI总结已存储到数据库")
                        
                    except Exception as e:
                        error_msg = str(e)
                        if "hidden" in error_msg:
                            print("警告：元素处于隐藏状态，尝试强制获取内容...")
                            try:
                                # 使用 evaluate 直接获取元素内容，忽略可见性
                                content = await page.evaluate(f'''
                                    document.querySelector("{selector}")?.innerHTML || ""
                                ''')
                                
                                if not content.strip():
                                    raise Exception("获取到的内容为空")
                                    
                                print("√ 成功获取隐藏元素的内容")
                            except Exception as inner_e:
                                raise Exception(f"无法获取隐藏元素内容: {str(inner_e)}")
                        else:
                            raise Exception(f"元素操作失败: {error_msg}")
                    
                    print("\n4. 清理浏览器资源...")
                    await context.close()
                    await browser.close()
                    print("√ 浏览器资源已清理")
                    
                    print(f"\n{'='*50}")
                    print(f"任务 {task_id} 执行完成")
                    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"{'='*50}\n")
                    
                except Exception as browser_error:
                    error_msg = f"浏览器操作错误: {str(browser_error)}"
                    print(f"\n× {error_msg}")
                    raise
        
        except Exception as e:
            error_msg = f"""
爬取失败详情:
- 任务ID: {task_id}
- URL: {url}
- 选择器: {selector}
- 错误类型: {type(e).__name__}
- 错误信息: {str(e)}
- 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            print(f"\n{'='*50}")
            print(error_msg)
            print(f"{'='*50}\n")
            
            try:
                conn = sqlite3.connect('scraper.db')
                c = conn.cursor()
                # 错误信息不需要去重，直接存储
                c.execute('''INSERT INTO results 
                           (task_id, content, is_new) 
                           VALUES (?, ?, 1)''',
                        (task_id, error_msg))
                conn.commit()
                conn.close()
                print("√ 错误信息已记录到数据库")
            except Exception as db_error:
                print(f"× 错误信息存储失败: {str(db_error)}")

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
