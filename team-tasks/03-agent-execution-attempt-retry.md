# Task 03 — Agent Execution Gateway, Capabilities và Run Correlation

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-03-agent-execution`
- **Reviewer:** `@sonlexuan3000`

**Shared contract:** [Coordination MVP Contracts v1](./CONTRACTS.md)

## Mục tiêu

Tạo một internal execution boundary để CoordinationService gọi Planner/Worker
qua `AgentService` và `AgentRunner` hiện có, đồng thời lưu correlation giữa
Coordination Task, Attempt và baseline AgentRun.

Task này không sở hữu task timeout, retry/requeue hoặc stale-result state
transition; các phần đó thuộc Task 01. MVP không có lease.

## Files sở hữu chính

```text
apps/server/src/agent-execution-gateway.ts
apps/server/src/agent-service.ts
apps/server/src/types.ts
apps/server/src/agent-service.test.ts
apps/server/src/agent-execution-gateway.test.ts
```

## Internal interface cần cung cấp

```ts
type AgentExecutionGateway =
  import("./coordination-types.js").AgentExecutionGateway;
```

Public Playground API vẫn trả HTTP `202` như trước. Coordinator dùng
`completion` nội bộ để không phải poll HTTP.

## Checklist implementation

- [ ] Extract managed Run primitive từ existing `sendMessage()`.
- [ ] Giữ nguyên behavior của single-Agent Playground.
- [ ] Giữ atomic one-active-Run-per-Agent admission.
- [ ] Planner và Worker đều đi qua existing AgentService/AgentRunner.
- [ ] Thêm Run origin/correlation metadata cho coordination.
- [ ] Không truyền Ark key vào prompt, DB, response hoặc log.
- [ ] Hỗ trợ Agent capabilities trong create/update persistence.
- [ ] Normalize capability lowercase, trim và deduplicate.
- [ ] Reject capability update/stop/delete Agent thuộc active Coordination Run.
- [ ] `cancel(runId)` chỉ cancel nếu đúng Run đó vẫn active trên Agent.
- [ ] Terminal/unknown Run cancel là idempotent no-op.
- [ ] Managed completion luôn trả persisted terminal AgentRun.
- [ ] Admission conflict giữ status code/meaning để scheduler xử lý được.

## Boundary semantics

Gateway chỉ quản lý lifecycle của baseline AgentRun. Coordinator quyết định một
AgentRun completion có còn là current attempt để commit task output hay không.
Không dùng lease token hoặc heartbeat.

## Automated tests

- [ ] Existing Playground conversation vẫn persist.
- [ ] Existing one-active-Run-per-Agent test vẫn pass.
- [ ] Managed Run trả completion promise đúng terminal state.
- [ ] Correlation metadata đúng task/attempt.
- [ ] Busy admission trả conflict và không tạo orphan AgentRun.
- [ ] Cancel theo Run ID map đúng Agent.
- [ ] Cancel Run A muộn không cancel Run B mới trên cùng Agent.
- [ ] Cancellation không để Agent kẹt `busy`.

## Definition of Done

- Không gọi `AgentRunner` trực tiếp từ frontend hoặc API route.
- Không duplicate workspace/session/status logic của AgentService.
- Baseline tests không thay đổi semantics.
- Managed execution/cancellation/correlation có automated evidence.
- `npm run check` pass.

## Ngoài scope

- Phân loại mọi transient error một cách production-grade.
- Lease/heartbeat/renewal.
- Retry budget theo cost/token.
- Per-task model routing.
