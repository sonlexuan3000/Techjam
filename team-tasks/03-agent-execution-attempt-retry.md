# Task 03 — Agent Execution, Attempt, Timeout và Retry

- **Owner:** Chưa có
- **Status:** Unassigned
- **Suggested branch:** `feat/task-03-agent-execution`
- **Reviewer:** `@sonlexuan3000`

## Mục tiêu

Tạo một internal execution boundary để CoordinationService gọi Planner/Worker
qua `AgentService` và `AgentRunner` hiện có, đồng thời quản lý correlation giữa
Coordination Task, Attempt và baseline AgentRun.

MVP không có lease. Kết quả cũ được chặn bằng `currentAttemptId`.

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
interface AgentExecutionGateway {
  start(
    agentId: string,
    prompt: string,
    context: {
      type: "planner" | "worker";
      coordinationRunId: string;
      taskId?: string;
      attemptId?: string;
    },
  ): Promise<{
    run: AgentRun;
    completion: Promise<AgentRun>;
  }>;

  cancel(runId: string): Promise<void>;
}
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
- [ ] Worker attempt có timeout độc lập với Planner validation.
- [ ] Khi timeout, invalidate current attempt trước khi requeue.
- [ ] Best-effort cancel old AgentRun nhưng không block retry vô hạn.
- [ ] Result chỉ được accept nếu `attemptId === task.currentAttemptId`.
- [ ] Late completion trở thành `stale_result_rejected`.
- [ ] `maxAttempts = 2`; không retry vô hạn.
- [ ] Worker Run failed có thể retry một lần; document coarse retry policy.

## Timeout semantics

```text
Attempt A1 starts
→ task.currentAttemptId = A1
→ A1 timeout
→ invalidate A1
→ task ready
→ Attempt A2 starts
→ task.currentAttemptId = A2
→ A1 returns late
→ reject because A1 != A2
```

Không dùng lease token hoặc heartbeat.

## Automated tests

- [ ] Existing Playground conversation vẫn persist.
- [ ] Existing one-active-Run-per-Agent test vẫn pass.
- [ ] Managed Run trả completion promise đúng terminal state.
- [ ] Correlation metadata đúng task/attempt.
- [ ] Timeout đánh dấu attempt cũ invalid.
- [ ] Retry tạo attempt ID mới.
- [ ] Late output của attempt cũ bị reject.
- [ ] Attempt hiện hành completed được accept.
- [ ] Hết hai attempts tạo terminal failure.
- [ ] Cancellation không để Agent kẹt `busy`.

## Definition of Done

- Không gọi `AgentRunner` trực tiếp từ frontend hoặc API route.
- Không duplicate workspace/session/status logic của AgentService.
- Baseline tests không thay đổi semantics.
- Timeout/retry/stale completion có automated evidence.
- `npm run check` pass.

## Ngoài scope

- Phân loại mọi transient error một cách production-grade.
- Lease/heartbeat/renewal.
- Retry budget theo cost/token.
- Per-task model routing.
