import sys
import json
from playwright.sync_api import sync_playwright
import os

def get_element_selector(page):
    # 直接从页面获取选中的元素
    selector = page.evaluate('''() => {
        try {
            const element = window.selectedElement;
            if (!element || element.nodeType !== Node.ELEMENT_NODE) {
                throw new Error("无效的元素对象");
            }
            
            const path = [];
            let currentElement = element;
            
            while (currentElement && currentElement.nodeType === Node.ELEMENT_NODE && currentElement.tagName !== 'HTML') {
                let selector = currentElement.tagName.toLowerCase();
                
                // 如果有id，优先使用id
                if (currentElement.id) {
                    selector = '#' + CSS.escape(currentElement.id);
                    path.unshift(selector);
                    break;
                }
                
                // 如果有class，使用第一个class
                if (currentElement.classList.length > 0) {
                    selector += '.' + CSS.escape(currentElement.classList[0]);
                }
                
                // 如果有父元素，计算索引
                if (currentElement.parentNode) {
                    const siblings = Array.from(currentElement.parentNode.children)
                        .filter(e => e.tagName === currentElement.tagName);
                    
                    if (siblings.length > 1) {
                        const index = siblings.indexOf(currentElement) + 1;
                        selector += `:nth-of-type(${index})`;
                    }
                }
                
                path.unshift(selector);
                currentElement = currentElement.parentNode;
            }
            
            return path.join(' > ');
            
        } catch (error) {
            console.error('Selector generation error:', error);
            return '';
        }
    }''')
    
    if not selector:
        raise Exception("选择器生成失败")
        
    return selector.strip()  # 返回纯净的选择器

def write_selector_info(data, file_path):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"写入失败: {str(e)}")
        return False

def on_element_selected(selector, preview_content, file_path):
    # 确保选择器不包含额外信息
    clean_selector = selector.strip()  # 只保存纯选择器
    
    selector_info = {
        'selector': clean_selector,  # 存储纯选择器
        'preview': preview_content   # 预览内容单独保存
    }
    write_selector_info(selector_info, file_path)

def main(url, selector_file):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            print(f"正在访问页面: {url}")
            try:
                # 先加载页面
                response = page.goto(url, 
                    timeout=60000,
                    wait_until='domcontentloaded'
                )
                
                if not response:
                    raise Exception("页面加载失败：无响应")
                    
                if response.status != 200:
                    raise Exception(f"页面加载失败：HTTP状态码 {response.status}")
                
                # 等待页面稳定
                page.wait_for_load_state('networkidle', timeout=30000)
                print("页面加载完成")
                
                # 在页面加载完成后注入提示和选择器功能
                page.evaluate('''() => {
                    // 创建并添加样式
                    const style = document.createElement('style');
                    style.textContent = `
                        #loading-tip {
                            position: fixed;
                            top: 20px;
                            right: 20px;
                            background: rgba(0, 0, 0, 0.8);
                            color: white;
                            padding: 10px 20px;
                            border-radius: 5px;
                            z-index: 999999;
                            font-family: Arial, sans-serif;
                            font-size: 14px;
                        }
                    `;
                    document.head.appendChild(style);
                    
                    // 创建提示元素
                    const loadingTip = document.createElement('div');
                    loadingTip.id = 'loading-tip';
                    loadingTip.textContent = '请用鼠标选择要监控的元素（绿框标注）';
                    document.body.appendChild(loadingTip);
                    
                    // 初始化选择器功能
                    window.selectedElement = null;
                    
                    document.addEventListener('mouseover', (e) => {
                        e.target.style.outline = '4px solid #00FF00';
                    });
                    
                    document.addEventListener('mouseout', (e) => {
                        if (e.target !== window.selectedElement) {
                            e.target.style.outline = '';
                        }
                    });
                    
                    document.addEventListener('click', (e) => {
                        e.preventDefault();
                        e.stopPropagation();
                        
                        if (window.selectedElement) {
                            window.selectedElement.style.outline = '';
                        }
                        window.selectedElement = e.target;
                        window.selectedElement.style.outline = '4px solid red';
                        
                        const preview = e.target.innerText.substring(0, 50) + 
                            (e.target.innerText.length > 50 ? '...' : '');
                        
                        window.selectorPreview = preview;
                        
                        const loadingTip = document.getElementById('loading-tip');
                        if (loadingTip) {
                            loadingTip.textContent = '元素已选择，即将关闭窗口...';
                        }
                        
                        window.dispatchEvent(new CustomEvent('selectorChosen'));
                    });
                }''')
                
            except Exception as e:
                print(f"页面加载或操作错误: {str(e)}")
                raise
            
            # 等待选择器事件
            page.evaluate('''() => new Promise((resolve) => {
                window.addEventListener('selectorChosen', resolve, { once: true });
            })''')
            
            try:
                selector = get_element_selector(page)
                preview = page.evaluate('window.selectorPreview')
                
                on_element_selected(selector, preview, selector_file)
            except Exception as e:
                print(f"选择器生成错误: {str(e)}")
                raise e
            
            browser.close()
            
    except Exception as e:
        print(f"发生错误: {str(e)}")
        raise e

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python selector_script.py <url> <selector_file>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2]) 