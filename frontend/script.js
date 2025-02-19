'use strict';
// 使用 meta 标签设置 UTF-8 编码
if (!document.querySelector('meta[charset]')) {
    const meta = document.createElement('meta');
    meta.setAttribute('charset', 'UTF-8');
    document.head.appendChild(meta);
}

let currentSelector = '';
let pollingInterval = null;  // 用于存储轮询定时器

// 修改API基础URL
const API_BASE_URL = 'http://localhost:8000';  // 添加这个常量

// 添加消息监听器
window.addEventListener('message', function(event) {
    if (event.data.selector) {
        currentSelector = event.data.selector;
        const selectorDisplay = document.getElementById('selector-display');
        selectorDisplay.innerHTML = `选择器: ${event.data.selector}<br>预览内容: ${event.data.preview}`;
        console.log('收到选择器:', currentSelector); // 添加调试日志
    }
});

async function previewSelector() {
    const url = document.getElementById('url').value;
    if (!url) {
        alert('请输入网址');
        return;
    }
    
    if (pollingInterval) {
        clearInterval(pollingInterval);
    }
    
    document.getElementById('selector-display').textContent = '正在选择...';
    currentSelector = '';
    
    try {
        const response = await fetch(`${API_BASE_URL}/preview_selector?url=${encodeURIComponent(url)}`);
        if (!response.ok) {
            throw new Error('预览失败');
        }
        
        pollingInterval = setInterval(async () => {
            try {
                console.log('正在检查选择器...');  // 添加调试日志
                const selectorResponse = await fetch(`${API_BASE_URL}/get_selector`);
                const result = await selectorResponse.json();
                console.log('获取到的结果:', result);  // 添加调试日志
                
                if (result.status === 'success' && result.data) {
                    console.log('成功获取选择器:', result.data);  // 添加调试日志
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    
                    currentSelector = result.data.selector;
                    const selectorDisplay = document.getElementById('selector-display');
                    selectorDisplay.innerHTML = `选择器: ${result.data.selector}<br>预览内容: ${result.data.preview}`;
                    console.log('已更新显示');  // 添加调试日志
                }
            } catch (error) {
                console.error('轮询错误:', error);
            }
        }, 1000);
        
        // 60秒后停止轮询
        setTimeout(() => {
            if (pollingInterval) {
                console.log('轮询超时');  // 添加调试日志
                clearInterval(pollingInterval);
                pollingInterval = null;
                if (!currentSelector) {
                    document.getElementById('selector-display').textContent = '未选择';
                }
            }
        }, 60000);
        
    } catch (error) {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
        document.getElementById('selector-display').textContent = '未选择';
        alert('发生错误：' + error.message);
    }
}

async function addTask() {
    const url = document.getElementById('url').value;
    const selectorDisplay = document.getElementById('selector-display').textContent;
    const selector = selectorDisplay.replace('选择器:', '').split('预览内容:')[0].trim();
    const executionTime = document.getElementById('execution-time').value;
    const customPrompt = document.getElementById('custom-prompt').value;
    
    // 获取选中的星期
    const selectedDays = [];
    document.querySelectorAll('.weekday-selector input:checked').forEach(checkbox => {
        selectedDays.push(parseInt(checkbox.value));
    });
    
    if (!url || selector === '未选择' || !executionTime || selectedDays.length === 0) {
        alert('请填写完整信息并至少选择一天');
        return;
    }
    
    // 解析时间
    const [hour, minute] = executionTime.split(':');
    
    const schedule = {
        days: selectedDays,
        hour: parseInt(hour),
        minute: parseInt(minute)
    };

    try {
        const response = await fetch(`${API_BASE_URL}/add_scrape_task`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                url: url,
                selector: selector,
                schedule: schedule,
                custom_prompt: customPrompt
            }),
        });

        const result = await response.json();
        
        if (result.status === 'success') {
            document.getElementById('url').value = '';
            document.getElementById('selector-display').textContent = '未选择';
            document.getElementById('execution-time').value = '';
            document.getElementById('custom-prompt').value = '';
            
            await loadTasks();
            alert('任务添加成功');
        } else {
            alert('添加失败: ' + result.message);
        }
    } catch (error) {
        alert('添加失败: ' + error.message);
    }
}

