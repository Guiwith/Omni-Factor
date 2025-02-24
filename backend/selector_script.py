import sys
import json
from playwright.sync_api import sync_playwright
import os

def get_element_selector(page):
    selector = page.evaluate('''() => {
        const element = window.selectedElement;
        if (!element) return '';
        
        const path = [];
        let current = element;
        
        while (current && current.tagName !== 'HTML') {
            let selector = current.tagName.toLowerCase();
            
            if (current.id) {
                return '#' + CSS.escape(current.id);
            }
            
            if (current.classList.length) {
                selector += '.' + CSS.escape(current.classList[0]);
            }
            
            const siblings = Array.from(current.parentNode?.children || [])
                .filter(e => e.tagName === current.tagName);
            
            if (siblings.length > 1) {
                selector += `:nth-of-type(${siblings.indexOf(current) + 1})`;
            }
            
            path.unshift(selector);
            current = current.parentNode;
        }
        
        return path.join(' > ');
    }''')
    return selector.strip()

def save_selector_info(selector, preview, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump({
            'selector': selector,
            'preview': preview
        }, f, ensure_ascii=False)

def inject_selector_ui(page):
    page.evaluate('''() => {
        const style = document.createElement('style');
        style.textContent = `
            #selector-tip {
                position: fixed;
                top: 20px;
                right: 20px;
                background: rgba(0, 0, 0, 0.8);
                color: white;
                padding: 10px;
                border-radius: 5px;
                z-index: 999999;
            }
            .highlight-element {
                outline: 4px solid #00FF00 !important;
            }
            .selected-element {
                outline: 4px solid red !important;
            }
        `;
        document.head.appendChild(style);
        
        const tip = document.createElement('div');
        tip.id = 'selector-tip';
        tip.textContent = '请选择要监控的元素';
        document.body.appendChild(tip);
        
        window.selectedElement = null;
        
        document.addEventListener('mouseover', e => {
            e.target.classList.add('highlight-element');
        });
        
        document.addEventListener('mouseout', e => {
            if (e.target !== window.selectedElement) {
                e.target.classList.remove('highlight-element');
            }
        });
        
        document.addEventListener('click', e => {
            e.preventDefault();
            e.stopPropagation();
            
            if (window.selectedElement) {
                window.selectedElement.classList.remove('selected-element');
            }
            
            window.selectedElement = e.target;
            e.target.classList.add('selected-element');
            
            document.getElementById('selector-tip').textContent = '已选择元素';
            window.selectorPreview = e.target.innerText.substring(0, 50);
            window.dispatchEvent(new CustomEvent('selectorChosen'));
        });
    }''')

def main(url, selector_file):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )
        page = context.new_page()
        
        page.goto(url, wait_until='domcontentloaded')
        page.wait_for_load_state('networkidle', timeout=30000)
        
        inject_selector_ui(page)
        
        # 等待选择器事件
        page.evaluate('() => new Promise(resolve => window.addEventListener("selectorChosen", resolve, { once: true }))')
        
        selector = get_element_selector(page)
        preview = page.evaluate('window.selectorPreview')
        save_selector_info(selector, preview, selector_file)
        
        browser.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python selector_script.py <url> <selector_file>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2]) 