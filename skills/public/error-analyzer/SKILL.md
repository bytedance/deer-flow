---
name: error-analyzer
description: Use this skill when encountering errors, exceptions, bugs, or unexpected behavior in code. Provides systematic error analysis, root cause identification, and solution strategies. Trigger when user reports an error message, asks "why is this not working", "debug this", "fix this error", or shows stack traces, error logs, or failing test output.
---

# Error Analyzer Skill

## Overview

This skill provides a systematic methodology for analyzing and resolving errors, exceptions, and bugs in software development. It transforms chaotic debugging into a structured, efficient process that identifies root causes and delivers actionable solutions.

## When to Use This Skill

**Always load this skill when:**

- User shares an error message, exception, or stack trace
- User asks "why is this not working?" or "debug this"
- User reports unexpected behavior or output
- User shows failing tests or CI/CD errors
- User needs help interpreting log files
- User is troubleshooting a production issue
- User wants to understand why code crashes or behaves incorrectly

## Core Capabilities

- **Error Classification**: Categorize errors by type (syntax, runtime, logical, network, etc.)
- **Root Cause Analysis**: Systematically identify the underlying cause, not just symptoms
- **Solution Generation**: Provide specific, actionable fixes with code examples
- **Prevention Strategies**: Suggest patterns and practices to prevent similar errors
- **Documentation**: Generate clear explanations for future reference

## Error Analysis Methodology

### Phase 1: Error Identification & Classification

#### Step 1.1: Parse the Error Signal

Extract key information from the error:

| Signal Type | What to Extract |
|------------|-----------------|
| **Error Message** | Exact text, error code/type |
| **Stack Trace** | File paths, line numbers, function calls |
| **Context** | What operation triggered it, input data |
| **Environment** | Language version, OS, dependencies |
| **Timing** | When it occurs (startup, runtime, specific action) |

#### Step 1.2: Classify Error Type

| Error Category | Indicators | Examples |
|---------------|------------|----------|
| **Syntax Error** | Parse errors, unexpected tokens | Missing semicolon, unmatched brackets |
| **Type Error** | Type mismatches, undefined methods | `undefined is not a function`, type coercion issues |
| **Reference Error** | Undefined variables, null access | `Cannot read property 'x' of undefined` |
| **Runtime Error** | Crashes during execution | Division by zero, stack overflow, out of memory |
| **Network Error** | Connection issues, timeouts | ECONNREFUSED, ETIMEDOUT, CORS errors |
| **Logic Error** | Wrong output, no crash | Incorrect algorithm, off-by-one errors |
| **Configuration Error** | Missing config, wrong settings | Missing environment variables, invalid config |
| **Dependency Error** | Package issues, version conflicts | Module not found, peer dependency warnings |
| **Permission Error** | Access denied, insufficient privileges | EACCES, authentication failures |
| **Resource Error** | File not found, disk full | ENOENT, database connection exhausted |

#### Step 1.3: Assess Severity & Urgency

- **Critical**: Production down, data loss risk, security vulnerability
- **High**: Core functionality broken, affects multiple users
- **Medium**: Feature partially working, workaround exists
- **Low**: Minor issue, cosmetic, edge case

### Phase 2: Root Cause Analysis

#### Step 2.1: Reproduce the Error

Document exact reproduction steps:

```markdown
## Reproduction Steps
1. Prerequisites: [Environment setup, dependencies]
2. Action: [Exact steps to trigger]
3. Expected: [What should happen]
4. Actual: [What happens instead]
```

#### Step 2.2: Apply Analysis Frameworks

**Five Whys Technique**:
```
Problem: [Error description]
Why 1: [First level cause]
Why 2: [Deeper cause]
Why 3: [Even deeper cause]
Why 4: [Root contributor]
Why 5: [Fundamental root cause]
```

**Fishbone (Ishikawa) Diagram** for complex errors:

| Category | Questions to Ask |
|----------|-----------------|
| **People** | Developer error? Misunderstanding? Training gap? |
| **Process** | Missing validation? Incomplete testing? Poor error handling? |
| **Technology** | Library bug? Version incompatibility? Platform issue? |
| **Data** | Bad input? Missing data? Data format issue? |
| **Environment** | Config difference? Resource limitation? Network issue? |
| **Time** | Race condition? Timeout? Order dependency? |

#### Step 2.3: Isolate the Problem

Narrow down the cause:

1. **Binary Search**: Comment out half the code, see if error persists
2. **Minimal Reproduction**: Create smallest code that reproduces error
3. **Dependency Check**: Test with different versions of dependencies
4. **Environment Compare**: Compare working vs. failing environments
5. **Input Analysis**: Test with different inputs to find pattern

### Phase 3: Solution Generation

#### Step 3.1: Solution Options Matrix

For each potential solution, evaluate:

| Solution | Effort | Risk | Effectiveness | Recommendation |
|----------|--------|------|---------------|----------------|
| [Option 1] | Low/Med/High | Low/Med/High | Partial/Complete | Recommended/Alternative/Not advised |
| [Option 2] | ... | ... | ... | ... |

