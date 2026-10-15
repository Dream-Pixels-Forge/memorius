# Memorius Security Requirements

## Zero-Trust Security & Authentication

### Password Storage
- **Not Applicable**: Memorius does not store user passwords as it is an agent memory vault
- **Alternative**: Uses API key authentication for REST server access

### Session Cookies
- **Not Applicable**: Memorius does not use traditional web session cookies
- **Alternative**: MCP server uses stdio transport; REST server uses bearer token auth

### JWTs (if used)
- **Not Used**: Memorius uses API key authentication instead of JWTs
- **Justification**: Simpler threat model appropriate for memory vault use case
- **Compensating Control**: API keys are short-lived and rotatable via environment variables

### CSRF Protection
- **Not Applicable**: CSRF protection is for browser-based applications
- **Memorius Context**: Primarily used via MCP (stdio) or programmatic API access
- **REST Server Protection**: Relies on API key authentication which prevents unauthorized access

### Input Sanitization & Schema Validation
- **Requirements**:
  - All inputs validated at edge using strict schemas
  - Zero trust in client/provided payloads
  - Sanitization to prevent injection attacks
- **Implementation**:
  - Name validation: `^[a-zA-Z0-9_\-]+$`, max 1000 chars
  - Memory ID validation: Must be valid UUID (prevents path traversal)
  - Content limits: Max 100KB for storage
  - Search limits: Max 100 results for queries
  - Metadata validation: Strict schema validation for all inputs
  - Template injection protection: Strips dangerous template syntax
  - Command injection prevention: Uses `shlex.split()` with `shell=False`

### SQL Injection Prevention
- **Requirements**:
  - 100% parameterized queries or type-safe query builders
  - No string interpolation in SQL queries
- **Implementation**:
  - SQLiteStore uses parameterized queries via SQLite3 API
  - ChromaDB uses native query API which is injection-safe
  - No raw SQL string concatenation in codebase
  - Static analysis confirms absence of vulnerable patterns

### XSS & Injection Headers
- **Requirements**:
  - `Content-Security-Policy` to prevent XSS
  - `X-Content-Type-Options: nosniff` to prevent MIME sniffing
  - `X-Frame-Options: DENY` to prevent clickjacking
  - `Referrer-Policy: strict-origin-when-cross-origin` for referrer control
  - `Strict-Transport-Security` for HTTPS enforcement
- **Implementation**:
  - REST server (FastAPI) provides some baseline protections
  - Need to explicitly set these headers in middleware
  - doctor.py includes security checks for path traversal and HTML injection

### Rate Limiting & DoS Defense
- **Requirements**:
  - Redis-backed token bucket or sliding window algorithm
  - Per IP and per authenticated user/tenant rate limiting
  - Protection against credential stuffing and brute force
- **Implementation**:
  - REST server: 500 requests/min per IP (basic implementation)
  - **Gap**: MCP server lacks rate limiting
  - **Gap**: No sliding window algorithm or per-tenant limits
  - **Needed**: Enhance rate limiting for both REST and MCP servers

### Secrets Management
- **Requirements**:
  - Runtime configuration validated on startup against strict schema
  - No secrets in repository or build layers
  - Immediate failure on missing/invalid required secrets
- **Implementation**:
  - Configuration validated via pydantic models (config.py)
  - All secrets expected via environment variables
  - No hardcoded secrets in repository
  - Startup validation ensures required configuration exists

### Secrets Scanning
- **Requirements**:
  - GitLeaks or TruffleHog runs in CI pre-merge
  - Detection of accidental secret commits (API keys, tokens, credentials)
  - Zero tolerance for secrets in repository history
- **Implementation Status**: **MISSING**
- **Required**: Add secrets scanning to CI pipeline

### Dependency Vulnerability Audit
- **Requirements**:
  - `pnpm audit --audit-level=high` or `npm audit` enforced in CI
  - Fail on HIGH/CRITICAL CVEs
  - No unaudited transitive dependencies
