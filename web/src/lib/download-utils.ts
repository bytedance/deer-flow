// Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
// SPDX-License-Identifier: MIT

import { Document, Packer, Paragraph, TextRun } from "docx";
import { saveAs } from "file-saver";
import html2canvas from "html2canvas";
import jsPDF from "jspdf";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

// 生成带时间戳的文件名
export function generateFilename(baseName: string, extension: string): string {
  const now = new Date();
  const pad = (n: number) => n.toString().padStart(2, '0');
  const timestamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
  return `${baseName}-${timestamp}.${extension}`;
}

// 清理HTML元素中的现代CSS函数，确保html2canvas兼容性
function sanitizeElementForCanvas(element: HTMLElement): void {
  // 移除所有子元素的style属性中可能包含现代CSS函数的内容
  const allElements = element.querySelectorAll('*');
  allElements.forEach((el) => {
    if (el instanceof HTMLElement) {
      // 清理可能包含oklch等现代颜色函数的样式
      const style = el.style;
      const propertiesToRemove: string[] = [];
      
      for (const property of Array.from(style)) {
        const value = style.getPropertyValue(property);
        if (value && (value.includes('oklch') || value.includes('var(--'))) {
          propertiesToRemove.push(property);
        }
      }
      
      propertiesToRemove.forEach(property => {
        style.removeProperty(property);
      });
    }
  });
}

// 使用ReactMarkdown将Markdown渲染为HTML
function renderMarkdownToHTML(markdown: string): string {
  // 处理KaTeX和引用（参考项目中的处理方式）
  const processedMarkdown = markdown
    .replace(/\\\\\[/g, "$$$$") // Replace '\\[' with '$$'
    .replace(/\\\\\]/g, "$$$$") // Replace '\\]' with '$$'
    .replace(/\\\\\(/g, "$$$$") // Replace '\\(' with '$$'
    .replace(/\\\\\)/g, "$$$$") // Replace '\\)' with '$$'
    .replace(/\\\[/g, "$$$$") // Replace '\[' with '$$'
    .replace(/\\\]/g, "$$$$") // Replace '\]' with '$$'
    .replace(/\\\(/g, "$$$$") // Replace '\(' with '$$'
    .replace(/\\\)/g, "$$$$") // Replace '\)' with '$$'
    .replace(/^```markdown\n/gm, "")
    .replace(/^```text\n/gm, "")
    .replace(/^```\n/gm, "")
    .replace(/\n```$/gm, "");

  // 使用ReactMarkdown渲染为HTML字符串
  const reactElement = React.createElement(ReactMarkdown, {
    remarkPlugins: [remarkGfm, remarkMath],
    rehypePlugins: [rehypeKatex],
    components: {
      // 自定义组件，确保在服务端渲染时正常工作
      img: ({ src, alt }) => 
        React.createElement('img', {
          src: src as string,
          alt: alt ?? '',
          style: { maxWidth: '100%', height: 'auto', borderRadius: '4px' }
        }),
      a: ({ href, children }) =>
        React.createElement('a', {
          href: href!,
          target: '_blank',
          rel: 'noopener noreferrer',
          style: { color: '#0066cc', textDecoration: 'underline' }
        }, children),
      table: ({ children }) =>
        React.createElement('table', {
          style: { 
            width: '100%', 
            borderCollapse: 'collapse', 
            margin: '16px 0',
            border: '1px solid #e5e7eb'
          }
        }, children),
      th: ({ children }) =>
        React.createElement('th', {
          style: { 
            padding: '8px 12px', 
            backgroundColor: '#f9fafb',
            border: '1px solid #e5e7eb',
            fontWeight: 'bold',
            textAlign: 'left'
          }
        }, children),
      td: ({ children }) =>
        React.createElement('td', {
          style: { 
            padding: '8px 12px', 
            border: '1px solid #e5e7eb'
          }
        }, children),
      code: ({ children, ...props }) => {
        const inline = 'inline' in props ? props.inline : false;
        if (inline) {
          return React.createElement('code', {
            style: { 
              backgroundColor: '#f3f4f6',
              padding: '2px 4px',
              borderRadius: '3px',
              fontSize: '0.9em',
              fontFamily: 'monospace'
            }
          }, children);
        }
        return React.createElement('pre', {
          style: {
            backgroundColor: '#f8f9fa',
            padding: '16px',
            borderRadius: '6px',
            overflow: 'auto',
            fontSize: '14px',
            fontFamily: 'monospace',
            margin: '16px 0'
          }
        }, React.createElement('code', {}, children));
      },
      blockquote: ({ children }) =>
        React.createElement('blockquote', {
          style: {
            borderLeft: '4px solid #cccccc',
            paddingLeft: '16px',
            margin: '16px 0',
            fontStyle: 'italic',
            color: '#666666'
          }
        }, children)
    }
  }, processedMarkdown);

  return renderToStaticMarkup(reactElement);
}

