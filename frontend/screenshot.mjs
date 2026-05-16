import puppeteer from 'puppeteer-core';
import { existsSync } from 'fs';

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

async function main() {
  const chromePath = findChrome();
  if (!chromePath) { console.error('Chrome not found'); process.exit(1); }

  const browser = await puppeteer.launch({
    executablePath: chromePath,
    headless: 'new',
    args: ['--no-sandbox'],
  });

  const pages = [
    { url: 'file:///C:/Users/22831/Desktop/deer-flow-static/agents/index.html', name: 'agents' },
    { url: 'file:///C:/Users/22831/Desktop/deer-flow-static/chats/new.html', name: 'chats-new' },
    { url: 'file:///C:/Users/22831/Desktop/deer-flow-static/chats/index.html', name: 'chats-list' },
    { url: 'file:///C:/Users/22831/Desktop/deer-flow-static/index.html', name: 'workspace' },
  ];

  for (const pageConfig of pages) {
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900 });

    const errors = [];
    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text());
    });

    await page.goto(pageConfig.url, { waitUntil: 'networkidle0', timeout: 30000 });
    await new Promise(r => setTimeout(r, 3000));

    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    await page.screenshot({ path: `C:/Users/22831/Desktop/deer-flow-static/screenshot-${pageConfig.name}.png`, fullPage: false });

    console.log(`${pageConfig.name}: background=${bg}, errors=${errors.length}`);
    if (errors.length > 0) {
      errors.slice(0, 3).forEach(e => console.log('  -', e.substring(0, 120)));
    }

    await page.close();
  }

  await browser.close();
  console.log('\nDone.');
}

main().catch(console.error);