async function updateTaskList() {
    try {
        const response = await fetch(`${API_BASE_URL}/tasks`);
        const tasks = await response.json();
        const taskList = document.getElementById('taskList');
        taskList.innerHTML = '';
        
        tasks.forEach(task => {
            const li = createTaskElement(task);
            taskList.appendChild(li);
        });
    } catch (error) {
        console.error('获取任务列表失败:', error);
    }
}

function createTaskElement(task) {
    const li = document.createElement('li');
    li.className = 'task-item';
    
    // 使用 textContent 而不是 innerHTML 来避免编码问题
    const taskUrl = document.createElement('div');
    taskUrl.className = 'task-url';
    taskUrl.title = task.url;
    taskUrl.textContent = truncateUrl(task.url);
    
    const schedule = JSON.parse(task.schedule);
    const days = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    const selectedDays = schedule.days.map(d => days[d]).join(', ');
    const time = `${String(schedule.hour).padStart(2, '0')}:${String(schedule.minute).padStart(2, '0')}`;
    
    const taskDetails = document.createElement('div');
    taskDetails.className = 'task-details';
    taskDetails.innerHTML = `
        <span class="schedule">执行时间: ${selectedDays} ${time}</span>
        <span class="separator">|</span>
        <span class="status ${task.active ? 'active' : 'inactive'}">
            ${task.active ? '监控中' : '已停止'}
        </span>
    `;
    
    const taskActions = document.createElement('div');
    taskActions.className = 'task-actions';
    taskActions.innerHTML = `
        <button onclick="viewResults(${task.id})" class="view-button">
            <span class="icon">📊</span>
            查看结果
        </button>
        <button onclick="toggleTask(${task.id}, ${!task.active})" 
                class="${task.active ? 'stop-button' : 'start-button'}">
            <span class="icon">${task.active ? '⏹️' : '▶️'}</span>
            ${task.active ? '停止' : '启动'}
        </button>
        <button onclick="deleteTask(${task.id})" class="delete-button">
            <span class="icon">🗑️</span>
            删除
        </button>
    `;
    
    li.appendChild(taskUrl);
    li.appendChild(taskDetails);
    li.appendChild(taskActions);
    
    return li;
}

async function viewResults(taskId) {
    try {
        const response = await fetch(`${API_BASE_URL}/api/tasks/${taskId}/results`);
        if (!response.ok) {
            throw new Error('获取结果失败');
        }
        const results = await response.json();
        
        const dialog = document.createElement('div');
        dialog.className = 'results-dialog';
        dialog.dataset.taskId = taskId; // 存储taskId用于关闭时更新
        
        const closeButton = document.createElement('button');
        closeButton.className = 'close-button';
        closeButton.innerHTML = '×';
        closeButton.onclick = async () => {
            // 在关闭前标记为已读
            try {
                await fetch(`${API_BASE_URL}/api/tasks/${taskId}/mark_read`, {
                    method: 'PUT'
                });
            } catch (error) {
                console.error('更新阅读状态失败:', error);
            }
            dialog.remove();
            overlay.remove();
        };
        
        const title = document.createElement('h2');
        title.textContent = '监控结果';
        
        const content = document.createElement('div');
        content.className = 'results-content';
        
        if (results.length === 0) {
            content.innerHTML = '<p class="no-results">暂无更新</p>';
        } else {
            content.innerHTML = results.map(result => {
                const isError = result.summary && result.summary.includes('爬取失败详情');
                const summaryClass = isError ? 'result-error' : 'result-summary';
                
                // 调整结构，将 readStatus 移到 result-time 后面
                return `
                    <div class="result-item ${result.is_new ? 'new-result' : 'read-result'}">
                        <div class="result-header">
                            <div class="result-time">${new Date(result.timestamp).toLocaleString()}</div>
                            ${result.is_new ? '' : '<div class="read-status">已阅读</div>'}
                        </div>
                        <div class="${summaryClass}">${result.summary}</div>
                    </div>
                `;
            }).join('');
        }
        
        dialog.appendChild(closeButton);
        dialog.appendChild(title);
        dialog.appendChild(content);
        
        document.body.appendChild(dialog);
        
        const overlay = document.createElement('div');
        overlay.className = 'overlay';
        overlay.onclick = closeButton.onclick; // 使用相同的关闭处理函数
        document.body.appendChild(overlay);
        
    } catch (error) {
        alert('获取结果失败: ' + error.message);
    }
}