// 下载Markdown格式
export function downloadAsMarkdown(content: string, filename?: string): void {
  const finalFilename = filename ?? generateFilename('research-report', 'md');
  const blob = new Blob([content], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = finalFilename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 0);
}

// 下载PDF格式
export async function downloadAsPDF(content: string, filename?: string): Promise<void> {
  const finalFilename = filename ?? generateFilename('research-report', 'pdf');
  
  // 创建一个临时的div来渲染markdown内容
  const tempDiv = document.createElement('div');
  tempDiv.style.position = 'absolute';
  tempDiv.style.left = '-9999px';
  tempDiv.style.top = '-9999px';
  tempDiv.style.width = '800px';
  tempDiv.style.padding = '20px';
  tempDiv.style.fontFamily = 'Arial, sans-serif';
  tempDiv.style.fontSize = '14px';
  tempDiv.style.lineHeight = '1.6';
  tempDiv.style.color = '#000000';
  tempDiv.style.backgroundColor = '#ffffff';
  // 添加CSS变量覆盖，避免oklch颜色函数
  tempDiv.style.setProperty('--color', '#000000');
  tempDiv.style.setProperty('--background', '#ffffff');
  
  // 使用ReactMarkdown正确渲染Markdown内容
  const htmlContent = renderMarkdownToHTML(content);
  
  tempDiv.innerHTML = `<div style="max-width: 800px; padding: 20px; font-family: Arial, sans-serif; line-height: 1.6; color: #000000;">
    ${htmlContent}
  </div>`;
  document.body.appendChild(tempDiv);
  
  // 清理现代CSS函数
  sanitizeElementForCanvas(tempDiv);
  
  try {
    const canvas = await html2canvas(tempDiv, {
      scale: 2,
      useCORS: true,
      allowTaint: false,
      backgroundColor: '#ffffff',
      ignoreElements: (element) => {
        // 忽略可能包含不支持样式的元素
        return element.tagName === 'SCRIPT' || element.tagName === 'STYLE';
      },
      onclone: (clonedDoc) => {
        // 移除所有现有的样式表以避免oklch等现代CSS函数
        const existingStyles = clonedDoc.querySelectorAll('style, link[rel="stylesheet"]');
        existingStyles.forEach(style => style.remove());
        
        // 添加KaTeX CSS
        const katexLink = clonedDoc.createElement('link');
        katexLink.rel = 'stylesheet';
        katexLink.href = 'https://cdn.jsdelivr.net/npm/katex@0.16.21/dist/katex.min.css';
        clonedDoc.head.appendChild(katexLink);
        
        // 添加安全的样式
        const styleElement = clonedDoc.createElement('style');
        styleElement.textContent = `
          * {
            color: #000000 !important;
            background-color: #ffffff !important;
            border-color: #cccccc !important;
            font-family: Arial, sans-serif !important;
          }
          h1 { 
            color: #1a1a1a !important; 
            font-size: 28px !important;
            font-weight: bold !important;
            margin: 24px 0 12px 0 !important;
            line-height: 1.2 !important;
            border-bottom: 2px solid #e5e5e5 !important;
            padding-bottom: 8px !important;
          }
          h2 { 
            color: #2a2a2a !important;
            font-size: 24px !important;
            font-weight: bold !important;
            margin: 20px 0 10px 0 !important;
            line-height: 1.3 !important;
            border-bottom: 1px solid #e5e5e5 !important;
            padding-bottom: 4px !important;
          }
          h3 { 
            color: #3a3a3a !important;
            font-size: 20px !important;
            font-weight: bold !important;
            margin: 18px 0 8px 0 !important;
            line-height: 1.3 !important;
          }
          h4, h5, h6 {
            color: #4a4a4a !important;
            font-weight: bold !important;
            margin: 16px 0 6px 0 !important;
          }
          p { 
            margin: 12px 0 !important; 
            line-height: 1.6 !important;
            color: #333333 !important;
          }
          strong { 
            color: #000000 !important; 
            font-weight: bold !important;
          }
          em { 
            color: #555555 !important; 
            font-style: italic !important;
          }
          ul, ol { 
            margin: 12px 0 !important; 
            padding-left: 20px !important;
            list-style-position: outside !important;
          }
          ul {
            list-style-type: disc !important;
          }
          ol {
            list-style-type: decimal !important;
          }
          li { 
            margin: 4px 0 !important; 
            line-height: 1.6 !important;
            padding-left: 6px !important;
            text-align: left !important;
          }
          table {
            width: 100% !important;
            border-collapse: collapse !important;
            margin: 16px 0 !important;
            border: 1px solid #e5e7eb !important;
          }
          th {
            padding: 10px 12px !important;
            background-color: #f9fafb !important;
            border: 1px solid #e5e7eb !important;
            font-weight: bold !important;
            text-align: left !important;
          }
          td {
            padding: 8px 12px !important;
            border: 1px solid #e5e7eb !important;
          }
          code {
            background-color: #f3f4f6 !important;
            padding: 2px 6px !important;
            border-radius: 4px !important;
            font-size: 0.9em !important;
            font-family: 'Courier New', monospace !important;
          }
          pre {
            background-color: #f8f9fa !important;
            padding: 16px !important;
            border-radius: 8px !important;
            overflow: auto !important;
            margin: 16px 0 !important;
            border: 1px solid #e9ecef !important;
          }
          pre code {
            background-color: transparent !important;
            padding: 0 !important;
            font-size: 14px !important;
          }
          blockquote {
            border-left: 4px solid #cccccc !important;
            padding-left: 16px !important;
            margin: 16px 0 !important;
            font-style: italic !important;
            color: #666666 !important;
            background-color: #f9f9f9 !important;
            padding: 12px 16px !important;
            border-radius: 0 6px 6px 0 !important;
          }
          img {
            max-width: 100% !important;
            height: auto !important;
            border-radius: 6px !important;
            margin: 12px 0 !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
          }
          a {
            color: #0066cc !important;
            text-decoration: underline !important;
          }
          a:hover {
            color: #004499 !important;
          }
          /* KaTeX样式支持 */
          .katex {
            font-size: 1em !important;
          }
          .katex-display {
            margin: 16px 0 !important;
            text-align: center !important;
          }
        `;
        clonedDoc.head.appendChild(styleElement);
      }
    });
    
    const imgData = canvas.toDataURL('image/png');
    const pdf = new jsPDF();
    const imgWidth = 210;
    const pageHeight = 295;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;
    let heightLeft = imgHeight;
    let position = 0;
    
    pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
    heightLeft -= pageHeight;
    
    while (heightLeft >= 0) {
      position = heightLeft - imgHeight;
      pdf.addPage();
      pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
      heightLeft -= pageHeight;
    }
    
    pdf.save(finalFilename);
  } finally {
    document.body.removeChild(tempDiv);
  }
}

