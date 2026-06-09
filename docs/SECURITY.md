# Security Policy

## Overview

Memorius is a local-first memory vault for AI agents. This document outlines security considerations, known vulnerabilities, and remediation plans.

## Threat Model

### Local-First Deployment
In typical deployments, Memorius runs locally with:
- REST API bound to `127.0.0.1` (no remote access)
- MCP server over stdin/stdout (no network exposure)
- Shared vault accessible to multiple agents

### Attack Vectors

| Vector | Risk Level | Description |
|--------|------------|-------------|
| Memory Poisoning | **Critical** | Malicious content stored via one agent affects other agents |
| Context Injection | **Critical** | Stored memories injected into LLM context without trust boundaries |
| Command Injection | High | Hook templates could execute arbitrary commands |
| Data Poisoning | High | False memories corrupt fact-checking results |
| Auth Bypass | High | REST API accessible without authentication by default |

## Known Vulnerabilities

### Critical (P0)

#### C1: Memory Content → LLM Context Injection
- **Location:** `memorius/context_inject.py:28-76`
- **Issue:** Memory content injected directly into LLM context without sanitization
- **Fix:** Add content boundary markers (`[MEMORY CONTENT START]...[MEMORY CONTENT END]`)

#### C2: LLM Extraction Prompt Injection
- **Location:** `memorius/llm_extract.py:36-69`
- **Issue:** User-provided conversation text concatenated into extraction prompt
- **Fix:** Sanitize conversation text before extraction

### High (P1)

#### H1: Command Injection via Hook Templates
- **Location:** `memorius/hooks/engine.py:449-478`
- **Issue:** Context values substituted into commands without validation
- **Fix:** Validate context values for shell metacharacters

#### H2: Data Poisoning → Fact-Check Manipulation
- **Location:** `memorius/factcheck.py:89-167`
- **Issue:** False memories can corrupt fact-checking results
- **Fix:** Implement trust scoring based on memory provenance

### Medium (P2)

#### M1: System Prompt Injection
- **Location:** `memorius/context_inject.py:91-96`
- **Issue:** Memory content injected into system prompts without marking as untrusted
- **Fix:** Mark memory content as `[UNTRUSTED USER CONTENT]`

#### M2: Template Injection
- **Location:** `memorius/hooks/engine.py:527-532`
- **Issue:** Simple string replacement without validation
- **Fix:** Escape template-like patterns in context values

## Security Best Practices

### For Users

1. **Enable Authentication**
   ```bash
   export MEMORIUS_API_KEY="your-secure-key"
   memorius serve-rest
   ```

2. **Use Per-Agent Vaults**
   ```bash
   memorius store "sensitive data" --vault agent-specific
   ```

3. **Review Stored Memories**
   ```bash
   memorius ls --vault main
   memorius search "suspicious content"
   ```

4. **Monitor Logs**
   ```bash
   # Check for injection attempts
   grep -i "ignore.*instructions" ~/.memorius/data/
   ```

### For Developers

1. **Never Trust Memory Content**
   ```python
   # Always mark memory content as untrusted
   content = f"[UNTRUSTED]\n{memory.content}\n[/UNTRUSTED]"
   ```

2. **Validate All Inputs**
   ```python
   # Use the validation helpers
   from memorius.vault import _validate_name
   vault = _validate_name(user_input, "vault")
   ```

3. **Sanitize for LLM Context**
   ```python
   # Escape potential injection markers
   content = content.replace("[", "\\[").replace("]", "\\]")
   ```

4. **Implement Trust Scoring**
   ```python
   def calculate_trust(memory):
       score = 0.5  # Base score
       if memory.metadata.get("source") == "conversation":
           score += 0.2
       if memory.metadata.get("extraction_method") == "llm":
           score -= 0.1
       return score
   ```

## Reporting Security Issues

If you discover a security vulnerability, please report it responsibly:

1. **Do NOT** open a public GitHub issue
2. Email: dimona.patrick@gmail.com
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Security Changelog

### v0.2.0 (2026-06-05)
- Added API key authentication for REST API
- Added input validation for MCP and REST endpoints
- Added name validation to prevent path traversal
- Added SSRF protection for webhook actions
- Added command injection prevention via `shlex.split()`

### v0.1.0 (Initial Release)
- Basic security features
- Local-only binding default
- Parameterized SQL queries
- Safe YAML loading
