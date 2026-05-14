/**
 * Scrape deer-flow workspace pages as static HTML using puppeteer-core + system Chrome
 *
 * Usage: node scrape-workspace.mjs
 *
 * This script downloads the CSS and JS resources from the rendered pages
 * and replaces URLs with local relative paths so the pages work standalone.
 */
import puppeteer from 'puppeteer-core';
import { mkdir, writeFile, readFile, stat } from 'fs/promises';
import { join, dirname } from 'path';
import { existsSync } from 'fs';

const BASE_URL = process.env.DEER_FLOW_URL || 'http://localhost:2026';
const OUTPUT_DIR = process.env.OUTPUT_DIR || 'C:/Users/22831/Desktop/deer-flow-static';

const PAGES = [
  { url: '/workspace', output: 'index.html' },
  { url: '/workspace/chats', output: 'chats/index.html' },
  { url: '/workspace/chats/new', output: 'chats/new.html' },
  { url: '/workspace/agents', output: 'agents/index.html' },
];

// Chrome paths on Windows
const CHROME_PATHS = [
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Users/22831/AppData/Local/Google/Chrome/Application/chrome.exe',
];

function findChrome() {
  for (const p of CHROME_PATHS) {
    if (existsSync(p)) return p;
  }
  return null;
}

async function ensureDir(filePath) {
  const dir = dirname(filePath);
  if (!existsSync(dir)) {
    await mkdir(dir, { recursive: true });
  }
}

