---
name: github-integration
display_name: GitHub Integration
description: Work with GitHub repos, PRs, issues, and code via API
---

When working with GitHub:
- Use the GitHub MCP server tools for repository operations
- For PR reviews: fetch the diff, review each file, post comments
- For issue management: read context before responding
- Prefer API calls over cloning when possible
- Always check rate limits before bulk operations
- Never expose tokens in output or commit messages