// 下载为图片格式
export async function downloadAsImage(elementId: string, filename?: string): Promise<void> {
  const finalFilename = filename ?? generateFilename('research-report', 'png');
  const element = document.getElementById(elementId);
  
  if (!element) {
    throw new Error('找不到要截图的元素');
  }
  
  // 清理现代CSS函数
  sanitizeElementForCanvas(element);
  
  const canvas = await html2canvas(element, {
    scale: 2,
    useCORS: true,
    allowTaint: false,
    backgroundColor: '#ffffff',
    ignoreElements: (element) => {
      // 忽略可能包含不支持样式的元素
      return element.tagName === 'SCRIPT' || element.tagName === 'STYLE';
    },
    onclone: (clonedDoc) => {
            // 移除所有现有的样式表以避免oklch等现代CSS函数
      const existingStyles = clonedDoc.querySelectorAll('style, link[rel="stylesheet"]');
      existingStyles.forEach(style => style.remove());
      
      // 添加KaTeX CSS
      const katexLink = clonedDoc.createElement('link');
      katexLink.rel = 'stylesheet';
      katexLink.href = 'https://cdn.jsdelivr.net/npm/katex@0.16.21/dist/katex.min.css';
      clonedDoc.head.appendChild(katexLink);
      
      // 添加安全的样式
        const styleElement = clonedDoc.createElement('style');
        styleElement.textContent = `
          * {
            color: #000000 !important;
            background-color: #ffffff !important;
            border-color: #cccccc !important;
            font-family: Arial, sans-serif !important;
          }
          h1 { 
            color: #1a1a1a !important; 
            font-size: 28px !important;
            font-weight: bold !important;
            margin: 24px 0 12px 0 !important;
            line-height: 1.2 !important;
            border-bottom: 2px solid #e5e5e5 !important;
            padding-bottom: 8px !important;
          }
          h2 { 
            color: #2a2a2a !important;
            font-size: 24px !important;
            font-weight: bold !important;
            margin: 20px 0 10px 0 !important;
            line-height: 1.3 !important;
            border-bottom: 1px solid #e5e5e5 !important;
            padding-bottom: 4px !important;
          }
          h3 { 
            color: #3a3a3a !important;
            font-size: 20px !important;
            font-weight: bold !important;
            margin: 18px 0 8px 0 !important;
            line-height: 1.3 !important;
          }
          h4, h5, h6 {
            color: #4a4a4a !important;
            font-weight: bold !important;
            margin: 16px 0 6px 0 !important;
          }
          p { 
            margin: 12px 0 !important; 
            line-height: 1.6 !important;
            color: #333333 !important;
          }
          strong { 
            color: #000000 !important; 
            font-weight: bold !important;
          }
          em { 
            color: #555555 !important; 
            font-style: italic !important;
          }
          ul, ol { 
            margin: 12px 0 !important; 
            padding-left: 20px !important;
            list-style-position: outside !important;
          }
          ul {
            list-style-type: disc !important;
          }
          ol {
            list-style-type: decimal !important;
          }
          li { 
            margin: 4px 0 !important; 
            line-height: 1.6 !important;
            padding-left: 6px !important;
            text-align: left !important;
          }
          table {
            width: 100% !important;
            border-collapse: collapse !important;
            margin: 16px 0 !important;
            border: 1px solid #e5e7eb !important;
          }
          th {
            padding: 10px 12px !important;
            background-color: #f9fafb !important;
            border: 1px solid #e5e7eb !important;
            font-weight: bold !important;
            text-align: left !important;
          }
          td {
            padding: 8px 12px !important;
            border: 1px solid #e5e7eb !important;
          }
          code {
            background-color: #f3f4f6 !important;
            padding: 2px 6px !important;
            border-radius: 4px !important;
            font-size: 0.9em !important;
            font-family: 'Courier New', monospace !important;
          }
          pre {
            background-color: #f8f9fa !important;
            padding: 16px !important;
            border-radius: 8px !important;
            overflow: auto !important;
            margin: 16px 0 !important;
            border: 1px solid #e9ecef !important;
          }
          pre code {
            background-color: transparent !important;
            padding: 0 !important;
            font-size: 14px !important;
          }
          blockquote {
            border-left: 4px solid #cccccc !important;
            padding-left: 16px !important;
            margin: 16px 0 !important;
            font-style: italic !important;
            color: #666666 !important;
            background-color: #f9f9f9 !important;
            padding: 12px 16px !important;
            border-radius: 0 6px 6px 0 !important;
          }
          img {
            max-width: 100% !important;
            height: auto !important;
            border-radius: 6px !important;
            margin: 12px 0 !important;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
          }
          a {
            color: #0066cc !important;
            text-decoration: underline !important;
          }
          a:hover {
            color: #004499 !important;
          }
          /* KaTeX样式支持 */
          .katex {
            font-size: 1em !important;
          }
          .katex-display {
            margin: 16px 0 !important;
            text-align: center !important;
          }
        `;
      clonedDoc.head.appendChild(styleElement);
    }
  });
  
  canvas.toBlob((blob) => {
    if (blob) {
      saveAs(blob, finalFilename);
    }
  }, 'image/png', 1.0);
}

