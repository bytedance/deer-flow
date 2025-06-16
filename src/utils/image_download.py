def extract_markdown_images(text: str) -> List[str]:
    """简单提取markdown格式图像"""
    if not text:
        return []
    
    # 匹配 ![description](url) 格式
    pattern = r'!\[[^\]]*\]\(([^)]+)\)'
    urls = re.findall(pattern, text)
    
    # 只返回有效的HTTP(S) URL
    return [url.strip() for url in urls if url.strip().startswith(('http://', 'https://'))]

async def download_images_batch(
    image_urls: List[str], 
    session_dir: str,
    max_images: int = 5,
    timeout: int = 10
) -> List[Dict[str, Any]]:
    """简化的批量下载"""
    
    os.makedirs(session_dir, exist_ok=True)
    downloaded_images = []
    
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        for i, url in enumerate(image_urls[:max_images]):
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        content = await response.read()
                        
                        # 简单的文件扩展名检测
                        if 'image/png' in response.headers.get('Content-Type', ''):
                            ext = '.png'
                        elif 'image/gif' in response.headers.get('Content-Type', ''):
                            ext = '.gif'
                        else:
                            ext = '.jpg'
                        
                        filename = f"research_img_{i+1}_{uuid.uuid4().hex[:8]}{ext}"
                        local_path = os.path.join(session_dir, filename)
                        
                        with open(local_path, 'wb') as f:
                            f.write(content)
                        
                        downloaded_images.append({
                            'original_url': url,
                            'local_path': local_path,
                            'filename': filename,
                            'mime_type': response.headers.get('Content-Type', 'image/jpeg'),
                            'size': len(content)
                        })
                        
            except Exception as e:
                logger.warning(f"Failed to download {url}: {e}")
                continue
    
    return downloaded_images