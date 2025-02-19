from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import asyncio
from playwright.sync_api import sync_playwright
import json
import sqlite3
from datetime import datetime
from .scheduler import ScraperScheduler
import subprocess
import sys
import os
import time
from fastapi.responses import Response

app = FastAPI()
scheduler = ScraperScheduler()

# 允许跨域请求
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeConfig(BaseModel):
    url: str
    selector: str
    schedule: dict  # 修改为schedule字段，包含days和time
    custom_prompt: str = ""  # 添加自定义提示词字段，默认为空字符串

class TaskResult(BaseModel):
    id: int
    content: str
    timestamp: str

# 存储爬虫配置
scrape_configs = []

def write_selector_info(data):
    max_retries = 3
    for i in range(max_retries):
        try:
            with open('selector_info.json', 'w', encoding='utf-8') as f:
                json.dump(data, f)
            return True
        except Exception as e:
            if i == max_retries - 1:
                print(f"写入失败: {str(e)}")
                return False
            time.sleep(0.5)

def read_selector_info():
    max_retries = 3
    for i in range(max_retries):
        try:
            with open('selector_info.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
            try:
                os.remove('selector_info.json')
            except:
                pass
            return data
        except FileNotFoundError:
            return None
        except Exception as e:
            if i == max_retries - 1:
                print(f"读取失败: {str(e)}")
                return None
            time.sleep(0.5)

@app.post("/add_scrape_task")
async def add_scrape_task(config: ScrapeConfig):
    conn = sqlite3.connect('scraper.db')
    c = conn.cursor()
    try:
        # 添加任务
        c.execute('''
            INSERT INTO tasks (url, selector, schedule, active)
            VALUES (?, ?, ?, 1)
        ''', (config.url, config.selector, json.dumps(config.schedule)))
        task_id = c.lastrowid
        
        # 如果有自定义提示词，保存到 prompts 表
        if config.custom_prompt:
            c.execute('''
                INSERT INTO prompts (task_id, custom_prompt)
                VALUES (?, ?)
            ''', (task_id, config.custom_prompt))
        
        conn.commit()
        
        # 添加到调度器
        scheduler.add_task(task_id, config.url, config.selector, json.dumps(config.schedule))
        # 设置自定义提示词
        if config.custom_prompt:
            scheduler.set_custom_prompt(task_id, config.custom_prompt)
            
        return {"status": "success", "task_id": task_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.get("/tasks")
async def get_tasks():
    conn = sqlite3.connect('scraper.db')
    c = conn.cursor()
    try:
        c.execute('SELECT id, url, selector, schedule, active FROM tasks')
        tasks = []
        for row in c.fetchall():
            tasks.append({
                "id": row[0],
                "url": row[1],
                "selector": row[2],
                "schedule": row[3],  # 这里已经是JSON字符串
                "active": bool(row[4])
            })
        return tasks  # 直接返回任务列表数组
    except Exception as e:
        print(f"获取任务列表失败: {str(e)}")
        return []  # 出错时返回空数组
    finally:
        conn.close()

@app.get("/task_results/{task_id}")
async def get_task_results(task_id: int):
    conn = sqlite3.connect('scraper.db')
    c = conn.cursor()
    c.execute('''
        SELECT id, content, timestamp 
        FROM results 
        WHERE task_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 10
    ''', (task_id,))
    results = [{"id": row[0], "content": row[1], "timestamp": row[2]} 
               for row in c.fetchall()]
    conn.close()
    return results

@app.delete("/task/{task_id}")
async def delete_task(task_id: int):
    conn = sqlite3.connect('scraper.db')
    c = conn.cursor()
    
    try:
        # 从数据库中完全删除任务
        c.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        # 同时删除相关的结果
        c.execute('DELETE FROM results WHERE task_id = ?', (task_id,))
        conn.commit()
        
        # 尝试从调度器中移除任务
        try:
            scheduler.remove_task(task_id)
        except Exception as e:
            print(f"移除调度任务时出错: {str(e)}")
            # 继续执行，不影响整体流程
            
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

@app.get("/preview_selector")
def preview_selector(url: str):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "selector_script.py")
    selector_file = os.path.join(current_dir, "selector_info.json")

    # 确保开始时没有遗留的文件
    try:
        os.remove(selector_file)
    except:
        pass

    # 使用固定的脚本文件
    subprocess.Popen([sys.executable, script_path, url, selector_file])
    return {"status": "success"}

@app.get("/get_selector")
async def get_selector():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    selector_file = os.path.join(current_dir, "selector_info.json")
    
    try:
        if os.path.exists(selector_file):
            try:
                # 尝试以独占模式打开文件
                with open(selector_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print("读取到选择器数据:", data)
                
                # 等待一小段时间确保文件被完全释放
                time.sleep(0.1)
                
                # 多次尝试删除文件
                for _ in range(3):
                    try:
                        os.remove(selector_file)
                        print("成功删除文件")
                        break
                    except Exception as e:
                        print(f"尝试删除文件失败: {e}")
                        time.sleep(0.1)  # 等待一下再试
                
                return {"status": "success", "data": data}
            except Exception as e:
                print(f"文件操作错误: {e}")
                return {"status": "error", "message": str(e)}
        else:
            return {"status": "waiting"}
            
    except Exception as e:
        print(f"其他错误: {e}")
        return {"status": "error", "message": str(e)}

@app.put("/task/{task_id}/toggle")
async def toggle_task(task_id: int):
    conn = sqlite3.connect('scraper.db')
    c = conn.cursor()
    try:
        # 获取当前状态
        c.execute('SELECT active, url, selector, schedule FROM tasks WHERE id = ?', (task_id,))
        result = c.fetchone()
        if not result:
            return {"status": "error", "message": "任务不存在"}
            
        current_active, url, selector, schedule = result
        new_active = not current_active
        
        # 更新数据库状态
        c.execute('UPDATE tasks SET active = ? WHERE id = ?', (int(new_active), task_id))
        conn.commit()
        
        # 同步调度器状态
        if new_active:
            scheduler.add_task(task_id, url, selector, json.dumps(schedule))
        else:
            scheduler.remove_task(task_id)
            
        return {"status": "success", "active": new_active}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        conn.close()

# 在应用启动时启动调度器
@app.on_event("startup")
async def startup_event():
    scheduler.start()

@app.put('/api/tasks/{task_id}/mark_read')
def mark_results_as_read(task_id: int):
    try:
        conn = sqlite3.connect('scraper.db')
        c = conn.cursor()
        
        # 将所有未读结果标记为已读
        c.execute('''UPDATE results 
                    SET is_new = 0 
                    WHERE task_id = ? AND is_new = 1''', (task_id,))
        
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        print(f"更新阅读状态失败: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.get('/api/tasks/{task_id}/results')
def get_task_results(task_id: int):
    try:
        conn = sqlite3.connect('scraper.db')
        c = conn.cursor()
        
        c.execute('''SELECT summary, timestamp, is_new 
                    FROM results 
                    WHERE task_id = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 10''', (task_id,))
        
        results = c.fetchall()
        conn.close()
        
        if results:
            return [{
                'summary': result[0], 
                'timestamp': result[1],
                'is_new': bool(result[2])
            } for result in results]
        else:
            return []
            
    except Exception as e:
        print(f"获取任务结果失败: {str(e)}")
        return {"error": "获取结果失败"}, 500

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)  # 返回"无内容"状态码

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