// 下载Word格式
export async function downloadAsWord(content: string, filename?: string): Promise<void> {
  const finalFilename = filename ?? generateFilename('research-report', 'docx');
  
  // 简单的markdown转文本处理
  const textContent = content
    .replace(/^#+\s*/gm, '') // 移除标题标记
    .replace(/\*\*(.*?)\*\*/g, '$1') // 移除粗体标记
    .replace(/\*(.*?)\*/g, '$1') // 移除斜体标记
    .replace(/^\- /gm, '• ') // 转换列表项
    .trim();
  
  const doc = new Document({
    sections: [
      {
        properties: {},
        children: textContent.split('\n\n').map(paragraph => 
          new Paragraph({
            children: [new TextRun(paragraph.trim())],
            spacing: {
              after: 200,
            },
          })
        ),
      },
    ],
  });
  
  const blob = await Packer.toBlob(doc);
  saveAs(blob, finalFilename);
}

// 根据内容创建一个可以截图的临时元素
export function createTempElementForScreenshot(content: string): string {
  const tempId = `temp-screenshot-${Date.now()}`;
  const tempDiv = document.createElement('div');
  tempDiv.id = tempId;
  tempDiv.style.position = 'absolute';
  tempDiv.style.left = '-9999px';
  tempDiv.style.top = '-9999px';
  tempDiv.style.width = '800px';
  tempDiv.style.padding = '20px';
  tempDiv.style.fontFamily = 'Arial, sans-serif';
  tempDiv.style.fontSize = '14px';
  tempDiv.style.lineHeight = '1.6';
  tempDiv.style.color = '#000000';
  tempDiv.style.backgroundColor = '#ffffff';
  tempDiv.style.border = '1px solid #dddddd';
  tempDiv.style.borderRadius = '8px';
  // 添加CSS变量覆盖，避免oklch颜色函数
  tempDiv.style.setProperty('--color', '#000000');
  tempDiv.style.setProperty('--background', '#ffffff');
  
  // 使用ReactMarkdown正确渲染Markdown内容
  const htmlContent = renderMarkdownToHTML(content);
  
  tempDiv.innerHTML = `<div style="max-width: 760px; padding: 20px; font-family: Arial, sans-serif; line-height: 1.6; color: #000000;">
    ${htmlContent}
  </div>`;
  document.body.appendChild(tempDiv);
  
  return tempId;
}

// 清理临时元素
export function cleanupTempElement(elementId: string): void {
  const element = document.getElementById(elementId);
  if (element) {
    document.body.removeChild(element);
  }
} 