- **Implementation Status**: **MISSING**
- **Required**: Add dependency vulnerability audit to CI pipeline

## Application-Specific Security Considerations

### Memory Content Trust Model
- **Requirement**: Treat all memory content as untrusted data
- **Implementation**:
  - Prompt injection protection in context injection
  - HTML escaping in graph visualizer
  - Template recursion depth limiting
  - UUID validation on all memory ID inputs
  - Content length limits preventing DoS via large payloads

### Webhook Security
- **Requirements**:
  - Cryptographic signature verification for incoming webhooks
  - Raw body verification before JSON parsing
  - HMAC signature validation with secret key
- **Implementation Status**: **PARTIAL**
- **Located**: hook engine webhook action
- **Needed**: Explicit cryptographic verification for supported webhook providers

### Agent Authentication & Authorization
- **Requirements**:
  - Strong agent identity verification
  - Principle of least privilege for agent capabilities
  - Audit trail of agent actions
- **Implementation**:
  - MCP server uses stdio transport (inherits caller's security)
  - REST server uses API key authentication
  - Hook engine provides agent action audit trail
  - **Gap**: No fine-grained authorization for different agent capabilities
  - **Needed**: Role-based access control for agent capabilities

## Security Testing Requirements

### Unit Tests
- [ ] Validate all input validation edge cases
- [ ] Test UUID validation rejects malformed IDs
- [ ] Test content length limits are enforced
- [ ] Test name validation rejects dangerous characters
- [ ] Test template injection protection
- [ ] Test command injection prevention

### Integration Tests
- [ ] Test API key authentication is required for REST server
- [ ] Test rate limiting triggers appropriately
- [ ] Test MCP server accessibility controls
- [ ] Test webhook signature verification (when implemented)
- [ ] Test secrets handling failures appropriately

### Security Scanning
- [ ] Run dependency vulnerability audit in CI
- [ ] Run secrets scanning in CI
- [ ] Perform periodic container image scanning
- [ ] Conduct regular dependency license scanning

## Security Monitoring & Incident Response

### Logging Requirements
- [ ] All authentication attempts logged (success/failure)
- [ ] All access control decisions logged
- [ ] Security-relevant events structured for SIEM ingestion
- [ ] No sensitive data (secrets, tokens) in logs

### Alerting Thresholds
- [ ] Repeated authentication failures trigger alerts
- [ ] Rate limiting violations trigger investigative alerts
- [ ] Unexpected access patterns trigger investigation
- [ ] Sign verification failures trigger immediate alerts

## Compliance & Regulatory Considerations

### Data Protection
- [ ] GDPR-compatible data deletion via `memorius delete`
- [ ] Ability to export user data via `memorius export`
- [ ] Data minimization principles followed
- [ ] Purpose limitation enforced through vault/shelf/folder structure

### Audit Trail
- [ ] All memory modifications tracked (create/update/delete)
- [ ] Agent actions attributable to specific identities
- [ ] Timestamps stored in UTC for global consistency
- [ ] Immutable audit trail for critical operations

## Security Hardening Checklist for Implementation

### Code-Level
- [ ] All inputs validated at trust boundary
- [ ] All outputs encoded for their context
- [ ] All database queries use parameterized statements
- [ ] All file operations validate paths are within allowed directories
- [ ] All subprocess calls use `shell=False` and validated arguments
- [ ] All temporary files created securely with proper permissions
- [ ] All encryption uses industry-standard algorithms and key lengths

### Configuration-Level
- [ ] No default credentials or secrets
- [ ] All security-relevant settings require explicit configuration
- [ ] Security settings have safe failure modes (fail closed)
- [ ] Configuration schema validates all inputs
- [ ] Secrets never logged or exposed in error messages

### Deployment-Level
- [ ] Running services drop privileges after startup
- [ ] Services bind to specific interfaces (not 0.0.0.0 unless required)
- [ ] All network communications encrypted in transit (where applicable)
- [ ] Container images scanned for vulnerabilities before deployment
- [ ] Host-level access controls restrict service accessibility