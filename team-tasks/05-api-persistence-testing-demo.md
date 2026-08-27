# Task 05 — API, Persistence, Integration Tests và Demo

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-05-api-persistence-tests`
- **Reviewer:** `@sonlexuan3000`

**Shared contract:** [Coordination MVP Contracts v1](./CONTRACTS.md)

## Mục tiêu

Nối các module MVP vào Fastify/JsonStore, cung cấp API cho frontend, persist
coordination state và xây end-to-end evidence có thể tái hiện khi chấm bài.

Task này không đưa scheduling logic vào route; route chỉ validate request và gọi
CoordinationService.

## Files sở hữu chính

```text
apps/server/src/types.ts              # Database v2 composition only
apps/server/src/store.ts
apps/server/src/app.ts
apps/server/src/index.ts
apps/server/src/config.ts
apps/server/src/app.test.ts
apps/server/src/coordination-integration.test.ts
README.md
docs/MULTI_AGENT_ARCHITECTURE.md
docs/DEMO.md
```

## API tối thiểu

```text
POST /api/coordination-runs
GET  /api/coordination-runs
GET  /api/coordination-runs/:id
```

Nếu còn thời gian:

```text
POST /api/coordination-runs/:id/stop
```

Create input:

```json
{
  "prompt": "Compare two approaches and recommend one",
  "plannerAgentId": "uuid",
  "workerAgentIds": ["uuid-a", "uuid-b", "uuid-c"]
}
```

Create trả HTTP `202` với Coordination Run trạng thái `planning`.

Detail response phải cung cấp một snapshot nhất quán:

```json
{
  "coordinationRun": {},
  "tasks": [],
  "attempts": [],
  "events": [],
  "latestSequence": 0
}
```

## Persistence

- [ ] Persist Coordination Runs.
- [ ] Persist Tasks.
- [ ] Persist Attempts.
- [ ] Persist Events.
- [ ] Có migration/normalization cho baseline database hiện tại.
- [ ] Browser refresh vẫn đọc được run.
- [ ] Server restart không để task giả ở trạng thái running.
- [ ] Event history có giới hạn; không lưu raw Codex stdout.
- [ ] Không lưu credential hoặc environment value.

## Controlled failure fixture

Live demo cần failure deterministic. Thêm development/demo-only fixture rõ ràng:

```text
timeout-first-worker-attempt
```

Yêu cầu:

- [ ] Chỉ hoạt động khi explicit demo config được bật.
- [ ] Emit `demo_fault_injected`.
- [ ] Task bị inject có ít nhất hai capable Workers và retry chọn Agent khác.
- [ ] Fixture có thể không cancel old Run để chứng minh late result bị reject.
- [ ] Không tạo hard-coded successful output.
- [ ] Retry Worker vẫn gọi real Agent qua Starter Kit.
- [ ] Có automated test với fake execution gateway.
- [ ] README nói rõ đây là controlled fixture được dùng để tái hiện recovery.

## Integration tests

- [ ] HTTP create Coordination Run trả `202`.
- [ ] Create trả trước khi Planner/Workers hoàn tất.
- [ ] Active Coordination Run thứ hai bị reject `409`.
- [ ] Invalid Agent IDs bị reject.
- [ ] Stopped/busy Planner bị reject hoặc trả lỗi rõ.
- [ ] Không đủ Workers bị reject.
- [ ] Valid Planner output tạo persisted DAG.
- [ ] Hai ready tasks chạy song song với fake gateway.
- [ ] Timeout requeue và tạo attempt 2.
- [ ] Old attempt completion tạo stale event.
- [ ] Final task unlock và complete run.
- [ ] Max attempts tạo failed run.
- [ ] List/detail API trả dữ liệu đúng sau refresh/reinitialize.
- [ ] Existing `/api/agents` và Playground API tests vẫn pass.
- [ ] Update capabilities/stop/delete selected Agent trong active run bị reject.

## Submission documentation

README cuối cùng cần có:

- Middleware problem và rationale.
- Provided Starter Kit versus team-added components.
- Architecture boundary.
- Required env: `ARK_API_KEY`, `ARK_MODEL`, optional `ARK_BASE_URL`.
- One-command local startup.
- Agent/capability setup cho demo.
- Automated test command.
- Three-minute demo steps.
- Failure/recovery evidence.
- Known limitations.
- Không chứa secret hoặc screenshot có key.

Architecture page cần thể hiện:

```text
React UI
→ Fastify
→ CoordinationService
→ Planner/Graph Validator/Scheduler/Attempt Guard/Event Store
→ AgentService
→ AgentRunner
→ Codex CLI
→ ModelArk
```

## Three-minute demo acceptance

- [ ] Chọn hoặc tạo Planner và Workers.
- [ ] Gửi một goal thật từ UI.
- [ ] Planner thật đề xuất DAG.
- [ ] Hai tasks chạy song song.
- [ ] Một attempt timeout có kiểm soát.
- [ ] Task được requeue cho Agent khác.
- [ ] Old result bị reject nếu quay lại.
- [ ] Downstream task được unlock.
- [ ] Final output hiển thị.
- [ ] Event history chứng minh toàn bộ flow.
- [ ] Platform vẫn hiểu và điều khiển được sau failure.

## Definition of Done

- Fresh clone có setup instructions đủ để reviewer chạy.
- `npm run check` pass.
- Demo không cần sửa DB hoặc code bằng tay.
- Không có hidden manual step ngoài documented credentials/runtime setup.
- Tất cả AI calls vẫn đi qua Starter Kit.

## Ngoài scope

- ECS/Terraform deployment.
- Production database/message broker.
- Hidden fallback DAG hoặc hard-coded model success.
- Full observability platform.
