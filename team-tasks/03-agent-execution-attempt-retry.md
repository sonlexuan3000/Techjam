# Task 03 — Agent Execution Gateway, Capabilities và Run Correlation

- **Owner:** VinhLuu25
- **Status:** In progress
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

Public Playground API vẫn trả HTTP `202` như trước với Agent không thuộc active
Coordination Run. Sau bước tích hợp của Task 05, Agent đang được giữ cho việc
nhóm trả `409`. Coordinator dùng `completion` nội bộ để không phải poll HTTP.

`start()` trả `AgentStartResult`: `{ ok: true, handle }` hoặc
`{ ok: false, code, error }`. Expected admission failures không throw và không
đòi Task 01/02 parse HTTP code hoặc error string.

## Checklist implementation

- [ ] Extract managed Run primitive từ existing `sendMessage()` và truyền
  `origin` vào trước atomic admission để integration phân biệt Playground với
  managed Planner/Worker.
- [ ] Giữ nguyên behavior của single-Agent Playground khi Agent không được giữ
  bởi active Coordination Run.
- [ ] Giữ atomic one-active-Run-per-Agent admission.
- [ ] Planner và Worker đều đi qua existing AgentService/AgentRunner.
- [ ] Thêm Run origin/correlation metadata cho coordination.
- [ ] Không truyền Ark key vào prompt, DB, response hoặc log.
- [ ] Thêm `capabilities?: string[]` vào `CreateAgentInput`/`UpdateAgentInput` và
  hỗ trợ create/update persistence (Task 05 chỉ nối Zod route body).
- [ ] Normalize capability lowercase, trim và deduplicate.
- [ ] Map expected start failures vào đúng code:
  `busy | stopped | not_found | not_configured | internal`.
- [ ] Không tạo AgentRun khi admission trả `ok: false`.
- [ ] `cancel(runId)` chỉ cancel nếu đúng Run đó vẫn active trên Agent.
- [ ] Terminal/unknown Run cancel là idempotent no-op.
- [ ] Managed completion luôn trả persisted terminal AgentRun.
- [ ] Managed coordination failure/cancel cleanup Agent về `ready`; lỗi vẫn nằm
  trên AgentRun để Task 01 quyết định retry.
- [ ] Playground failure behavior hiện có không bị đổi với Run đã được nhận.

## Boundary semantics

Gateway chỉ quản lý lifecycle của baseline AgentRun. Coordinator quyết định một
AgentRun completion có còn là current attempt để commit task output hay không.
Không dùng lease token hoặc heartbeat.

Atomic guard cho public Agent lifecycle và Playground admission thuộc Task 05 sau
Database v2 migration. Task 03 phải để admission nhận biết `origin`, nhưng không
import `CoordinationAgentGuard`/`DatabaseV2`, không đọc coordination arrays và
không duplicate coordination state; một shared-file conflict nhỏ trong
`agent-service.ts` khi Task 05 merge sau là chấp nhận được.

## Automated tests

- [ ] Existing Playground conversation vẫn persist.
- [ ] Normal Playground admission vẫn persist Run/Message; HTTP `202` và
  coordination-reservation cases thuộc integration tests của Task 05.
- [ ] Existing one-active-Run-per-Agent test vẫn pass.
- [ ] Managed Run trả completion promise đúng terminal state.
- [ ] Correlation metadata đúng task/attempt.
- [ ] Busy admission trả conflict và không tạo orphan AgentRun.
- [ ] Mọi expected admission failure trả discriminated result, không throw.
- [ ] Managed failed Run đưa Agent về `ready`, nên một-Worker retry vẫn khả thi.
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
