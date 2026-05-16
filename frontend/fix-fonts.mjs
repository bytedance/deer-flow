/**
 * Fix font URLs in the already-scraped HTML files.
 * Downloads fonts from the dev server and replaces __nextjs_font paths.
 */
import puppeteer from 'puppeteer-core';
import { mkdir, writeFile, readFile, stat } from 'fs/promises';
import { join, dirname } from 'path';
import { existsSync } from 'fs';

const BASE_URL = process.env.DEER_FLOW_URL || 'http://localhost:2026';
const OUTPUT_DIR = process.env.OUTPUT_DIR || 'C:/Users/22831/Desktop/deer-flow-static';

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

async function main() {
  const chromePath = findChrome();
  if (!chromePath) {
    console.error('Chrome not found!');
    process.exit(1);
  }

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: 'new',
    args: ['--no-sandbox'],
  });

  const page = await browser.newPage();

  // Fonts to download
  const fonts = [
    '__nextjs_font/geist-latin-ext.woff2',
    '__nextjs_font/geist-mono-latin-ext.woff2',
    '__nextjs_font/geist-latin.woff2',
    '__nextjs_font/geist-mono-latin.woff2',
  ];

  await mkdir(join(OUTPUT_DIR, 'assets/fonts'), { recursive: true });

  const fontPathMapping = {};

  for (const fontPath of fonts) {
    const fontUrl = `${BASE_URL}/${fontPath}`;
    const filename = fontPath.split('/').pop();
    const localPath = `assets/fonts/${filename}`;
    const fullPath = join(OUTPUT_DIR, localPath);

    console.log(`Downloading: ${fontUrl}`);

    try {
      const result = await page.evaluate(async (url) => {
        try {
          const resp = await fetch(url, { cache: 'force-cache' });
          if (!resp.ok) return { ok: false, status: resp.status };
          const buf = await resp.arrayBuffer();
          const bytes = Array.from(new Uint8Array(buf));
          return { ok: true, bytes };
        } catch (e) {
          return { ok: false, error: e.message };
        }
      }, fontUrl);

      if (result.ok) {
        await writeFile(fullPath, new Uint8Array(result.bytes));
        fontPathMapping[`/${fontPath}`] = localPath;
        console.log(`  Saved: ${localPath}`);
      } else {
        console.log(`  Failed: ${result.status || result.error}`);
      }
    } catch (e) {
      console.log(`  Error: ${e.message}`);
    }
  }

  await browser.close();

  // Now fix all HTML files
  const htmlFiles = [
    'index.html',
    'chats/index.html',
    'chats/new.html',
    'agents/index.html',
  ];

  for (const htmlFile of htmlFiles) {
    const fullPath = join(OUTPUT_DIR, htmlFile);
    if (!existsSync(fullPath)) continue;

    let html = await readFile(fullPath, 'utf-8');

    for (const [remotePath, localPath] of Object.entries(fontPathMapping)) {
      html = html.split(remotePath).join(localPath);
    }

    await writeFile(fullPath, html, 'utf-8');
    const size = (await stat(fullPath)).size;
    console.log(`Fixed: ${htmlFile} (${(size / 1024).toFixed(1)} KB)`);
  }

  console.log('\nDone!');
}

main().catch(console.error);