// 格式化内容，保留换行和格式
function formatContent(content) {
    if (!content) return '无内容';
    return content
        .replace(/\n/g, '<br>')
        .replace(/【(.+?)】/g, '<strong>【$1】</strong>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>'); // 支持 markdown 加粗语法
}

async function deleteTask(taskId) {
    if (!confirm('确定要删除这个任务吗？')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/task/${taskId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            throw new Error('删除任务失败');
        }
        
        updateTaskList();
    } catch (error) {
        alert('删除失败：' + error.message);
    }
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', function() {
    document.getElementById('selector-display').textContent = '未选择';
    updateTaskList();

    // 更新错误消息和提示文本
    const messages = {
        urlRequired: '请输入网址',
        selectorRequired: '请先选择要爬取的元素',
        taskInfoRequired: '请填写完整的任务信息',
        taskAddSuccess: '任务添加成功',
        taskAddFailed: '任务添加失败',
        deleteConfirm: '确定要删除这个任务吗？',
        deleteFailed: '删除失败：',
        operationFailed: '操作失败: ',
        selecting: '正在选择...',
        notSelected: '未选择',
        previewFailed: '预览失败',
        noUpdates: '暂无更新'
    };

    // 使用这些消息替换原有的硬编码文本
    if (!url) {
        alert(messages.urlRequired);
        return;
    }
});

// 在页面卸载时清除轮询
window.addEventListener('beforeunload', () => {
    if (pollingInterval) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
});

// 加载任务列表
async function loadTasks() {
    try {
        const response = await fetch(`${API_BASE_URL}/tasks`);
        if (!response.ok) {
            throw new Error('获取任务列表失败');
        }
        const tasks = await response.json();
        
        // 添加调试信息
        console.log('获取到的任务数据:', tasks);
        
        // 确保tasks是数组
        if (!Array.isArray(tasks)) {
            console.error('任务数据不是数组:', tasks);
            throw new Error('服务器返回了无效的数据格式');
        }
        
        const taskList = document.getElementById('taskList');
        taskList.innerHTML = ''; // 清空现有列表
        
        tasks.forEach(task => {
            const li = createTaskElement(task);
            taskList.appendChild(li);
        });
        
    } catch (error) {
        console.error('加载任务失败:', error);
        // 在页面上显示错误信息
        const taskList = document.getElementById('taskList');
        taskList.innerHTML = `<li class="error-message">加载任务列表失败: ${error.message}</li>`;
    }
}

// URL 截断函数
function truncateUrl(url) {
    try {
        const urlObj = new URL(url);
        let display = urlObj.hostname + urlObj.pathname;
        if (display.length > 40) {
            display = display.substring(0, 37) + '...';
        }
        return display;
    } catch (e) {
        return url;
    }
}

// 切换任务状态
async function toggleTask(taskId, active) {
    try {
        const response = await fetch(`${API_BASE_URL}/task/${taskId}/toggle`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json; charset=utf-8'
            },
            body: JSON.stringify({ active })
        });
        
        if (!response.ok) {
            throw new Error('操作失败');
        }
        
        loadTasks(); // 重新加载任务列表
    } catch (error) {
        alert('操作失败: ' + error.message);
    }
}

// 删除任务
async function deleteTask(taskId) {
    if (!confirm('确定要删除这个任务吗？')) {
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE_URL}/task/${taskId}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            throw new Error('删除失败');
        }
        
        loadTasks(); // 重新加载任务列表
    } catch (error) {
        alert('删除失败: ' + error.message);
    }
}

// 页面加载完成后自动加载任务列表
document.addEventListener('DOMContentLoaded', loadTasks);

function handleSelectorInfo(data) {
    if (data && data.selector) {
        // 只保留实际的CSS选择器部分
        const selectorOnly = data.selector.split('预览内容:')[0]  // 分割并获取选择器部分
            .replace('选择器:', '')  // 移除"选择器:"前缀
            .trim();  // 清理多余空格
        
        document.getElementById('selector-display').textContent = selectorOnly;
        
        // 如果有预览内容，可以显示在另一个元素中
        if (data.preview) {
            const previewElement = document.createElement('div');
            previewElement.className = 'preview-content';
            previewElement.textContent = data.preview;
            document.getElementById('selected-element').appendChild(previewElement);
        }
    }
} 