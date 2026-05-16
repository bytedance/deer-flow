# DeerFlow Smoke Test Report

**Test Date**: {{test_date}}  
**Test Environment**: {{test_environment}}  
**Deployment Mode**: Local  
**Test Version**: {{git_commit}}

---

## Execution Summary

| Metric | Status |
|------|------|
| Total Test Phases | 6 |
| Passed Phases | {{passed_stages}} |
| Failed Phases | {{failed_stages}} |
| Overall Conclusion | **{{overall_status}}** |

### Key Test Cases

| Case | Result | Details |
|------|--------|---------|
| Code update check | {{case_code_update}} | {{case_code_update_details}} |
| Environment check | {{case_env_check}} | {{case_env_check_details}} |
| Configuration preparation | {{case_config_prep}} | {{case_config_prep_details}} |
| Deployment | {{case_deploy}} | {{case_deploy_details}} |
| Health check | {{case_health_check}} | {{case_health_check_details}} |
| Frontend routes | {{case_frontend_routes_overall}} | {{case_frontend_routes_details}} |

---

## Detailed Test Results

### Phase 1: Code Update Check

- [x] Confirm current directory - {{status_dir_check}}
- [x] Check Git status - {{status_git_status}}
- [x] Pull latest code - {{status_git_pull}}
- [x] Confirm code update - {{status_git_verify}}

**Phase Status**: {{stage1_status}}

---

### Phase 2: Local Environment Check

- [x] Node.js version - {{status_node_version}}
- [x] pnpm - {{status_pnpm}}
- [x] uv - {{status_uv}}
- [x] nginx - {{status_nginx}}
- [x] Port check - {{status_port_check}}

**Phase Status**: {{stage2_status}}

---

### Phase 3: Configuration Preparation

- [x] config.yaml - {{status_config_yaml}}
- [x] .env file - {{status_env_file}}
- [x] Model configuration - {{status_model_config}}

**Phase Status**: {{stage3_status}}

---

### Phase 4: Local Deployment

- [x] make check - {{status_make_check}}
- [x] make install - {{status_make_install}}
- [x] make dev-daemon / make dev - {{status_local_start}}
- [x] Service startup wait - {{status_wait_startup}}

**Phase Status**: {{stage4_status}}

---

### Phase 5: Service Health Check

- [x] Process status - {{status_processes}}
- [x] Frontend service - {{status_frontend}}
- [x] API Gateway - {{status_api_gateway}}
- [x] LangGraph service - {{status_langgraph}}

**Phase Status**: {{stage5_status}}

---

### Frontend Routes Smoke Results

| Route | Status | Details |
|-------|--------|---------|
| Landing `/` | {{landing_status}} | {{landing_details}} |
| Workspace redirect `/workspace` | {{workspace_redirect_status}} | target {{workspace_redirect_target}} |
| New chat `/workspace/chats/new` | {{new_chat_status}} | {{new_chat_details}} |
| Chats list `/workspace/chats` | {{chats_list_status}} | {{chats_list_details}} |
| Agents gallery `/workspace/agents` | {{agents_gallery_status}} | {{agents_gallery_details}} |
| Docs `{{docs_path}}` | {{docs_status}} | {{docs_details}} |

**Summary**: {{frontend_routes_summary}}

---

### Phase 6: Test Report Generation

- [x] Result summary - {{status_summary}}
- [x] Issue log - {{status_issues}}
- [x] Report generation - {{status_report}}

**Phase Status**: {{stage6_status}}

---

## Issue Log

### Issue 1
**Description**: {{issue1_description}}  
**Severity**: {{issue1_severity}}  
**Solution**: {{issue1_solution}}

---

## Environment Information

### Local Dependency Versions
```text
Node.js: {{node_version_output}}
pnpm: {{pnpm_version_output}}
uv: {{uv_version_output}}
nginx: {{nginx_version_output}}
```

### Git Information
```text
Repository: {{git_repo}}
Branch: {{git_branch}}
Commit: {{git_commit}}
Commit Message: {{git_commit_message}}
```

### Configuration Summary
- config.yaml exists: {{config_exists}}
- .env file exists: {{env_exists}}
- Number of configured models: {{model_count}}

---

## Local Service Status

| Service | Status | Endpoint |
|---------|--------|----------|
| Nginx | {{nginx_status}} | {{nginx_endpoint}} |
| Frontend | {{frontend_status}} | {{frontend_endpoint}} |
| Gateway | {{gateway_status}} | {{gateway_endpoint}} |
| LangGraph | {{langgraph_status}} | {{langgraph_endpoint}} |

---

## Recommendations and Next Steps

### If the Test Passes
1. [ ] Visit http://localhost:2026 to start using DeerFlow
2. [ ] Configure your preferred model if it is not configured yet
3. [ ] Explore available skills
4. [ ] Refer to the documentation to learn more features

### If the Test Fails
1. [ ] Review references/troubleshooting.md for common solutions
2. [ ] Check local logs: `logs/{langgraph,gateway,frontend,nginx}.log`
3. [ ] Verify configuration file format and content
4. [ ] If needed, fully reset the environment: `make stop && make clean && make install && make dev-daemon`

---

## Appendix

### Full Logs
{{full_logs}}

### Tester
{{tester_name}}

---

*Report generated at: {{report_time}}*