#### Step 3.2: Generate Specific Fixes

Provide concrete code changes:

```markdown
## Solution

### Root Cause
[Clear explanation of what was wrong]

### Fix
[Exact code change with before/after]

### Explanation
[Why this fix works]

### Alternative Approaches
[Other valid solutions if applicable]
```

#### Step 3.3: Validation Checklist

After applying fix, verify:

- [ ] Error no longer occurs
- [ ] Original functionality works
- [ ] No new errors introduced
- [ ] Edge cases handled
- [ ] Tests pass (add new test if applicable)
- [ ] Documentation updated

### Phase 4: Prevention & Documentation

#### Step 4.1: Prevention Strategies

Suggest patterns to prevent recurrence:

| Error Type | Prevention Pattern |
|-----------|-------------------|
| Null/Undefined Access | Optional chaining, null checks, default values |
| Type Errors | TypeScript, runtime validation, input sanitization |
| Network Errors | Retry logic, timeouts, circuit breakers, fallbacks |
| Logic Errors | Unit tests, code review, static analysis |
| Configuration Errors | Validation schemas, default values, env checks |

#### Step 4.2: Error Documentation Template

```markdown
## Error Documentation

### Summary
**Error Type**: [Category]
**Severity**: [Critical/High/Medium/Low]
**Status**: [Resolved/Workaround/Open]

### Details
**Error Message**: 
```
[Paste exact error]
```

**Stack Trace**:
```
[Paste relevant stack trace]
```

**Environment**:
- Language/Version: [e.g., Node.js 18.17.0]
- OS: [e.g., Ubuntu 22.04]
- Dependencies: [Relevant packages and versions]

### Root Cause
[Explanation]

### Solution
[Fix description and code]

### Prevention
[How to avoid in future]

### Related
- Related errors: [Links]
- Similar issues: [Links]
```

## Common Error Patterns by Language

### JavaScript/TypeScript

| Error Pattern | Common Causes | Quick Fixes |
|--------------|---------------|-------------|
| `Cannot read property 'x' of undefined` | Null/undefined access | Optional chaining (`?.`), null checks |
| `is not a function` | Type mismatch, wrong import | Check variable type, verify export |
| `Promise rejected` | Unhandled async error | Try-catch, `.catch()`, async error handling |
| `Module not found` | Wrong path, missing package | Check import path, `npm install` |
| `Maximum call stack exceeded` | Infinite recursion | Add base case, check recursive calls |

### Python

| Error Pattern | Common Causes | Quick Fixes |
|--------------|---------------|-------------|
| `NameError: name 'x' is not defined` | Typo, scope issue | Check spelling, variable scope |
| `TypeError: 'NoneType' object...` | Function returns None | Add None check, fix function |
| `KeyError: 'key'` | Missing dict key | Use `.get()` with default |
| `ImportError/ModuleNotFoundError` | Missing package, path issue | `pip install`, check PYTHONPATH |
| `IndentationError` | Mixed tabs/spaces | Use consistent indentation |

### Java

| Error Pattern | Common Causes | Quick Fixes |
|--------------|---------------|-------------|
| `NullPointerException` | Null object access | Null checks, Optional class |
| `ClassNotFoundException` | Missing class/JAR | Check classpath, add dependency |
| `ArrayIndexOutOfBoundsException` | Wrong array index | Bounds checking |
| `ClassCastException` | Invalid type cast | `instanceof` check |
| `NumberFormatException` | Invalid string to number | Try-catch, validation |

### Go

| Error Pattern | Common Causes | Quick Fixes |
|--------------|---------------|-------------|
| `nil pointer dereference` | Nil pointer access | Check for nil before dereferencing |
| `index out of range` | Slice/array bounds | Check `len()` before access |
| `invalid memory address` | Uninitialized pointer | Initialize before use |
| `connection refused` | Service not running | Check service status, network |
| `context deadline exceeded` | Timeout | Increase timeout, check slow operations |

## Advanced Debugging Techniques

### Logging Strategy

```markdown
## Logging Levels

| Level | When to Use |
|-------|------------|
| ERROR | Failures requiring immediate attention |
| WARN | Unexpected but handled situations |
| INFO | Key business events, state changes |
| DEBUG | Detailed diagnostic information |
| TRACE | Very detailed execution flow |

## What to Log

1. **Entry/Exit**: Function start and end with parameters
2. **State Changes**: Before/after of modified data
3. **Decisions**: Branch paths taken (if/else outcomes)
4. **External Calls**: API requests, DB queries with timing
5. **Errors**: Full context when error occurs
```

### Performance Debugging

For slow code or timeouts:

1. **Profile First**: Don't guess, measure
2. **Identify Hotspots**: Find actual bottlenecks
3. **Common Culprits**:
   - N+1 queries
   - Missing indexes
   - Synchronous blocking operations
   - Large data in memory
   - Inefficient algorithms (O(n²) in loops)

### Memory Debugging

For memory leaks or OOM errors:

1. **Take Heap Snapshots**: Compare before/after
2. **Look For**: Growing arrays, unclosed connections, event listeners not removed
3. **Tools**: Language-specific profilers (Chrome DevTools, valgrind, pprof)

