# Pattern: Security Best Practices

> **Source:** `echarts-docs/handbook/zh/best-practices/security.md`

## Core Principle

**ECharts assumes all input is from trusted sources** and does NOT auto-sanitize. The developer is responsible for sanitizing untrusted data.

## Risk Checklist

| API | Risk | Mitigation |
|-----|------|------------|
| `tooltip.formatter` (function returning HTML) | **XSS** | Use `echarts.format.encodeHTML()` |
| `toolbox.feature.dataView.*` | **XSS** | DataView panel renders full HTML |
| `tooltip.extraCssText` | **CSS injection** | Validate/sanitize if untrusted |
| `title.link`, `title.sublink` | **URL injection** | Validate protocol (allowlist `https://`) |
| `series-treemap.data.link` | **URL injection** | Validate protocol |
| `series-sunburst.data.link` | **URL injection** | Validate protocol |
| `toolbox.feature.saveAsImage.name` | **Filename injection** | Sanitize for path traversal, special chars |
| `dataset.transform` filter `config.reg` | **ReDoS** | Never accept untrusted regex patterns |
| JS callback functions | **Code injection** | Generally safe unless executing eval |

## XSS Prevention

### tooltip.formatter (the most common risk)

```javascript
// ❌ UNSAFE — user-controlled data injected as HTML
tooltip: {
  formatter: function(params) {
    return `${params.name}: <b>${params.value}</b>`;
  }
}

// ✅ SAFE — encode all untrusted data
tooltip: {
  formatter: function(params) {
    return echarts.format.encodeHTML(params.name) +
      ': <b>' + echarts.format.encodeHTML(params.value) + '</b>';
  }
}
```

### HTML Encoding Mapping
```
'&' → '&amp;'
'<' → '&lt;'
'>' → '&gt;'
'"' → '&quot;'
"'" → '&#39;'
```

### Safe Alternatives
- **String formatter** (not a function): ECharts' internal template system is safe — no XSS risk
- **`renderMode: 'richText'`**: Non-HTML template system — safe

```javascript
// Safe (string formatter):
tooltip: { formatter: '{b}: {c}' }

// Safe (richText):
tooltip: { renderMode: 'richText' }
```

## URL Validation

```javascript
// ✅ SAFE — allowlist approach
function isValidUrl(url) {
  return /^https:\/\//i.test(url);
}

// Usage
title: {
  link: isValidUrl(userInput) ? userInput : undefined
}
```

Never allow `javascript:`, `data:`, or other non-https protocols.

## ReDoS Prevention

```javascript
// ❌ DANGEROUS — untrusted regex
dataset: {
  transform: {
    type: 'filter',
    config: {
      dimension: 'name',
      reg: userSuppliedRegex  // Catastrophic backtracking risk!
    }
  }
}

// ✅ SAFE — validate regex complexity
function isValidRegex(pattern) {
  if (pattern.length > 100) return false;  // Reasonable max length
  try { new RegExp(pattern); return true; }
  catch { return false; }
}
```

## Best Practices Summary

1. **Treat all user-supplied data as untrusted**
2. **Use `echarts.format.encodeHTML()`** on any user string in HTML contexts
3. **Validate URLs** against https-only allowlist
4. **Never allow untrusted regex** in data transform filters
5. **Use DOMPurify** or similar if you must render untrusted HTML
6. **Sanitize on BOTH client and server** — client-only sanitization can be bypassed
7. **Use sandboxed iframe** for custom untrusted HTML scenarios
