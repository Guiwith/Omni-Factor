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

def get_db():
    conn = sqlite3.connect('scraper.db')
    try:
        yield conn
    finally:
        conn.close()

@app.post("/add_scrape_task")
async def add_scrape_task(config: ScrapeConfig):
    with next(get_db()) as conn:
        c = conn.cursor()
        c.execute('''INSERT INTO tasks (url, selector, schedule, active)
                    VALUES (?, ?, ?, 1)''', 
                    (config.url, config.selector, json.dumps(config.schedule)))
        task_id = c.lastrowid
        
        if config.custom_prompt:
            c.execute('''INSERT INTO prompts (task_id, custom_prompt)
                        VALUES (?, ?)''', (task_id, config.custom_prompt))
            scheduler.set_custom_prompt(task_id, config.custom_prompt)
        
        conn.commit()
        scheduler.add_task(task_id, config.url, config.selector, json.dumps(config.schedule))
        return {"status": "success", "task_id": task_id}

@app.get("/tasks")
async def get_tasks():
    with next(get_db()) as conn:
        c = conn.cursor()
        c.execute('SELECT id, url, selector, schedule, active FROM tasks')
        return [{
            "id": row[0],
            "url": row[1],
            "selector": row[2],
            "schedule": row[3],
            "active": bool(row[4])
        } for row in c.fetchall()]

@app.get("/task_results/{task_id}")
async def get_task_results(task_id: int):
    with next(get_db()) as conn:
        c = conn.cursor()
        c.execute('''SELECT summary, timestamp, is_new 
                    FROM results 
                    WHERE task_id = ? 
                    ORDER BY timestamp DESC 
                    LIMIT 10''', (task_id,))
        return [{
            'summary': row[0], 
            'timestamp': row[1],
            'is_new': bool(row[2])
        } for row in c.fetchall()]

@app.delete("/task/{task_id}")
async def delete_task(task_id: int):
    with next(get_db()) as conn:
        c = conn.cursor()
        c.execute('DELETE FROM tasks WHERE id = ?', (task_id,))
        c.execute('DELETE FROM results WHERE task_id = ?', (task_id,))
        conn.commit()
        scheduler.remove_task(task_id)
        return {"status": "success"}

@app.get("/preview_selector")
def preview_selector(url: str):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "selector_script.py")
    selector_file = os.path.join(current_dir, "selector_info.json")
    
    try:
        os.remove(selector_file)
    except FileNotFoundError:
        pass
    
    subprocess.Popen([sys.executable, script_path, url, selector_file])
    return {"status": "success"}

@app.get("/get_selector")
async def get_selector():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    selector_file = os.path.join(current_dir, "selector_info.json")
    
    if not os.path.exists(selector_file):
        return {"status": "waiting"}
        
    try:
        with open(selector_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        os.remove(selector_file)
        return {"status": "success", "data": data}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.put("/task/{task_id}/toggle")
async def toggle_task(task_id: int):
    with next(get_db()) as conn:
        c = conn.cursor()
        c.execute('SELECT active, url, selector, schedule FROM tasks WHERE id = ?', (task_id,))
        result = c.fetchone()
        if not result:
            raise HTTPException(status_code=404, detail="Task not found")
            
        current_active, url, selector, schedule = result
        new_active = not current_active
        
        c.execute('UPDATE tasks SET active = ? WHERE id = ?', (int(new_active), task_id))
        conn.commit()
        
        if new_active:
            scheduler.add_task(task_id, url, selector, json.dumps(schedule))
        else:
            scheduler.remove_task(task_id)
            
        return {"status": "success", "active": new_active}

@app.put('/api/tasks/{task_id}/mark_read')
def mark_results_as_read(task_id: int):
    with next(get_db()) as conn:
        c = conn.cursor()
        c.execute('UPDATE results SET is_new = 0 WHERE task_id = ? AND is_new = 1', (task_id,))
        conn.commit()
        return {"status": "success"}

@app.on_event("startup")
async def startup_event():
    scheduler.start()

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)  # 返回"无内容"状态码

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