async function scrapePage(browser, pageConfig) {
  const { url, output } = pageConfig;
  const fullUrl = `${BASE_URL}${url}`;
  const outputPath = join(OUTPUT_DIR, output);

  console.log(`\nScraping: ${fullUrl}`);

  const page = await browser.newPage();

  // Mock all API calls
  await page.setRequestInterception(true);
  page.on('request', (request) => {
    const reqUrl = request.url();
    if (reqUrl.includes('/api/')) {
      const mockBody = JSON.stringify({
        threads: [],
        agents: [],
        skills: [],
        models: [],
        search_results: [],
      });
      request.respond({
        status: 200,
        contentType: 'application/json',
        headers: { 'Access-Control-Allow-Origin': '*' },
        body: mockBody,
      });
    } else {
      request.continue();
    }
  });

  try {
    await page.goto(fullUrl, { waitUntil: 'networkidle0', timeout: 30000 });
    // Wait for React hydration
    await new Promise(r => setTimeout(r, 4000));

    // Check if page loaded
    const title = await page.title();
    console.log(`  Page title: ${title}`);

    // Collect and download all resources
    const resources = await page.evaluate(() => {
      const resources = [];

      document.querySelectorAll('link[rel="stylesheet"]').forEach((link) => {
        if (link.href && !link.href.startsWith('data:')) {
          resources.push({ type: 'css', url: link.href });
        }
      });

      document.querySelectorAll('script[src]').forEach((script) => {
        if (script.src && !script.src.startsWith('data:')) {
          resources.push({ type: 'js', url: script.src });
        }
      });

      document.querySelectorAll('img[src]').forEach((img) => {
        if (img.src && !img.src.startsWith('data:')) {
          resources.push({ type: 'image', url: img.src });
        }
      });

      return resources;
    });

    console.log(`  Found ${resources.length} resources`);

    // Download each resource and save to assets
    const pathMapping = {}; // full URL -> local path
    const relPathMapping = {}; // relative path (e.g. /_next/static/...) -> local path
    for (const resource of resources) {
      try {
        const urlObj = new URL(resource.url);
        const pathname = urlObj.pathname;
        const filename = pathname.split('/').filter(Boolean).pop() || 'index';

        const assetDir = resource.type === 'css' ? 'css' : resource.type === 'js' ? 'js' : resource.type === 'image' ? 'images' : 'other';
        const assetPath = `assets/${assetDir}/${filename}`;
        const fullPath = join(OUTPUT_DIR, assetPath);

        await ensureDir(fullPath);

        const response = await page.evaluate(async (url) => {
          try {
            const resp = await fetch(url, { cache: 'force-cache' });
            const ct = resp.headers.get('content-type') || '';
            if (ct.includes('text/') || ct.includes('javascript') || ct.includes('css')) {
              return { ok: true, text: await resp.text() };
            }
            const buf = await resp.arrayBuffer();
            return { ok: true, binary: Buffer.from(buf).toString('base64') };
          } catch (e) {
            return { ok: false, error: e.message };
          }
        }, resource.url);

        if (response.ok) {
          if (response.text) {
            let content = response.text;
            // Fix font URLs in CSS - convert relative URLs to local paths
            content = content.replace(/url\((["']?)(\/[^)]+)\1\)/g, (match, quote, urlPath) => {
              const filename = urlPath.split('/').filter(Boolean).pop() || 'font';
              const fontPath = `assets/fonts/${filename}`;
              const fontFullPath = join(OUTPUT_DIR, fontPath);
              // We'll download fonts in a second pass
              return `url(${quote}${fontPath}${quote})`;
            });
            await writeFile(fullPath, content, 'utf-8');
          } else if (response.binary) {
            await writeFile(fullPath, Buffer.from(response.binary, 'base64'));
          }
          pathMapping[resource.url] = assetPath;
          relPathMapping[pathname] = assetPath;
          console.log(`    Downloaded: ${assetPath}`);
        }
      } catch (e) {
        console.log(`    Skipped: ${resource.url} (${e.message})`);
      }
    }

    // Get fully rendered HTML
    let html = await page.content();

    // Second pass: download fonts referenced in CSS
    for (const [relPath, localPath] of Object.entries(relPathMapping)) {
      if (!localPath.startsWith('assets/css/')) continue;
      const cssFullPath = join(OUTPUT_DIR, localPath);
      if (!existsSync(cssFullPath)) continue;
      try {
        const cssContent = await readFile(cssFullPath, 'utf-8');
        const fontMatches = cssContent.match(/url\(["']?(\/[^"')\s]+)["']?\)/g) || [];
        for (const fontMatch of fontMatches) {
          const urlMatch = fontMatch.match(/url\(["']?([^"')\s]+)["']?\)/);
          if (!urlMatch) continue;
          const fontUrl = BASE_URL + urlMatch[1];
          const fontFilename = urlMatch[1].split('/').filter(Boolean).pop();
          const fontLocalPath = `assets/fonts/${fontFilename}`;
          const fontFullPath = join(OUTPUT_DIR, fontLocalPath);
          await ensureDir(fontFullPath);

          try {
            const fontResp = await page.evaluate(async (url) => {
              try {
                const resp = await fetch(url, { cache: 'force-cache' });
                const buf = await resp.arrayBuffer();
                return { ok: true, binary: Buffer.from(buf).toString('base64') };
              } catch (e) {
                return { ok: false, error: e.message };
              }
            }, fontUrl);
            if (fontResp.ok) {
              await writeFile(fontFullPath, Buffer.from(fontResp.binary, 'base64'));
              console.log(`    Downloaded font: ${fontLocalPath}`);
            }
          } catch (e) {
            // Font download failed, skip
          }
        }
      } catch (e) {
        // Skip CSS read errors
      }
    }

    // Replace both full URLs and relative paths with local paths
    for (const [remoteUrl, localPath] of Object.entries(pathMapping)) {
      html = html.split(remoteUrl).join(localPath);
    }
    for (const [relPath, localPath] of Object.entries(relPathMapping)) {
      html = html.split(relPath).join(localPath);
    }

    // Inject mock API interceptor script
    const mockScript = `
<script>
// Mock all API fetch calls
const _origFetch = window.fetch;
window.fetch = async function(...args) {
  const url = typeof args[0] === 'string' ? args[0] : args[0].url || args[0];
  if (url && url.includes('/api/')) {
    console.log('[Mock] Intercepted:', url);
    return new Response(JSON.stringify({threads:[],agents:[],skills:[],models:[],search_results:[]}), {
      status: 200,
      headers: {'Content-Type': 'application/json'}
    });
  }
  return _origFetch.apply(this, args);
};
</script>`;

    html = html.replace('</head>', mockScript + '\n</head>');

    await writeFile(outputPath, html, 'utf-8');
    const size = (await stat(outputPath)).size;
    console.log(`  Saved: ${output} (${(size / 1024).toFixed(1)} KB)`);
  } catch (e) {
    console.error(`  Error: ${e.message}`);
  } finally {
    await page.close();
  }
}

async function main() {
  const chromePath = findChrome();
  if (!chromePath) {
    console.error('Chrome not found! Tried paths:');
    for (const p of CHROME_PATHS) console.error(`  ${p}`);
    process.exit(1);
  }
  console.log(`Chrome: ${chromePath}`);
  console.log(`Base URL: ${BASE_URL}`);
  console.log(`Output: ${OUTPUT_DIR}`);

  // Create output directories
  await mkdir(OUTPUT_DIR, { recursive: true });
  await mkdir(join(OUTPUT_DIR, 'chats'), { recursive: true });
  await mkdir(join(OUTPUT_DIR, 'agents'), { recursive: true });
  await mkdir(join(OUTPUT_DIR, 'assets', 'css'), { recursive: true });
  await mkdir(join(OUTPUT_DIR, 'assets', 'js'), { recursive: true });
  await mkdir(join(OUTPUT_DIR, 'assets', 'images'), { recursive: true });

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    for (const pageConfig of PAGES) {
      await scrapePage(browser, pageConfig);
    }
  } finally {
    await browser.close();
  }

  console.log('\nDone! Files saved to:', OUTPUT_DIR);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
