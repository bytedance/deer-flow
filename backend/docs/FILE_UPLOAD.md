# File Upload Feature

## Overview

The Thinktank.ai backend provides full file upload support, including multi-file uploads, and automatically converts Office documents and PDFs to Markdown.

## Features

- Multi-file upload support
- Automatic document-to-Markdown conversion (PDF, PPT, Excel, Word)
- Files stored in thread-isolated directories
- Agent automatically sees uploaded files
- File list retrieval and deletion

## API Endpoints

### 1. Upload files
```
POST /api/threads/{thread_id}/uploads
```

**Request body:** `multipart/form-data`
- `files`: one or more files

**Response:**
```json
{
  "success": true,
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".think-tank/threads/{thread_id}/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf",
      "markdown_file": "document.md",
      "markdown_path": ".think-tank/threads/{thread_id}/user-data/uploads/document.md",
      "markdown_virtual_path": "/mnt/user-data/uploads/document.md",
      "markdown_artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.md"
    }
  ],
  "message": "Successfully uploaded 1 file(s)"
}
```

**Path fields:**
- `path`: physical filesystem path (relative to `backend/`)
- `virtual_path`: virtual path used by the Agent in the sandbox
- `artifact_url`: HTTP URL for frontend access

### 2. List uploaded files
```
GET /api/threads/{thread_id}/uploads/list
```

**Response:**
```json
{
  "files": [
    {
      "filename": "document.pdf",
      "size": 1234567,
      "path": ".think-tank/threads/{thread_id}/user-data/uploads/document.pdf",
      "virtual_path": "/mnt/user-data/uploads/document.pdf",
      "artifact_url": "/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf",
      "extension": ".pdf",
      "modified": 1705997600.0
    }
  ],
  "count": 1
}
```

### 3. Delete a file
```
DELETE /api/threads/{thread_id}/uploads/{filename}
```

**Response:**
```json
{
  "success": true,
  "message": "Deleted document.pdf"
}
```

## Supported Document Formats

The following formats are automatically converted to Markdown:
- PDF (`.pdf`)
- PowerPoint (`.ppt`, `.pptx`)
- Excel (`.xls`, `.xlsx`)
- Word (`.doc`, `.docx`)

Converted Markdown files are stored in the same directory, with the original filename plus a `.md` extension.

## Agent Integration

### Automatic file listing

On each request, the Agent automatically receives the list of uploaded files, formatted as:

```xml
<uploaded_files>
The following files have been uploaded and are available for use:

- document.pdf (1.2 MB)
  Path: /mnt/user-data/uploads/document.pdf

- document.md (45.3 KB)
  Path: /mnt/user-data/uploads/document.md

You can read these files using the `read_file` tool with the paths shown above.
</uploaded_files>
```

### Using uploaded files

The Agent runs in a sandbox and uses virtual paths. It can read uploaded files directly via `read_file`:

```python
# Read original PDF (if supported)
read_file(path="/mnt/user-data/uploads/document.pdf")

# Read converted Markdown (recommended)
read_file(path="/mnt/user-data/uploads/document.md")
```

**Path mapping:**
- Agent uses: `/mnt/user-data/uploads/document.pdf` (virtual path)
- Physical storage: `backend/.think-tank/threads/{thread_id}/user-data/uploads/document.pdf`
- Frontend access: `/api/threads/{thread_id}/artifacts/mnt/user-data/uploads/document.pdf` (HTTP URL)

The upload flow uses a "thread directory first" strategy:
- Files are first written to `backend/.think-tank/threads/{thread_id}/user-data/uploads/` as canonical storage
- Local sandbox (`sandbox_id=local`) uses the thread directory content directly
- Non-local sandboxes additionally sync to `/mnt/user-data/uploads/*` for runtime visibility

## Test Examples

### Test with curl

