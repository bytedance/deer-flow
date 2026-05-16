/**
 * Rename URL-encoded filenames to their decoded versions.
 */
import { readdir, rename } from 'fs/promises';
import { join } from 'path';
import { existsSync } from 'fs';

const JS_DIR = 'C:/Users/22831/Desktop/deer-flow-static/assets/js';

async function main() {
  const files = await readdir(JS_DIR);
  const renamed = [];

  for (const file of files) {
    if (file.includes('%')) {
      const decoded = decodeURIComponent(file);
      if (decoded !== file) {
        const oldPath = join(JS_DIR, file);
        const newPath = join(JS_DIR, decoded);
        if (!existsSync(newPath)) {
          await rename(oldPath, newPath);
          console.log(`Renamed: ${file} -> ${decoded}`);
          renamed.push([file, decoded]);
        }
      }
    }
  }

  // Now update all HTML files to reference decoded filenames
  const htmlFiles = [
    'C:/Users/22831/Desktop/deer-flow-static/index.html',
    'C:/Users/22831/Desktop/deer-flow-static/chats/index.html',
    'C:/Users/22831/Desktop/deer-flow-static/chats/new.html',
    'C:/Users/22831/Desktop/deer-flow-static/agents/index.html',
  ];

  const { readFile, writeFile } = await import('fs/promises');

  for (const htmlPath of htmlFiles) {
    if (!existsSync(htmlPath)) continue;
    let html = await readFile(htmlPath, 'utf-8');

    for (const [encoded, decoded] of renamed) {
      html = html.split(encoded).join(decoded);
    }

    await writeFile(htmlPath, html, 'utf-8');
    console.log(`Updated: ${htmlPath}`);
  }

  console.log(`\nDone. Renamed ${renamed.length} files.`);
}

main().catch(console.error);
