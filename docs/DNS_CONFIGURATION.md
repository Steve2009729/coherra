# Coherra Production DNS Configuration

This document specifies the DNS routing split for Coherra's production infrastructure.

## 1. Domain Routing Architecture

| Hostname | Record Type | Value / Target | Destination Service |
|---|---|---|---|
| `coherra.xyz` (or `@` root) | `A` or `CNAME` / ALIAS | `76.76.21.21` (Vercel) / `cname.vercel-dns.com` | Next.js Frontend (Vercel) |
| `www.coherra.xyz` | `CNAME` | `cname.vercel-dns.com` | Redirect / Frontend (Vercel) |
| `api.coherra.xyz` | `CNAME` | `<service-name>.up.railway.app` (Railway) | Persistent Python x402 Server |

## 2. SSL & Protocol Specifications
- **Frontend**: Automated SSL / TLS 1.3 via Vercel Edge Network.
- **Backend API**: Automated SSL / TLS 1.3 termination via Railway Edge Proxy.
- **WebSocket / HTTP/2**: Enabled across both root and `api.` subdomains.
