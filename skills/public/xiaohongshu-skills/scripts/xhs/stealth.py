"""反检测 JS 注入 + Chrome 启动参数，对应 go-rod/stealth。"""

# 真实 Chrome UA（固定版本，避免每次随机导致指纹不一致）
REALISTIC_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# 反检测 JS 脚本：在页面加载时注入
STEALTH_JS = """
(() => {
    // 1. navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true,
    });

    // 2. chrome.runtime
    if (!window.chrome) {
        window.chrome = {};
    }
    if (!window.chrome.runtime) {
        window.chrome.runtime = {
            connect: () => {},
            sendMessage: () => {},
        };
    }

    // 3. plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            return [
                {
                    0: {type: 'application/x-google-chrome-pdf'},
                    description: 'Portable Document Format',
                    filename: 'internal-pdf-viewer',
                    length: 1,
                    name: 'Chrome PDF Plugin',
                },
                {
                    0: {type: 'application/pdf'},
                    description: '',
                    filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                    length: 1,
                    name: 'Chrome PDF Viewer',
                },
                {
                    0: {type: 'application/x-nacl'},
                    description: '',
                    filename: 'internal-nacl-plugin',
                    length: 1,
                    name: 'Native Client',
                },
            ];
        },
        configurable: true,
    });

    // 4. languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en-US', 'en'],
        configurable: true,
    });

    // 5. permissions
    const originalQuery = window.navigator.permissions?.query;
    if (originalQuery) {
        window.navigator.permissions.query = (parameters) =>
            parameters.name === 'notifications'
                ? Promise.resolve({ state: Notification.permission })
                : originalQuery(parameters);
    }

    // 6. WebGL vendor/renderer
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.call(this, parameter);
    };

    // 7. hardwareConcurrency — 随机 4 或 8
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => [4, 8][Math.floor(Math.random() * 2)],
        configurable: true,
    });

    // 8. deviceMemory — 随机 4 或 8
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => [4, 8][Math.floor(Math.random() * 2)],
        configurable: true,
    });

    // 9. navigator.connection — 伪造网络信息
    Object.defineProperty(navigator, 'connection', {
        get: () => ({
            effectiveType: '4g',
            downlink: 10,
            rtt: 50,
            saveData: false,
        }),
        configurable: true,
    });

    // 10. chrome.csi / chrome.loadTimes — 空函数伪装
    if (window.chrome) {
        window.chrome.csi = function() { return {}; };
        window.chrome.loadTimes = function() { return {}; };
    }

    // 11. outerWidth/outerHeight — 与 innerWidth/innerHeight 对齐
    Object.defineProperty(window, 'outerWidth', {
        get: () => window.innerWidth,
        configurable: true,
    });
    Object.defineProperty(window, 'outerHeight', {
        get: () => window.innerHeight,
        configurable: true,
    });
})();
"""

# Chrome 启动参数（反检测相关）
STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-component-update",
    "--disable-extensions",
    "--disable-sync",
]