## Quality Checklist

### Error Analysis Quality

- [ ] Exact error message captured (not paraphrased)
- [ ] Error type correctly classified
- [ ] Root cause identified, not just symptom treated
- [ ] All relevant context considered (input, environment, timing)
- [ ] Solution addresses root cause directly
- [ ] Alternative solutions considered
- [ ] Fix validated with reproduction

### Solution Quality

- [ ] Solution is specific and actionable
- [ ] Code examples provided where applicable
- [ ] Explanation of why fix works
- [ ] Edge cases considered
- [ ] No new issues introduced
- [ ] Tests added/updated if applicable
- [ ] Prevention strategies suggested

### Documentation Quality

- [ ] Clear summary for future reference
- [ ] All relevant details captured
- [ ] Searchable keywords included
- [ ] Links to related issues
- [ ] Lessons learned documented

## Output Format

### For Simple Errors

```markdown
## Error Analysis

**Type**: [Error category]
**Severity**: [Level]

### Root Cause
[One-sentence explanation]

### Solution
[Code fix]

### Why It Works
[Explanation]
```

### For Complex Errors

```markdown
## Error Analysis Report

### Summary
- **Error**: [Type and message]
- **Severity**: [Level]
- **Status**: [Current status]

### Error Details
**Full Message**:
```
[Complete error output]
```

**Stack Trace**:
```
[Relevant portions]
```

### Root Cause Analysis
**Five Whys**:
1. Why: [Level 1]
2. Why: [Level 2]
3. Why: [Level 3]
4. Why: [Level 4]
5. Why: [Root cause]

**Contributing Factors**:
- [Factor 1]
- [Factor 2]

### Solution

**Recommended Fix**:
```language
// Before
[problematic code]

// After
[fixed code]
```

**Explanation**: [Why this fixes the issue]

**Alternative Approaches**:
1. [Alternative 1]: [Pros/Cons]
2. [Alternative 2]: [Pros/Cons]

### Validation Steps
1. [How to verify fix]
2. [Tests to run]

### Prevention
[Suggested patterns/practices]

### Related
- [Links to docs, similar issues]
```

## Examples

### Example 1: JavaScript TypeError

**Input**: User reports `TypeError: Cannot read property 'id' of undefined` when loading user profile.

**Analysis**:
```markdown
## Error Analysis

**Type**: Reference Error (Null/Undefined Access)
**Severity**: High (breaks core functionality)

### Root Cause
The code attempts to access `user.profile.id` but `user.profile` is undefined for users who haven't created a profile yet.

### Solution
```javascript
// Before
const profileId = user.profile.id;

// After
const profileId = user?.profile?.id ?? 'default-id';
```

**Why It Works**: Optional chaining (`?.`) safely handles undefined intermediate properties, and nullish coalescing (`??`) provides a fallback.

### Prevention
1. Use TypeScript interfaces to define expected shape
2. Add validation at API boundaries
3. Write tests for users without profiles
```

### Example 2: Python Import Error

**Input**: User gets `ModuleNotFoundError: No module named 'requests'` when running script.

**Analysis**:
```markdown
## Error Analysis

**Type**: Dependency Error
**Severity**: Medium (blocks execution but easy fix)

### Root Cause
The `requests` library is not installed in the current Python environment.

### Solution
```bash
# Install the missing package
pip install requests

# Or if using requirements.txt, ensure it's listed and run:
pip install -r requirements.txt
```

**Why It Works**: The package must be installed before it can be imported.

### Prevention
1. Always include a `requirements.txt` with all dependencies
2. Document setup steps in README
3. Consider using a virtual environment
4. Use `pip freeze > requirements.txt` to capture current dependencies
```

### Example 3: Network Error

**Input**: User reports `ECONNREFUSED` when connecting to database in production.

**Analysis**:
```markdown
## Error Analysis

**Type**: Network Error
**Severity**: Critical (production down)

### Root Cause Analysis
1. Why: Connection refused → Port not listening
2. Why: Port not listening → Database service not running
3. Why: Service not running → Crashed on startup
4. Why: Crashed on startup → Out of memory
5. Why: Out of memory → Memory limit too low for data volume

### Immediate Fix
1. Restart database service: `systemctl restart postgresql`
2. Check logs: `journalctl -u postgresql`

### Long-term Solution
1. Increase memory allocation
2. Optimize queries to reduce memory usage
3. Add connection pooling
4. Set up monitoring for memory usage

### Prevention
1. Add health checks and auto-restart policies
2. Implement connection retry with exponential backoff
3. Set up alerting for resource limits
4. Regular capacity planning reviews
```

## Notes

- Always reproduce the error before attempting fixes
- Start with the simplest explanation (Occam's Razor)
- Consider environmental differences (works on my machine syndrome)
- Document solutions for future reference
- When stuck, explain the problem aloud (rubber duck debugging)
- Fresh eyes help - take breaks or ask for second opinions
- Version control your debugging attempts
- Don't treat symptoms - find and fix root causes