```bash
# 1. Upload a single file
curl -X POST http://localhost:2026/api/threads/test-thread/uploads \
  -F "files=@/path/to/document.pdf"

# 2. Upload multiple files
curl -X POST http://localhost:2026/api/threads/test-thread/uploads \
  -F "files=@/path/to/document.pdf" \
  -F "files=@/path/to/presentation.pptx" \
  -F "files=@/path/to/spreadsheet.xlsx"

# 3. List uploaded files
curl http://localhost:2026/api/threads/test-thread/uploads/list

# 4. Delete a file
curl -X DELETE http://localhost:2026/api/threads/test-thread/uploads/document.pdf
```

### Test with Python

```python
import requests

thread_id = "test-thread"
base_url = "http://localhost:2026"

# Upload files
files = [
    ("files", open("document.pdf", "rb")),
    ("files", open("presentation.pptx", "rb")),
]
response = requests.post(
    f"{base_url}/api/threads/{thread_id}/uploads",
    files=files
)
print(response.json())

# List files
response = requests.get(f"{base_url}/api/threads/{thread_id}/uploads/list")
print(response.json())

# Delete file
response = requests.delete(
    f"{base_url}/api/threads/{thread_id}/uploads/document.pdf"
)
print(response.json())
```

## File Storage Layout

```
backend/.think-tank/threads/
└── {thread_id}/
    └── user-data/
        └── uploads/
            ├── document.pdf          # Original file
            ├── document.md           # Converted Markdown
            ├── presentation.pptx
            ├── presentation.md
            └── ...
```

## Limits

- Max file size: 100MB (configurable in `nginx.conf` via `client_max_body_size`)
- Filename safety: system validates file paths to prevent directory traversal
- Thread isolation: uploads are isolated per thread and cannot be accessed across threads

## Implementation Details

### Components

1. **Upload Router** (`src/gateway/routers/uploads.py`)
   - Handles upload, list, delete requests
   - Uses markitdown for document conversion

2. **Uploads Middleware** (`src/agents/middlewares/uploads_middleware.py`)
   - Injects the file list before each Agent request
   - Auto-generates the formatted file list message

3. **Nginx config** (`nginx.conf`)
   - Routes upload requests to the Gateway API
   - Enables large file upload support

### Dependencies

- `markitdown>=0.0.1a2` - document conversion
- `python-multipart>=0.0.20` - file upload handling

## Troubleshooting

### Upload fails

1. Check file size against limits
2. Ensure Gateway API is running
3. Check disk space
4. Review Gateway logs: `make gateway`

### Document conversion fails

1. Verify markitdown is installed: `uv run python -c "import markitdown"`
2. Check logs for detailed errors
3. Some corrupted or encrypted documents may not convert, but the original file is preserved

### Agent cannot see uploaded files

1. Confirm `UploadsMiddleware` is registered in `agent.py`
2. Verify `thread_id` is correct
3. Confirm the files were uploaded to `backend/.think-tank/threads/{thread_id}/user-data/uploads/`
4. For non-local sandbox scenarios, confirm the upload endpoint returned no errors (sandbox sync must succeed)

## Development Suggestions

### Frontend integration

```typescript
// Upload files example
async function uploadFiles(threadId: string, files: File[]) {
  const formData = new FormData();
  files.forEach((file) => {
    formData.append("files", file);
  });

  const response = await fetch(`/api/threads/${threadId}/uploads`, {
    method: "POST",
    body: formData,
  });

  return response.json();
}

// List files
async function listFiles(threadId: string) {
  const response = await fetch(`/api/threads/${threadId}/uploads/list`);
  return response.json();
}
```

### Potential enhancements

1. **File preview**: add preview endpoints to view files in the browser
2. **Bulk delete**: delete multiple files at once
3. **File search**: search by filename or type
4. **Versioning**: keep multiple versions of a file
5. **Archive support**: auto-unzip zip files
6. **Image OCR**: extract text from uploaded images
