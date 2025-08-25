# 🔒 Security Policy

## 🛡️ Mission Security Protocols

ProxSyncBox handles sensitive infrastructure data and credentials. We take security seriously and appreciate your help in keeping our users' infrastructure safe.

## 📊 Supported Versions

We provide security updates for the following versions:

| Version | Supported          | Status        |
| ------- | ------------------ | ------------- |
| 1.x.x   | :white_check_mark: | Active        |
| < 1.0   | :x:                | End of Life   |

## 🚨 Reporting a Vulnerability

### Priority Levels

- **🔴 Critical:** Remote code execution, credential exposure, data destruction
- **🟠 High:** Authentication bypass, privilege escalation, data leakage
- **🟡 Medium:** Cross-site scripting, denial of service, information disclosure
- **🟢 Low:** Minor information leaks, non-exploitable crashes

### Reporting Process

1. **DO NOT** create a public issue for security vulnerabilities

2. **Email us directly** at: security@proxsyncbox.dev
   
3. **Include in your report:**
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)
   - Your contact information

4. **Encryption (optional but recommended):**
   ```
   GPG Key: [Will be provided]
   Fingerprint: [Will be provided]
   ```

### Response Timeline

- **Initial Response:** Within 24 hours
- **Status Update:** Within 72 hours
- **Resolution Target:**
  - Critical: 7 days
  - High: 14 days
  - Medium: 30 days
  - Low: 60 days

## 🛡️ Security Best Practices

### For Users

1. **Credential Management:**
   - Never commit `.env` files
   - Use strong, unique API tokens
   - Rotate tokens regularly
   - Use read-only tokens when possible

2. **Network Security:**
   - Use HTTPS for NetBox connections
   - Enable SSL verification for Proxmox
   - Restrict API access by IP when possible
   - Use VPN for remote access

3. **Access Control:**
   - Follow principle of least privilege
   - Use separate tokens for dev/prod
   - Audit token permissions regularly
   - Monitor sync logs for anomalies

### For Contributors

1. **Code Security:**
   - Validate all inputs
   - Use parameterized queries
   - Avoid shell command injection
   - Handle errors gracefully

2. **Dependency Management:**
   - Keep dependencies updated
   - Review dependency changes
   - Use lock files
   - Scan for vulnerabilities

3. **Secret Handling:**
   - Never hardcode credentials
   - Use environment variables
   - Implement secure token storage
   - Clear sensitive data from memory

## 🔍 Security Features

### Current Security Measures

- ✅ Encrypted token storage in `.env`
- ✅ SSL/TLS support for API connections
- ✅ Input validation for NetBox fields
- ✅ Secure credential handling in memory
- ✅ No credential logging
- ✅ Support for read-only operations

### Planned Security Enhancements

- 🔄 Encrypted configuration files
- 🔄 Token encryption at rest
- 🔄 Audit logging
- 🔄 Rate limiting
- 🔄 MFA support
- 🔄 Secret rotation automation

## 🚀 Security Checklist for Releases

Before each release, we ensure:

- [ ] Dependencies are up to date
- [ ] Security scanning passes (Bandit, Safety)
- [ ] No hardcoded secrets (detect-secrets)
- [ ] Input validation is comprehensive
- [ ] Error messages don't leak sensitive info
- [ ] Documentation includes security guidance
- [ ] CHANGELOG mentions security fixes

## 📚 Security Resources

### Tools We Use

- **Bandit:** Python security linting
- **Safety:** Dependency vulnerability scanning
- **detect-secrets:** Pre-commit secret detection
- **CodeQL:** GitHub security scanning

### Running Security Checks

```bash
# Run security scan
mise run security

# Check dependencies
safety check

# Scan for secrets
detect-secrets scan

# Full CI security check
mise run ci
```

## 🏆 Security Hall of Fame

We gratefully acknowledge security researchers who have helped improve ProxSyncBox:

- *Your name could be here!*

## 📞 Contact

- **Security Issues:** security@proxsyncbox.dev
- **General Questions:** Use GitHub Discussions
- **Urgent:** Contact maintainers directly via GitHub

## 🤝 Responsible Disclosure

We support responsible disclosure and will:

1. Acknowledge your report promptly
2. Keep you informed of progress
3. Credit you in security advisories (unless you prefer anonymity)
4. Not pursue legal action for good-faith reports

## 📋 Security Advisories

Security advisories are published at:
- GitHub Security Advisories
- Project CHANGELOG
- Release notes

---

**Remember:** Security is everyone's responsibility. If you see something, say something! 🛡️